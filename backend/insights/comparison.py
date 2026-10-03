"""
Space-vs-space and period-vs-period comparison.

**Normalisation is the whole point of space comparison.** A 500 m2 office using
more than a 12 m2 store room is not a finding. Ranking therefore uses energy per
m2 and per person, and a space whose area is unknown is **excluded and listed as
excluded** rather than silently ranked on raw energy - which would put the
biggest space at the top every time and call it a result.

Period comparison supports day, week, month and the same weekday a week earlier.
The last one matters because weekday-to-weekend differences otherwise dominate
any week-on-week number.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from spaces.models import Building, Floor, Organisation, Room
from telemetry import rollups

#: Period keys accepted by the period comparison endpoint.
PERIODS = ("day", "week", "month", "same_weekday_last_week")

#: Child level used when comparing the spaces inside a scope.
CHILD_LEVELS = {
    "organisation": "building",
    "building": "floor",
    "floor": "room",
}


def _safe_divide(numerator: Decimal, denominator) -> Decimal | None:
    """Divide, or return None when the denominator is missing or zero."""
    if denominator in (None, 0):
        return None
    denominator = Decimal(str(denominator))
    if denominator == 0:
        return None
    return numerator / denominator


def _children(kind: str, object_id: int):
    """The spaces one level below the given scope."""
    if kind == "organisation":
        return list(Building.objects.filter(organisation_id=object_id))
    if kind == "building":
        return list(Floor.objects.filter(building_id=object_id))
    if kind == "floor":
        return list(Room.objects.filter(floor_id=object_id))
    return []


def _device_filter(kind: str, object_id: int) -> dict:
    return {
        "building": {"room__floor__building_id": object_id},
        "floor": {"room__floor_id": object_id},
        "room": {"room_id": object_id},
    }[kind]


def compare_spaces(
    scope_kind: str,
    scope_id: int,
    visible_organisations,
    start: datetime,
    end: datetime,
    metering: str = "auto",
    normalise_by: str = "area",
) -> dict:
    """
    Compare the spaces one level below a scope, normalised and ranked.

    `normalise_by` is `area`, `occupancy` or `none`. With `none` the ranking is
    raw energy and the response says plainly that it is not comparable between
    differently-sized spaces.
    """
    from telemetry.models import Device

    if scope_kind not in CHILD_LEVELS:
        raise rollups.ScopeError(
            f"Cannot compare inside a {scope_kind}. One of: {', '.join(CHILD_LEVELS)}."
        )
    if normalise_by not in ("area", "occupancy", "none"):
        raise rollups.ScopeError(
            f"Unknown normalise_by '{normalise_by}'. One of: area, occupancy, none."
        )

    child_kind = CHILD_LEVELS[scope_kind]
    children = _children(scope_kind, scope_id)

    rows = []
    excluded = []

    for child in children:
        devices = Device.objects.filter(
            room__floor__building__organisation__in=visible_organisations,
            **_device_filter(child_kind, child.pk),
        )
        selected, applied = rollups.select_devices(devices, metering)
        totals = rollups.totals(rollups.readings_for(selected, start, end))

        energy = Decimal(totals["energy_kwh"])
        area = child.total_area_sqm
        occupancy = child.total_occupancy or None

        per_area = _safe_divide(energy, area)
        per_person = _safe_divide(energy, occupancy)

        denominator_missing = (
            normalise_by == "area" and per_area is None
        ) or (normalise_by == "occupancy" and per_person is None)

        row = {
            "kind": child_kind,
            "id": child.pk,
            # Both forms: `name` for a chart label, `path` for disambiguation,
            # since two floors can hold rooms with the same name.
            "name": child.name,
            "path": str(child),
            "energy_kwh": totals["energy_kwh"],
            "peak_power_w": totals["peak_power_w"],
            "area_sqm": area,
            "occupancy": occupancy,
            "kwh_per_sqm": None if per_area is None else per_area.quantize(Decimal("0.000001")),
            "kwh_per_person": None
            if per_person is None
            else per_person.quantize(Decimal("0.000001")),
            "device_count": selected.count(),
            "metering_applied": applied,
            "sample_count": totals["sample_count"],
        }

        if denominator_missing:
            row["excluded_reason"] = (
                f"No {normalise_by} recorded for this space, so a normalised "
                f"comparison would be meaningless. Set it in the spaces API to "
                f"include this space."
            )
            excluded.append(row)
        else:
            rows.append(row)

    sort_key = {
        "area": "kwh_per_sqm",
        "occupancy": "kwh_per_person",
        "none": "energy_kwh",
    }[normalise_by]
    rows.sort(key=lambda item: Decimal(item[sort_key] or 0), reverse=True)

    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    notes = [
        f"Ranked by {sort_key}, highest first.",
    ]
    if normalise_by == "none":
        notes.append(
            "NOT NORMALISED: raw energy is not comparable between spaces of "
            "different sizes. A larger space will rank higher simply for being "
            "larger."
        )
    else:
        notes.append(
            "Normalised, so a large space is not penalised for its size."
        )
    if excluded:
        notes.append(
            f"{len(excluded)} space(s) excluded for a missing {normalise_by} value "
            f"rather than being ranked on raw energy."
        )

    return {
        "scope": {"kind": scope_kind, "id": scope_id},
        "compared_level": child_kind,
        "normalise_by": normalise_by,
        "window": {"from": start, "to": end},
        "results": rows,
        "excluded": excluded,
        "notes": notes,
    }


def period_bounds(period: str, reference: datetime | None = None) -> dict:
    """
    Current and previous window for a period key.

    `same_weekday_last_week` compares a day against the same weekday seven days
    earlier, which is the only honest week-on-week comparison for a load that
    differs between weekdays and weekends.
    """
    if period not in PERIODS:
        raise rollups.ScopeError(
            f"Unknown period '{period}'. One of: {', '.join(PERIODS)}."
        )

    now = reference or timezone.localtime()

    if period == "day":
        current_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_end = current_start + timedelta(days=1)
        previous_start = current_start - timedelta(days=1)
        label = "Today vs yesterday"
    elif period == "same_weekday_last_week":
        current_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_end = current_start + timedelta(days=1)
        previous_start = current_start - timedelta(days=7)
        label = f"{current_start:%A} vs the same weekday last week"
    elif period == "week":
        current_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        current_end = current_start + timedelta(days=7)
        previous_start = current_start - timedelta(days=7)
        label = "This week vs last week"
    else:  # month
        current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (current_start + timedelta(days=31)).replace(day=1)
        current_end = next_month
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        label = "This month vs last month"

    previous_end = previous_start + (current_end - current_start)

    return {
        "period": period,
        "label": label,
        "current": {"from": current_start, "to": current_end},
        "previous": {"from": previous_start, "to": previous_end},
    }


def compare_periods(
    devices,
    period: str,
    metering: str = "auto",
    reference: datetime | None = None,
) -> dict:
    """
    Compare the same scope across two consecutive periods.

    The comparison is **elapsed-time aware**: a part-way-through month compared
    against a whole previous month would always look like a saving. When the
    current window is incomplete, a pro-rated previous figure is reported
    alongside the raw one and the response says which is the fair comparison.
    """
    bounds = period_bounds(period, reference)
    selected, applied = rollups.select_devices(devices, metering)

    def totals_for(window) -> dict:
        return rollups.totals(
            rollups.readings_for(selected, window["from"], window["to"])
        )

    current = totals_for(bounds["current"])
    previous = totals_for(bounds["previous"])

    now = reference or timezone.localtime()
    window_length = bounds["current"]["to"] - bounds["current"]["from"]
    elapsed = min(max(now - bounds["current"]["from"], timedelta(0)), window_length)
    elapsed_fraction = (
        Decimal(elapsed.total_seconds()) / Decimal(window_length.total_seconds())
        if window_length.total_seconds()
        else Decimal("1")
    )
    is_partial = elapsed_fraction < Decimal("0.999")

    current_kwh = Decimal(current["energy_kwh"])
    previous_kwh = Decimal(previous["energy_kwh"])
    comparable_previous = (
        (previous_kwh * elapsed_fraction).quantize(Decimal("0.000001"))
        if is_partial
        else previous_kwh
    )

    change = current_kwh - comparable_previous
    change_percent = (
        (change / comparable_previous * 100).quantize(Decimal("0.01"))
        if comparable_previous > 0
        else None
    )

    notes = [bounds["label"]]
    if is_partial:
        notes.append(
            f"The current period is {elapsed_fraction:.1%} elapsed, so the previous "
            f"period's {previous['energy_kwh']} kWh was pro-rated to "
            f"{comparable_previous} kWh for a fair comparison. Comparing against "
            f"the full previous period would show a false saving."
        )
    if current["sample_count"] == 0 or previous["sample_count"] == 0:
        notes.append(
            "One of the periods has no readings, so the change is not meaningful."
        )

    return {
        "period": period,
        "label": bounds["label"],
        "metering_applied": applied,
        "device_count": selected.count(),
        "current": {
            "from": bounds["current"]["from"],
            "to": bounds["current"]["to"],
            "energy_kwh": current["energy_kwh"],
            "peak_power_w": current["peak_power_w"],
            "sample_count": current["sample_count"],
        },
        "previous": {
            "from": bounds["previous"]["from"],
            "to": bounds["previous"]["to"],
            "energy_kwh": previous["energy_kwh"],
            "peak_power_w": previous["peak_power_w"],
            "sample_count": previous["sample_count"],
        },
        "elapsed_fraction": elapsed_fraction.quantize(Decimal("0.0001")),
        "is_partial_period": is_partial,
        "comparable_previous_kwh": comparable_previous,
        "change_kwh": change.quantize(Decimal("0.000001")),
        "change_percent": change_percent,
        "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        "notes": notes,
    }

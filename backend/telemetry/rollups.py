"""
Usage rollups: energy and power aggregated by time bucket, device or space.

**The double-counting trap.** A room can hold both a whole-space `mains` meter
and per-appliance meters covering the same load. Naively summing every device in
a space therefore reports roughly twice the real consumption, which would make
every cost estimate (Phase 9) and every space comparison (Phase 16) wrong by a
factor of two.

`select_devices` resolves this explicitly:

* `auto` (default) - use the `mains` meters when the scope has any, otherwise sum
  the appliance meters. This is the physically correct whole-space figure.
* `mains` / `appliance` - force one kind.
* `all` - sum everything, double counting included. Only useful for debugging.

Every response states which mode was applied, so a number is never shown without
saying how it was derived.

**Buckets are local-time.** `TruncHour`/`TruncDay`/`TruncMonth` use Django's
active timezone (`Asia/Kolkata`), so a "day" is a local day. That matters for
time-of-day tariffs in Phase 9 and for the night-load rule in Phase 13; UTC days
would smear both across midnight.

**Gaps are not filled.** A bucket with no readings is absent from the series
rather than reported as zero, because zero energy and "the device was offline"
are different facts and the UI must be able to tell them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Max, Min, QuerySet, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth
from django.utils import timezone

from spaces.models import Building, Floor, Organisation, Room
from telemetry.models import Device, Reading

#: Time bucket sizes accepted by `?period=`.
PERIODS = {
    "hour": TruncHour,
    "day": TruncDay,
    "month": TruncMonth,
}

#: Default window per period, used when `from`/`to` are omitted.
DEFAULT_WINDOWS = {
    "hour": timedelta(days=1),
    "day": timedelta(days=30),
    "month": timedelta(days=365),
}

#: Which device kinds `?metering=` may select.
METERING_MODES = ("auto", "mains", "appliance", "all")

#: Space kinds accepted by `?space=<kind>:<id>`.
SPACE_KINDS = {
    "organisation": (Organisation, "room__floor__building__organisation_id"),
    "building": (Building, "room__floor__building_id"),
    "floor": (Floor, "room__floor_id"),
    "room": (Room, "room_id"),
}


class ScopeError(ValueError):
    """The requested scope could not be resolved or is not visible to the caller."""


@dataclass
class Scope:
    """The resolved target of a usage query."""

    kind: str
    label: str
    object_id: int | None
    devices: QuerySet
    #: Area and occupancy, carried through so Phase 16 can normalise.
    area_sqm: Decimal | None = None
    occupancy: int | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.object_id,
            "label": self.label,
            "area_sqm": self.area_sqm,
            "occupancy": self.occupancy,
        }


def resolve_scope(params, visible_organisations: QuerySet) -> Scope:
    """
    Work out which devices a query covers.

    Accepts `?space=<kind>:<id>`, the explicit `?organisation=` / `?building=` /
    `?floor=` / `?room=` / `?device=`, or nothing at all, which means every
    device the caller can see.

    Scoping is applied to a queryset already filtered to the caller's
    organisations, so an id belonging to someone else resolves to "not found"
    rather than leaking.
    """
    visible_devices = Device.objects.filter(
        room__floor__building__organisation__in=visible_organisations
    ).select_related("room__floor__building__organisation")

    if device_id := params.get("device"):
        device = visible_devices.filter(pk=_as_int(device_id, "device")).first()
        if device is None:
            raise ScopeError(f"No visible device with id {device_id}.")
        return Scope(
            kind="device",
            label=device.name,
            object_id=device.pk,
            devices=visible_devices.filter(pk=device.pk),
            area_sqm=device.room.total_area_sqm,
            occupancy=device.room.total_occupancy,
        )

    kind, raw_id = _space_selector(params)
    if kind is None:
        return Scope(
            kind="all",
            label="All visible spaces",
            object_id=None,
            devices=visible_devices,
        )

    model, device_path = SPACE_KINDS[kind]
    object_id = _as_int(raw_id, kind)

    # Confirm the object is visible before using its id as a filter.
    if kind == "organisation":
        instance = visible_organisations.filter(pk=object_id).first()
    else:
        lookup = {
            "building": "organisation__in",
            "floor": "building__organisation__in",
            "room": "floor__building__organisation__in",
        }[kind]
        instance = model.objects.filter(pk=object_id, **{lookup: visible_organisations}).first()

    if instance is None:
        raise ScopeError(f"No visible {kind} with id {object_id}.")

    return Scope(
        kind=kind,
        label=str(instance),
        object_id=object_id,
        devices=visible_devices.filter(**{device_path: object_id}),
        area_sqm=instance.total_area_sqm,
        occupancy=instance.total_occupancy,
    )


def _space_selector(params) -> tuple[str | None, str | None]:
    """Read the scope from `?space=kind:id` or an explicit named parameter."""
    if space := params.get("space"):
        if ":" not in space:
            raise ScopeError(
                "space must be '<kind>:<id>', for example 'building:3'. "
                f"Valid kinds: {', '.join(SPACE_KINDS)}."
            )
        kind, _, raw_id = space.partition(":")
        kind = kind.strip().lower()
        if kind not in SPACE_KINDS:
            raise ScopeError(
                f"Unknown space kind '{kind}'. Valid kinds: {', '.join(SPACE_KINDS)}."
            )
        return kind, raw_id

    for kind in SPACE_KINDS:
        if raw_id := params.get(kind):
            return kind, raw_id
    return None, None


def _as_int(value, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ScopeError(f"{label} id must be an integer, got '{value}'.") from error


def select_devices(devices: QuerySet, metering: str = "auto") -> tuple[QuerySet, str]:
    """
    Pick the devices whose readings represent the scope's consumption.

    Returns the queryset and the mode actually applied, which may differ from the
    requested one: `auto` resolves to `mains` or `appliance` depending on what
    the scope contains.
    """
    if metering not in METERING_MODES:
        raise ScopeError(
            f"Unknown metering mode '{metering}'. One of: {', '.join(METERING_MODES)}."
        )

    if metering == "all":
        return devices, "all"
    if metering == "mains":
        return devices.filter(kind=Device.Kind.MAINS), "mains"
    if metering == "appliance":
        return devices.filter(kind=Device.Kind.APPLIANCE), "appliance"

    # auto: a whole-space meter supersedes the appliance meters beneath it.
    mains = devices.filter(kind=Device.Kind.MAINS)
    if mains.exists():
        return mains, "mains"
    appliances = devices.filter(kind=Device.Kind.APPLIANCE)
    if appliances.exists():
        return appliances, "appliance"
    # Nothing is tagged mains or appliance (e.g. only simulated devices).
    return devices, "all"


def validate_period(period: str) -> str:
    """Reject an unknown period before it is used as a dict key."""
    if period not in PERIODS:
        raise ScopeError(f"Unknown period '{period}'. One of: {', '.join(PERIODS)}.")
    return period


def resolve_window(params, period: str) -> tuple[datetime, datetime]:
    """
    Resolve `from`/`to`, defaulting to a sensible window for the period.

    The period is validated here as well as by the caller, because it indexes
    `DEFAULT_WINDOWS` and an unknown value would otherwise raise `KeyError`
    (a 500) instead of a 400 - but only on requests that omit `from`.
    """
    validate_period(period)
    to_value = _parse_datetime(params.get("to"), "to") or timezone.now()
    from_value = _parse_datetime(params.get("from"), "from")
    if from_value is None:
        from_value = to_value - DEFAULT_WINDOWS[period]
    if from_value >= to_value:
        raise ScopeError("'from' must be earlier than 'to'.")
    return from_value, to_value


def _parse_datetime(value, label: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ScopeError(
            f"{label} must be an ISO-8601 date or datetime, got '{value}'."
        ) from error
    # A bare date is interpreted in the active timezone, matching the buckets.
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def readings_for(devices: QuerySet, start: datetime, end: datetime) -> QuerySet:
    """Readings from the given devices inside [start, end)."""
    return Reading.objects.filter(
        device__in=devices, timestamp__gte=start, timestamp__lt=end
    )


#: Aggregates computed for every bucket and every group.
_AGGREGATES = {
    "energy_wh": Sum("energy_wh"),
    "mean_power_w": Avg("active_power_w"),
    "peak_power_w": Max("active_power_w"),
    "min_power_w": Min("active_power_w"),
    "sample_count": Count("id"),
}


def _finalise(row: dict) -> dict:
    """Add kWh alongside Wh and round to a sensible precision."""
    energy_wh = row.get("energy_wh") or Decimal("0")
    row["energy_wh"] = energy_wh.quantize(Decimal("0.0001"))
    row["energy_kwh"] = (energy_wh / Decimal("1000")).quantize(Decimal("0.000001"))
    for key in ("mean_power_w", "peak_power_w", "min_power_w"):
        value = row.get(key)
        if value is not None:
            row[key] = Decimal(value).quantize(Decimal("0.01"))
    return row


def time_series(readings: QuerySet, period: str) -> list[dict]:
    """
    Aggregate into local-time buckets, oldest first.

    Buckets with no readings are omitted rather than zero-filled.
    """
    validate_period(period)
    truncate = PERIODS[period]
    rows = (
        readings.annotate(bucket=truncate("timestamp"))
        .values("bucket")
        .annotate(**_AGGREGATES)
        .order_by("bucket")
    )
    return [_finalise(dict(row)) for row in rows]


def by_device(readings: QuerySet) -> list[dict]:
    """Totals per device over the whole window, highest energy first."""
    rows = (
        readings.values("device_id", "device__name", "device__kind", "device__room__name")
        .annotate(**_AGGREGATES)
        .order_by("-energy_wh")
    )
    return [
        _finalise(
            {
                "device_id": row["device_id"],
                "device_name": row["device__name"],
                "device_kind": row["device__kind"],
                "room_name": row["device__room__name"],
                **{key: row[key] for key in _AGGREGATES},
            }
        )
        for row in rows
    ]


def by_room(readings: QuerySet) -> list[dict]:
    """Totals per room over the whole window, highest energy first."""
    rows = (
        readings.values("device__room_id", "device__room__name")
        .annotate(**_AGGREGATES)
        .order_by("-energy_wh")
    )
    return [
        _finalise(
            {
                "room_id": row["device__room_id"],
                "room_name": row["device__room__name"],
                **{key: row[key] for key in _AGGREGATES},
            }
        )
        for row in rows
    ]


def totals(readings: QuerySet) -> dict:
    """One row covering the whole window."""
    row = readings.aggregate(**_AGGREGATES, first_at=Min("timestamp"), last_at=Max("timestamp"))
    first_at = row.pop("first_at")
    last_at = row.pop("last_at")
    result = _finalise(dict(row))
    result["first_reading_at"] = first_at
    result["last_reading_at"] = last_at
    return result

"""
Cost and CO2 engines.

Pure functions over plain values, so they are unit-testable without the ORM and
reusable by the Phase 15 savings recommendations.

**Every result carries its own arithmetic.** A bill is returned as a list of
slab lines, a time-of-use adjustment, a fixed charge and a tax line, not as one
number. Phase 15 has to show the formula behind a claimed saving, and Phase 19
has to show the formula behind a bill; both read these breakdowns rather than
re-deriving the maths.

Units: energy in **kWh**, money in **INR**, emissions in **kg CO2**. Power (W/kW)
never appears here - that conversion belongs to the Phase 8 rollups.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from billing.models import DEFAULT_FACTOR_SOURCE, DEFAULT_KG_CO2_PER_KWH

#: Money is rounded to paise at the end of each line, never mid-calculation.
MONEY = Decimal("0.01")
ENERGY = Decimal("0.000001")
MASS = Decimal("0.000001")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def energy(value: Decimal) -> Decimal:
    return Decimal(value).quantize(ENERGY, rounding=ROUND_HALF_UP)


def mass(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MASS, rounding=ROUND_HALF_UP)


# --- Slab energy charge ---------------------------------------------------------


@dataclass
class SlabLine:
    """One slab's contribution to the energy charge."""

    label: str
    from_kwh: Decimal
    to_kwh: Decimal | None
    rate_inr_per_kwh: Decimal
    units_kwh: Decimal
    charge_inr: Decimal

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "from_kwh": self.from_kwh,
            "to_kwh": self.to_kwh,
            "rate_inr_per_kwh": self.rate_inr_per_kwh,
            "units_kwh": energy(self.units_kwh),
            "charge_inr": money(self.charge_inr),
            "formula": (
                f"{energy(self.units_kwh)} kWh x {self.rate_inr_per_kwh} INR/kWh "
                f"= {money(self.charge_inr)} INR"
            ),
        }


def slab_charge(total_kwh: Decimal, slabs) -> tuple[list[SlabLine], Decimal]:
    """
    Apply a cumulative slab tariff to a month's total consumption.

    Slabs are cumulative, as Indian tariffs are: the first `n` kWh are charged at
    the first rate, the next block at the second, and so on. Returns the per-slab
    lines and the total energy charge.

    Consumption above the last bounded slab is charged at that slab's rate when
    no unbounded slab exists, and the caller is told via the returned lines - the
    alternative, dropping the excess, would understate the bill.
    """
    total_kwh = Decimal(total_kwh)
    if total_kwh <= 0 or not slabs:
        return [], Decimal("0")

    lines: list[SlabLine] = []
    charged = Decimal("0")

    for slab in slabs:
        lower = Decimal(slab.from_kwh)
        upper = Decimal(slab.to_kwh) if slab.to_kwh is not None else None

        if total_kwh <= lower:
            break

        block_top = total_kwh if upper is None else min(total_kwh, upper)
        units = block_top - lower
        if units <= 0:
            continue

        charge = units * Decimal(slab.rate_inr_per_kwh)
        lines.append(
            SlabLine(
                label=slab.label or str(slab),
                from_kwh=lower,
                to_kwh=upper,
                rate_inr_per_kwh=Decimal(slab.rate_inr_per_kwh),
                units_kwh=units,
                charge_inr=charge,
            )
        )
        charged += units

    # Consumption beyond the final bounded slab: charge it at the top rate rather
    # than silently billing nothing for it.
    remainder = total_kwh - charged
    if remainder > 0 and slabs:
        top = slabs[-1]
        charge = remainder * Decimal(top.rate_inr_per_kwh)
        lines.append(
            SlabLine(
                label=f"{top.label or 'Top slab'} (above the last defined block)",
                from_kwh=Decimal(top.to_kwh) if top.to_kwh is not None else Decimal(top.from_kwh),
                to_kwh=None,
                rate_inr_per_kwh=Decimal(top.rate_inr_per_kwh),
                units_kwh=remainder,
                charge_inr=charge,
            )
        )

    return lines, sum((line.charge_inr for line in lines), Decimal("0"))


# --- Time-of-use adjustment -----------------------------------------------------


@dataclass
class TouLine:
    """One time-of-use window's adjustment."""

    name: str
    start_hour: int
    end_hour: int
    multiplier: Decimal
    units_kwh: Decimal
    adjustment_inr: Decimal

    def as_dict(self) -> dict:
        direction = "surcharge" if self.multiplier > 1 else "rebate"
        return {
            "name": self.name,
            "window": f"{self.start_hour:02d}:00-{self.end_hour:02d}:00",
            "multiplier": self.multiplier,
            "kind": direction if self.multiplier != 1 else "neutral",
            "units_kwh": energy(self.units_kwh),
            "adjustment_inr": money(self.adjustment_inr),
        }


def tou_adjustment(
    hourly_kwh: dict[int, Decimal],
    effective_rate_inr_per_kwh: Decimal,
    tou_rates,
) -> tuple[list[TouLine], Decimal]:
    """
    Compute the time-of-day surcharge or rebate.

    `hourly_kwh` maps a **local** hour (0-23) to the energy used in it over the
    whole period. The adjustment for a window is

        units_in_window x effective_rate x (multiplier - 1)

    so a multiplier of 1.0 contributes nothing and the slab charge is unchanged.
    `effective_rate` is the blended rate the slabs actually produced
    (energy charge / total kWh), which keeps the adjustment proportional to what
    the customer is really paying per unit instead of to an arbitrary slab.

    An hour covered by several windows uses the first matching one, ordered by
    `start_hour`, so overlapping configuration is deterministic rather than
    double charged.
    """
    rates = list(tou_rates)
    if not rates or not hourly_kwh:
        return [], Decimal("0")

    buckets: dict[int, Decimal] = {}
    for hour, kwh in hourly_kwh.items():
        match = next((rate for rate in rates if rate.covers_hour(int(hour))), None)
        if match is None:
            continue
        buckets[match.pk if match.pk is not None else id(match)] = buckets.get(
            match.pk if match.pk is not None else id(match), Decimal("0")
        ) + Decimal(kwh)

    lines: list[TouLine] = []
    for rate in rates:
        key = rate.pk if rate.pk is not None else id(rate)
        units = buckets.get(key, Decimal("0"))
        if units <= 0:
            continue
        adjustment = (
            units * Decimal(effective_rate_inr_per_kwh) * (Decimal(rate.multiplier) - 1)
        )
        lines.append(
            TouLine(
                name=rate.name,
                start_hour=rate.start_hour,
                end_hour=rate.end_hour,
                multiplier=Decimal(rate.multiplier),
                units_kwh=units,
                adjustment_inr=adjustment,
            )
        )

    return lines, sum((line.adjustment_inr for line in lines), Decimal("0"))


# --- Bill -----------------------------------------------------------------------


@dataclass
class Bill:
    """A complete estimate, with every component kept separate."""

    total_kwh: Decimal
    currency: str
    slab_lines: list[SlabLine] = field(default_factory=list)
    energy_charge_inr: Decimal = Decimal("0")
    tou_lines: list[TouLine] = field(default_factory=list)
    tou_adjustment_inr: Decimal = Decimal("0")
    fixed_charge_inr: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    tax_inr: Decimal = Decimal("0")
    total_inr: Decimal = Decimal("0")
    tariff_name: str = ""
    is_sample: bool = True
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def effective_rate_inr_per_kwh(self) -> Decimal | None:
        if self.total_kwh <= 0:
            return None
        return money(self.total_inr / self.total_kwh)

    def as_dict(self) -> dict:
        return {
            "total_kwh": energy(self.total_kwh),
            "currency": self.currency,
            "energy_charge_inr": money(self.energy_charge_inr),
            "slab_lines": [line.as_dict() for line in self.slab_lines],
            "tou_adjustment_inr": money(self.tou_adjustment_inr),
            "tou_lines": [line.as_dict() for line in self.tou_lines],
            "fixed_charge_inr": money(self.fixed_charge_inr),
            "tax_percent": self.tax_percent,
            "tax_inr": money(self.tax_inr),
            "total_inr": money(self.total_inr),
            "effective_rate_inr_per_kwh": self.effective_rate_inr_per_kwh,
            "tariff": {
                "name": self.tariff_name,
                "is_sample": self.is_sample,
                "source": self.source,
            },
            "notes": self.notes,
        }


def estimate_bill(
    total_kwh: Decimal,
    tariff,
    hourly_kwh: dict[int, Decimal] | None = None,
    include_fixed_charge: bool = True,
) -> Bill:
    """
    Estimate a bill for `total_kwh`.

    `hourly_kwh` enables the time-of-use adjustment. Without it the estimate is
    slabs plus fixed charge only, and a note says the time-of-day component was
    not applied - rather than quietly pretending the tariff has none.

    `include_fixed_charge` is off for sub-month windows where charging a full
    month's standing charge would overstate the cost.
    """
    total_kwh = Decimal(total_kwh)

    if tariff is None:
        return Bill(
            total_kwh=energy(total_kwh),
            currency="INR",
            tariff_name="none configured",
            is_sample=True,
            source="No tariff is configured, so no cost could be estimated.",
            notes=["No active tariff found. Create one or run `manage.py seed_tariffs`."],
        )

    notes: list[str] = []
    slab_lines, energy_charge = slab_charge(total_kwh, tariff.ordered_slabs)
    if not slab_lines and total_kwh > 0:
        notes.append("This tariff has no slabs defined, so the energy charge is zero.")

    effective_rate = energy_charge / total_kwh if total_kwh > 0 else Decimal("0")

    tou_rates = tariff.ordered_tou_rates
    if tou_rates and hourly_kwh:
        tou_lines, tou_total = tou_adjustment(hourly_kwh, effective_rate, tou_rates)
    else:
        tou_lines, tou_total = [], Decimal("0")
        if tou_rates and not hourly_kwh:
            notes.append(
                "Time-of-day rates exist on this tariff but no hourly breakdown was "
                "supplied, so no time-of-day adjustment was applied."
            )

    fixed = Decimal(tariff.fixed_charge_inr_month) if include_fixed_charge else Decimal("0")
    if not include_fixed_charge and tariff.fixed_charge_inr_month > 0:
        notes.append(
            f"The monthly fixed charge of {money(tariff.fixed_charge_inr_month)} INR is "
            f"excluded because this window is shorter than a billing month."
        )

    subtotal = energy_charge + tou_total + fixed
    tax = subtotal * Decimal(tariff.tax_percent) / Decimal("100")

    return Bill(
        total_kwh=total_kwh,
        currency=tariff.currency,
        slab_lines=slab_lines,
        energy_charge_inr=energy_charge,
        tou_lines=tou_lines,
        tou_adjustment_inr=tou_total,
        fixed_charge_inr=fixed,
        tax_percent=Decimal(tariff.tax_percent),
        tax_inr=tax,
        total_inr=subtotal + tax,
        tariff_name=tariff.name,
        is_sample=tariff.is_sample,
        source=tariff.source,
        notes=notes,
    )


# --- Month projection -----------------------------------------------------------


@dataclass
class Projection:
    """A month-end projection from partial data, with its assumptions stated."""

    month: str
    days_in_month: int
    days_elapsed: Decimal
    consumed_kwh: Decimal
    mean_kwh_per_day: Decimal
    projected_kwh: Decimal
    bill_to_date: Bill
    projected_bill: Bill
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "days_in_month": self.days_in_month,
            "days_elapsed": self.days_elapsed,
            "days_remaining": Decimal(self.days_in_month) - self.days_elapsed,
            "consumed_kwh": energy(self.consumed_kwh),
            "mean_kwh_per_day": energy(self.mean_kwh_per_day),
            "projected_kwh": energy(self.projected_kwh),
            "bill_to_date": self.bill_to_date.as_dict(),
            "projected_bill": self.projected_bill.as_dict(),
            "assumptions": self.assumptions,
        }


def project_month(
    consumed_kwh: Decimal,
    as_of: datetime,
    tariff,
    hourly_kwh: dict[int, Decimal] | None = None,
) -> Projection:
    """
    Project a full month from consumption so far.

    The projection is deliberately simple - the mean daily rate so far, held for
    the rest of the month - and says so in `assumptions`. A seasonal or
    weekday-aware projection is a Phase 11 forecasting job; presenting this naive
    figure as if it modelled anything would be dishonest.

    `as_of` is interpreted in whatever timezone it carries; the caller passes
    local time so month boundaries and day counts are local.
    """
    consumed_kwh = Decimal(consumed_kwh)
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]

    # Fractional days, so a projection made at midday is not a day behind.
    elapsed = (
        Decimal(as_of.day - 1)
        + (Decimal(as_of.hour) + Decimal(as_of.minute) / 60) / Decimal("24")
    )
    # Guard the first moments of a month, where elapsed time is ~0.
    elapsed = max(elapsed, Decimal("0.0416667"))  # one hour

    mean_per_day = consumed_kwh / elapsed
    projected_kwh = mean_per_day * Decimal(days_in_month)

    scale = projected_kwh / consumed_kwh if consumed_kwh > 0 else Decimal("0")
    projected_hourly = (
        {hour: Decimal(kwh) * scale for hour, kwh in hourly_kwh.items()}
        if hourly_kwh
        else None
    )

    return Projection(
        month=f"{as_of.year:04d}-{as_of.month:02d}",
        days_in_month=days_in_month,
        days_elapsed=elapsed.quantize(Decimal("0.01")),
        consumed_kwh=consumed_kwh,
        mean_kwh_per_day=mean_per_day,
        projected_kwh=projected_kwh,
        # Month-to-date excludes the standing charge; the projection includes it.
        bill_to_date=estimate_bill(
            consumed_kwh, tariff, hourly_kwh, include_fixed_charge=False
        ),
        projected_bill=estimate_bill(
            projected_kwh, tariff, projected_hourly, include_fixed_charge=True
        ),
        assumptions=[
            f"Consumption so far ({energy(consumed_kwh)} kWh over "
            f"{elapsed.quantize(Decimal('0.01'))} days) continues at the same mean "
            f"daily rate for the remaining "
            f"{(Decimal(days_in_month) - elapsed).quantize(Decimal('0.01'))} days.",
            "No seasonal, weekday or weather adjustment is applied.",
            "Slab rates are applied to the projected monthly total, as slabs are "
            "cumulative over a billing month.",
            "The monthly fixed charge is included in the projection but excluded "
            "from the month-to-date figure.",
        ],
    )


# --- CO2 ------------------------------------------------------------------------


@dataclass
class Emissions:
    """CO2 for an amount of energy, always with the factor's provenance."""

    energy_kwh: Decimal
    kg_co2: Decimal
    kg_co2_per_kwh: Decimal
    factor_name: str
    factor_kind: str
    factor_region: str
    factor_source: str
    factor_is_verified: bool
    is_fallback: bool

    def as_dict(self) -> dict:
        return {
            "energy_kwh": energy(self.energy_kwh),
            "kg_co2": mass(self.kg_co2),
            "formula": (
                f"{energy(self.energy_kwh)} kWh x {self.kg_co2_per_kwh} kg CO2/kWh "
                f"= {mass(self.kg_co2)} kg CO2"
            ),
            "factor": {
                "kg_co2_per_kwh": self.kg_co2_per_kwh,
                "name": self.factor_name,
                "kind": self.factor_kind,
                "region": self.factor_region,
                "source": self.factor_source,
                "is_verified": self.factor_is_verified,
                "is_fallback": self.is_fallback,
            },
        }


def estimate_co2(energy_kwh: Decimal, factor=None) -> Emissions:
    """
    CO2 for `energy_kwh`, as `kWh x factor`.

    When no `EmissionFactor` row is supplied the documented default is used and
    `is_fallback` is set, so the response still names where the number came from.
    The plan requires the factor's source to appear wherever a CO2 figure does.
    """
    energy_kwh = Decimal(energy_kwh)

    if factor is None:
        value = DEFAULT_KG_CO2_PER_KWH
        return Emissions(
            energy_kwh=energy_kwh,
            kg_co2=energy_kwh * value,
            kg_co2_per_kwh=value,
            factor_name="Default static factor",
            factor_kind="static",
            factor_region="India (national grid)",
            factor_source=DEFAULT_FACTOR_SOURCE,
            factor_is_verified=False,
            is_fallback=True,
        )

    value = Decimal(factor.kg_co2_per_kwh)
    return Emissions(
        energy_kwh=energy_kwh,
        kg_co2=energy_kwh * value,
        kg_co2_per_kwh=value,
        factor_name=factor.name,
        factor_kind=factor.kind,
        factor_region=factor.region,
        factor_source=factor.source,
        factor_is_verified=factor.is_verified,
        is_fallback=False,
    )


def hourly_kwh_from_series(series) -> dict[int, Decimal]:
    """
    Fold a Phase 8 hourly series into energy per local hour-of-day.

    The rollup returns one row per hour *bucket*; time-of-use needs energy per
    hour *of the day*, summed across days.

    Each bucket is converted with `timezone.localtime` before its hour is taken.
    Time-of-use windows are defined in local hours, so reading a UTC hour here
    would shift every window by the UTC offset - 5.5 hours for Asia/Kolkata,
    which would put the evening peak in the afternoon.
    """
    buckets: dict[int, Decimal] = {}
    for row in series:
        bucket = row.get("bucket")
        if bucket is None:
            continue
        if isinstance(bucket, datetime):
            hour = (
                timezone.localtime(bucket).hour
                if timezone.is_aware(bucket)
                else bucket.hour
            )
        elif isinstance(bucket, date):
            hour = 0
        else:
            hour = int(bucket)
        buckets[hour] = buckets.get(hour, Decimal("0")) + Decimal(row.get("energy_kwh") or 0)
    return buckets

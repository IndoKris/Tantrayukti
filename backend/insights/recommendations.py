"""
Savings recommendations.

Each action computes **kWh, rupees and kg CO2 saved per month**, and returns the
formula and every assumption that went into it. The Mission requires specific
actions with estimated savings; the plan requires the formula and assumptions to
be shown. A saving figure with no visible derivation is indistinguishable from an
invented one, so none is produced here.

Money comes from the Phase 9 tariff engine and CO2 from the Phase 9 emission
factor, so a recommendation cannot disagree with the bill shown next to it.

Savings are **estimates with stated assumptions**, never promises. Every action
carries a `confidence` and an `assumptions` list, and the payback figure for a
paid action states the capital cost it assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from billing import engines
from billing.models import Tariff

HOURS_PER_DAY = Decimal("24")
DAYS_PER_MONTH = Decimal("30.44")  # mean Gregorian month

#: Assumed capital costs for paid actions, in INR. Clearly marked as assumptions
#: and returned with every payback figure.
ASSUMED_COSTS_INR = {
    "standby_cutoff": Decimal("1200"),  # smart plugs / timer
    "replace_appliance": Decimal("32000"),  # efficient replacement
}


@dataclass
class Action:
    """One recommendation with its full derivation."""

    code: str
    title: str
    detail: str
    kwh_saved_per_month: Decimal
    formula: str
    assumptions: list[str] = field(default_factory=list)
    confidence: str = "medium"
    capital_cost_inr: Decimal | None = None
    effort: str = "low"

    # Filled in by `price_action`.
    inr_saved_per_month: Decimal | None = None
    kg_co2_saved_per_month: Decimal | None = None
    payback_months: Decimal | None = None
    pricing: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "effort": self.effort,
            "confidence": self.confidence,
            "savings": {
                "kwh_per_month": engines.energy(self.kwh_saved_per_month),
                "inr_per_month": None
                if self.inr_saved_per_month is None
                else engines.money(self.inr_saved_per_month),
                "kg_co2_per_month": None
                if self.kg_co2_saved_per_month is None
                else engines.mass(self.kg_co2_saved_per_month),
            },
            "formula": self.formula,
            "assumptions": self.assumptions,
            "capital_cost_inr": None
            if self.capital_cost_inr is None
            else engines.money(self.capital_cost_inr),
            "payback_months": None
            if self.payback_months is None
            else round(self.payback_months, 1),
            "pricing": self.pricing,
            "caveat": (
                "An estimate derived from the stated assumptions, not a measured "
                "or guaranteed saving. Phase 21 verifies claimed reductions "
                "against telemetry."
            ),
        }


# --- Action catalogue ----------------------------------------------------------


def action_setpoint_change(context: dict) -> Action | None:
    """
    Raise a cooling setpoint by 1 C.

    Rule of thumb used: roughly 6% of cooling energy per degree. That is an
    assumption, stated as one, not a measurement of this building.
    """
    excess = context.get("excess_kwh_per_month") or Decimal("0")
    hvac_share = Decimal("0.6")
    per_degree = Decimal("0.06")
    degrees = Decimal("1")

    saving = excess * hvac_share * per_degree * degrees
    if saving <= 0:
        return None

    return Action(
        code="setpoint_change",
        title="Raise the cooling setpoint by 1 °C",
        detail=(
            "Increasing the setpoint by one degree reduces compressor runtime "
            "with little effect on comfort."
        ),
        kwh_saved_per_month=saving,
        formula=(
            f"{engines.energy(excess)} kWh/month excess x {hvac_share} HVAC share "
            f"x {per_degree} per °C x {degrees} °C = {engines.energy(saving)} kWh/month"
        ),
        assumptions=[
            f"{hvac_share:.0%} of the excess is cooling or heating load.",
            f"A 1 °C setpoint change alters cooling energy by about {per_degree:.0%} "
            "- an industry rule of thumb, not a measurement of this building.",
            "Occupant comfort is unaffected at this magnitude.",
        ],
        confidence="medium",
        effort="low",
    )


def action_schedule_shift(context: dict) -> Action | None:
    """Switch equipment off outside occupied hours."""
    excess = context.get("excess_kwh_per_month") or Decimal("0")
    hours_outside = Decimal(str(context.get("hours_outside_schedule") or 0))
    if excess <= 0 or hours_outside <= 0:
        return None

    recoverable = Decimal("0.85")
    saving = excess * recoverable

    return Action(
        code="schedule_shift",
        title="Switch off outside occupied hours",
        detail=(
            f"Usage was detected across about {hours_outside} hours per month "
            "outside the occupied window. A timer or scheduler removes most of it."
        ),
        kwh_saved_per_month=saving,
        formula=(
            f"{engines.energy(excess)} kWh/month outside schedule x {recoverable} "
            f"recoverable = {engines.energy(saving)} kWh/month"
        ),
        assumptions=[
            f"{recoverable:.0%} of the out-of-hours energy can be removed; the "
            "remainder is genuinely required (security lighting, refrigeration).",
            "The occupied schedule is correct. No schedule is attached to this "
            "space, so 09:00-19:00 was assumed.",
        ],
        confidence="high",
        effort="low",
    )


def action_standby_cutoff(context: dict) -> Action | None:
    """Cut always-on standby draw with switched sockets or a timer."""
    baseload_extra = context.get("baseload_extra_kwh_per_hour")
    if baseload_extra is None:
        excess = context.get("excess_kwh_per_month") or Decimal("0")
        if excess <= 0:
            return None
        saving = excess * Decimal("0.4")
        formula = (
            f"{engines.energy(excess)} kWh/month excess x 0.4 attributable to "
            f"standby = {engines.energy(saving)} kWh/month"
        )
        assumptions = [
            "40% of the excess is standby or always-on draw, in the absence of a "
            "measured baseload step.",
        ]
    else:
        extra = Decimal(str(baseload_extra))
        saving = extra * HOURS_PER_DAY * DAYS_PER_MONTH
        formula = (
            f"{extra} kWh/h extra baseload x {HOURS_PER_DAY} h/day x "
            f"{DAYS_PER_MONTH} days/month = {engines.energy(saving)} kWh/month"
        )
        assumptions = [
            "The measured baseload step is entirely avoidable load.",
            f"A month is {DAYS_PER_MONTH} days.",
        ]

    if saving <= 0:
        return None

    return Action(
        code="standby_cutoff",
        title="Cut the standby and always-on draw",
        detail=(
            "Put the always-on equipment behind switched sockets or a timer so it "
            "stops drawing power when nothing needs it."
        ),
        kwh_saved_per_month=saving,
        formula=formula,
        assumptions=assumptions,
        confidence="high" if baseload_extra is not None else "low",
        capital_cost_inr=ASSUMED_COSTS_INR["standby_cutoff"],
        effort="low",
    )


def action_replace_appliance(context: dict) -> Action | None:
    """Replace a persistently heavy load with an efficient model."""
    monthly_kwh = context.get("monthly_kwh") or Decimal("0")
    if monthly_kwh <= 0:
        return None

    improvement = Decimal("0.30")
    saving = monthly_kwh * improvement

    return Action(
        code="replace_appliance",
        title="Replace the appliance with an efficient model",
        detail=(
            "A 5-star rated replacement typically draws substantially less for the "
            "same duty."
        ),
        kwh_saved_per_month=saving,
        formula=(
            f"{engines.energy(monthly_kwh)} kWh/month x {improvement} efficiency "
            f"improvement = {engines.energy(saving)} kWh/month"
        ),
        assumptions=[
            f"A replacement is {improvement:.0%} more efficient for the same duty "
            "- a typical figure for an old unit replaced by a 5-star model, not a "
            "measurement of a specific product.",
            f"Capital cost assumed at "
            f"{engines.money(ASSUMED_COSTS_INR['replace_appliance'])} INR.",
            "Usage patterns stay the same after replacement.",
        ],
        confidence="low",
        capital_cost_inr=ASSUMED_COSTS_INR["replace_appliance"],
        effort="high",
    )


CATALOGUE = {
    "setpoint_change": action_setpoint_change,
    "schedule_shift": action_schedule_shift,
    "standby_cutoff": action_standby_cutoff,
    "replace_appliance": action_replace_appliance,
}


# --- Pricing -------------------------------------------------------------------


def price_action(action: Action, tariff, factor) -> Action:
    """
    Attach rupee and CO2 savings using the Phase 9 engines.

    The marginal rate is used, not the average: a saving comes off the *top* of
    the bill, which is the highest slab the customer reaches. Averaging would
    understate the saving on a slab tariff.
    """
    kwh = action.kwh_saved_per_month

    if tariff is None:
        action.pricing = {
            "tariff": None,
            "note": "No tariff configured, so no rupee saving could be computed.",
        }
    else:
        slabs = tariff.ordered_slabs
        marginal_rate = (
            Decimal(slabs[-1].rate_inr_per_kwh) if slabs else Decimal("0")
        )
        action.inr_saved_per_month = kwh * marginal_rate
        action.pricing = {
            "tariff_name": tariff.name,
            "tariff_is_sample": tariff.is_sample,
            "marginal_rate_inr_per_kwh": marginal_rate,
            "rate_basis": (
                "Top slab rate, because a saving is removed from the highest-priced "
                "units first. Using the average rate would understate it."
            ),
            "formula": (
                f"{engines.energy(kwh)} kWh/month x {marginal_rate} INR/kWh = "
                f"{engines.money(action.inr_saved_per_month)} INR/month"
            ),
        }

    emissions = engines.estimate_co2(kwh, factor)
    action.kg_co2_saved_per_month = emissions.kg_co2
    action.pricing["co2"] = {
        "kg_co2_per_kwh": emissions.kg_co2_per_kwh,
        "factor_source": emissions.factor_source,
        "factor_is_fallback": emissions.is_fallback,
        "formula": emissions.as_dict()["formula"],
    }

    if action.capital_cost_inr and action.inr_saved_per_month and action.inr_saved_per_month > 0:
        action.payback_months = action.capital_cost_inr / action.inr_saved_per_month
        action.pricing["payback"] = {
            "formula": (
                f"{engines.money(action.capital_cost_inr)} INR / "
                f"{engines.money(action.inr_saved_per_month)} INR/month = "
                f"{action.payback_months:.1f} months"
            ),
            "note": "Capital cost is an assumption; confirm against a real quote.",
        }

    return action


# --- Entry point ---------------------------------------------------------------


def context_from_anomaly(anomaly) -> dict:
    """Turn an anomaly into the inputs the action catalogue needs."""
    evidence = anomaly.evidence or {}
    excess_per_event = Decimal(str(anomaly.excess_kwh or 0))

    # How often this condition is assumed to recur in a month.
    if anomaly.detector == "rule_baseload_jump":
        occurrences = Decimal("1")
        excess_month = Decimal(str(evidence.get("extra_kwh_per_day") or 0)) * DAYS_PER_MONTH
    elif anomaly.detector == "rule_device_left_on":
        occurrences = Decimal("4")  # assumed weekly recurrence
        excess_month = excess_per_event * occurrences
    else:
        occurrences = Decimal(str(DAYS_PER_MONTH))  # assumed daily recurrence
        excess_month = excess_per_event * occurrences

    hour = evidence.get("hour")
    if hour is None and anomaly.window_start:
        hour = anomaly.window_start.hour
    outside_schedule = hour is not None and not (9 <= int(hour) < 19)

    return {
        "excess_kwh_per_month": excess_month,
        "monthly_kwh": Decimal(str(anomaly.observed_kwh or 0)) * DAYS_PER_MONTH,
        "baseload_extra_kwh_per_hour": (
            evidence.get("baseload_after_kwh_per_hour", 0)
            - evidence.get("baseload_before_kwh_per_hour", 0)
            if "baseload_after_kwh_per_hour" in evidence
            else None
        ),
        "hours_outside_schedule": (
            Decimal(str(evidence.get("run_hours") or 1)) * occurrences
            if outside_schedule
            else Decimal("0")
        ),
        "recurrence_assumption": (
            f"This condition is assumed to recur {occurrences} time(s) per month, "
            f"based on the detector that raised it."
        ),
    }


def recommend(anomaly, tariff=None, factor=None, cause_codes=None) -> dict:
    """
    Recommendations for one anomaly, highest rupee saving first.

    `cause_codes` restricts the catalogue to actions the Phase 14 causes
    suggested, so a recommendation is always tied to a stated cause rather than
    offered generically.
    """
    from billing.models import EmissionFactor

    from insights.causes import rank_causes

    causes = rank_causes(anomaly)
    if cause_codes is None:
        cause_codes = {
            code for cause in causes for code in cause.recommended_action_codes
        }

    tariff = tariff or Tariff.resolve(organisation=anomaly.organisation)
    factor = factor or EmissionFactor.resolve()

    context = context_from_anomaly(anomaly)

    actions: list[Action] = []
    for code in CATALOGUE:
        if cause_codes and code not in cause_codes:
            continue
        action = CATALOGUE[code](context)
        if action is not None:
            actions.append(price_action(action, tariff, factor))

    actions.sort(
        key=lambda item: (item.inr_saved_per_month or Decimal("0")), reverse=True
    )

    total_kwh = sum((a.kwh_saved_per_month for a in actions), Decimal("0"))
    total_inr = sum((a.inr_saved_per_month or Decimal("0") for a in actions), Decimal("0"))
    total_co2 = sum((a.kg_co2_saved_per_month or Decimal("0") for a in actions), Decimal("0"))

    return {
        "anomaly_id": anomaly.pk,
        "linked_causes": [cause.code for cause in causes],
        "context": {
            **{
                key: (engines.energy(value) if isinstance(value, Decimal) else value)
                for key, value in context.items()
            }
        },
        "actions": [action.as_dict() for action in actions],
        "totals_if_all_applied": {
            "kwh_per_month": engines.energy(total_kwh),
            "inr_per_month": engines.money(total_inr),
            "kg_co2_per_month": engines.mass(total_co2),
            "note": (
                "Actions may overlap, so applying all of them will not "
                "necessarily save the sum of their individual estimates."
            ),
        },
    }

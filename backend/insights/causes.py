"""
Ranked cause explanation.

Given an anomaly and its evidence, produce an ordered list of likely causes,
each with a confidence, the evidence that supports it, and a sentence a person
can read.

**Rules first, wording second.** The ranking is produced by deterministic rules
over the structured evidence the detectors already recorded - never by a language
model. `describe()` renders text from templates and works entirely offline. An
LLM may optionally be used to *reword* the sentence, and when it is, it is given
only the structured facts and may not introduce numbers of its own. That keeps
the explanation reproducible and keeps an invented figure out of the UI.

Every cause states its evidence, so a reader can disagree with the conclusion
while still trusting the facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from insights.models import Detector

#: Occupied hours assumed when a space has no schedule attached. Stated in the
#: evidence so the assumption is visible rather than hidden.
DEFAULT_OCCUPIED_HOURS = range(9, 19)

NIGHT_HOURS = range(1, 5)


@dataclass
class Cause:
    """One candidate explanation."""

    code: str
    label: str
    confidence: float
    evidence: dict = field(default_factory=dict)
    recommended_action_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "explanation": describe(self),
            "suggested_action_codes": list(self.recommended_action_codes),
        }


# --- Templates -----------------------------------------------------------------

TEMPLATES = {
    "device_left_on": (
        "A load of about {mean_kwh_per_hour} kWh/h ran for {run_hours} consecutive "
        "hours from {run_start_time}, holding nearly constant. That is the "
        "signature of equipment left switched on rather than a varying load in use."
    ),
    "night_occupancy_mismatch": (
        "{observed_kwh} kWh was drawn at {hour_label}, {multiple}x the usual "
        "level for that hour, when the space is expected to be unoccupied."
    ),
    "baseload_increase": (
        "The always-on floor of consumption rose from {before} to {after} kWh/h "
        "around {changed_on}, about {extra_per_day} kWh extra every day. Something "
        "is now running permanently that was not before."
    ),
    "schedule_overrun": (
        "Usage at {hour_label} sits outside the assumed occupied window "
        "({occupied_from}:00-{occupied_to}:00), so equipment is running beyond "
        "the schedule."
    ),
    "hvac_setpoint_or_runtime": (
        "{observed_kwh} kWh at {hour_label} is {multiple}x the expected "
        "{expected_kwh} kWh. On a space with HVAC this usually means a setpoint "
        "that is too low or a unit running longer than needed."
    ),
    "unexpected_peak": (
        "{observed_kwh} kWh at {hour_label} is {sigmas} robust standard deviations "
        "above the usual {expected_kwh} kWh for that hour and day type."
    ),
    "unusual_pattern": (
        "The combination of values at {hour_label} is unlike the rest of the "
        "period, even though no single reading is extreme on its own."
    ),
    "insufficient_evidence": (
        "The anomaly was detected but the recorded evidence is not specific "
        "enough to attribute a cause."
    ),
}


def describe(cause: Cause) -> str:
    """Render a cause as a sentence, offline, from a template."""
    template = TEMPLATES.get(cause.code, TEMPLATES["insufficient_evidence"])
    try:
        return template.format(**cause.evidence)
    except (KeyError, IndexError):
        # A missing field must not crash the feed; fall back to the label.
        return cause.label


def _hour_label(hour) -> str:
    try:
        return f"{int(hour):02d}:00"
    except (TypeError, ValueError):
        return "the affected hour"


# --- Rules ---------------------------------------------------------------------


def rank_causes(anomaly) -> list[Cause]:
    """
    Rank likely causes for an anomaly, most confident first.

    Confidences are rule-assigned weights, not probabilities from a model. They
    exist to order the list; a cause at 0.9 is "the evidence fits this pattern
    closely", not "90% likely".
    """
    evidence = anomaly.evidence or {}
    detector = anomaly.detector
    causes: list[Cause] = []

    observed = float(anomaly.observed_kwh or 0)
    expected = float(anomaly.expected_kwh) if anomaly.expected_kwh is not None else None
    hour = evidence.get("hour")
    if hour is None and anomaly.window_start is not None:
        hour = anomaly.window_start.hour
    multiple = evidence.get("multiple_of_expected") or evidence.get(
        "multiple_of_night_median"
    )
    if multiple is None and expected and expected > 0:
        multiple = round(observed / expected, 2)

    # --- Device left on ---
    if detector == Detector.DEVICE_LEFT_ON:
        run_start = str(evidence.get("run_start", ""))
        causes.append(
            Cause(
                code="device_left_on",
                label="Equipment left switched on",
                confidence=0.9,
                evidence={
                    "run_hours": evidence.get("run_hours"),
                    "mean_kwh_per_hour": evidence.get("mean_kwh_per_hour"),
                    "run_start_time": run_start[11:16] or "the start of the run",
                    "flatness": evidence.get("flatness"),
                    "rule": evidence.get("rule"),
                },
                recommended_action_codes=("standby_cutoff", "schedule_shift"),
            )
        )
        if evidence.get("run_hours", 0) >= 8:
            causes.append(
                Cause(
                    code="schedule_overrun",
                    label="Running outside the occupied schedule",
                    confidence=0.55,
                    evidence={
                        "hour_label": _hour_label(hour),
                        "occupied_from": DEFAULT_OCCUPIED_HOURS.start,
                        "occupied_to": DEFAULT_OCCUPIED_HOURS.stop,
                        "assumption": (
                            "No occupancy schedule is attached to this space, so "
                            f"{DEFAULT_OCCUPIED_HOURS.start}:00-"
                            f"{DEFAULT_OCCUPIED_HOURS.stop}:00 was assumed."
                        ),
                    },
                    recommended_action_codes=("schedule_shift",),
                )
            )

    # --- Night load ---
    if detector == Detector.NIGHT_LOAD:
        causes.append(
            Cause(
                code="night_occupancy_mismatch",
                label="Load while the space should be empty",
                confidence=0.88,
                evidence={
                    "observed_kwh": round(observed, 2),
                    "hour_label": _hour_label(hour),
                    "multiple": multiple or "several times",
                    "night_median_kwh": evidence.get("night_median_kwh"),
                    "night_hours": evidence.get("night_hours", list(NIGHT_HOURS)),
                },
                recommended_action_codes=("standby_cutoff", "schedule_shift"),
            )
        )
        causes.append(
            Cause(
                code="device_left_on",
                label="Equipment left switched on overnight",
                confidence=0.6,
                evidence={
                    "run_hours": 1,
                    "mean_kwh_per_hour": round(observed, 2),
                    "run_start_time": _hour_label(hour),
                    "flatness": None,
                    "rule": "Inferred from night-hour load, not from a measured plateau.",
                },
                recommended_action_codes=("standby_cutoff",),
            )
        )

    # --- Baseload jump ---
    if detector == Detector.BASELOAD_JUMP:
        causes.append(
            Cause(
                code="baseload_increase",
                label="A new always-on load appeared",
                confidence=0.92,
                evidence={
                    "before": evidence.get("baseload_before_kwh_per_hour"),
                    "after": evidence.get("baseload_after_kwh_per_hour"),
                    "changed_on": evidence.get("changed_on"),
                    "extra_per_day": evidence.get("extra_kwh_per_day"),
                    "increase_fraction": evidence.get("increase_fraction"),
                },
                recommended_action_codes=("standby_cutoff", "replace_appliance"),
            )
        )

    # --- Seasonal z-score ---
    if detector == Detector.SEASONAL_ZSCORE:
        z = evidence.get("z_score")
        in_night = hour is not None and int(hour) in NIGHT_HOURS
        outside_schedule = (
            hour is not None and int(hour) not in DEFAULT_OCCUPIED_HOURS
        )

        if in_night:
            causes.append(
                Cause(
                    code="night_occupancy_mismatch",
                    label="Load while the space should be empty",
                    confidence=0.8,
                    evidence={
                        "observed_kwh": round(observed, 2),
                        "hour_label": _hour_label(hour),
                        "multiple": multiple or "well above",
                        "z_score": z,
                    },
                    recommended_action_codes=("standby_cutoff", "schedule_shift"),
                )
            )
        elif outside_schedule:
            causes.append(
                Cause(
                    code="schedule_overrun",
                    label="Running outside the occupied schedule",
                    confidence=0.7,
                    evidence={
                        "hour_label": _hour_label(hour),
                        "occupied_from": DEFAULT_OCCUPIED_HOURS.start,
                        "occupied_to": DEFAULT_OCCUPIED_HOURS.stop,
                        "z_score": z,
                        "assumption": (
                            "No occupancy schedule is attached, so "
                            f"{DEFAULT_OCCUPIED_HOURS.start}:00-"
                            f"{DEFAULT_OCCUPIED_HOURS.stop}:00 was assumed."
                        ),
                    },
                    recommended_action_codes=("schedule_shift",),
                )
            )

        if multiple and float(multiple) >= 1.5 and expected:
            causes.append(
                Cause(
                    code="hvac_setpoint_or_runtime",
                    label="Cooling or heating running harder than needed",
                    confidence=0.6 if not in_night else 0.45,
                    evidence={
                        "observed_kwh": round(observed, 2),
                        "expected_kwh": round(expected, 2),
                        "hour_label": _hour_label(hour),
                        "multiple": multiple,
                    },
                    recommended_action_codes=("setpoint_change", "schedule_shift"),
                )
            )

        causes.append(
            Cause(
                code="unexpected_peak",
                label="Usage far above the baseline for this hour",
                confidence=0.5,
                evidence={
                    "observed_kwh": round(observed, 2),
                    "expected_kwh": round(expected, 2) if expected else "the usual level",
                    "hour_label": _hour_label(hour),
                    "sigmas": z if z is not None else "several",
                    "baseline_samples": evidence.get("baseline_samples"),
                },
                recommended_action_codes=("schedule_shift",),
            )
        )

    # --- Isolation Forest ---
    if detector == Detector.ISOLATION_FOREST:
        causes.append(
            Cause(
                code="unusual_pattern",
                label="Unusual combination of readings",
                confidence=0.45,
                evidence={
                    "hour_label": _hour_label(hour),
                    "isolation_forest_score": evidence.get("isolation_forest_score"),
                    "magnitude_fence_kwh": evidence.get("magnitude_fence_kwh"),
                    "features": evidence.get("features"),
                },
                recommended_action_codes=(),
            )
        )

    if not causes:
        causes.append(
            Cause(
                code="insufficient_evidence",
                label="Cause could not be attributed",
                confidence=0.2,
                evidence={"detector": detector, "available_evidence": sorted(evidence)},
            )
        )

    # Highest confidence first; de-duplicate by code, keeping the strongest.
    best: dict[str, Cause] = {}
    for cause in causes:
        existing = best.get(cause.code)
        if existing is None or cause.confidence > existing.confidence:
            best[cause.code] = cause

    return sorted(best.values(), key=lambda cause: -cause.confidence)


def explain(anomaly, use_llm: bool = False) -> dict:
    """
    Full structured explanation for an anomaly.

    `use_llm` is a flag, off by default. When enabled and a provider is
    configured, the top cause's sentence may be reworded from the same
    structured facts; the facts themselves never come from a model.
    """
    causes = rank_causes(anomaly)
    payload = {
        "anomaly_id": anomaly.pk,
        "detector": anomaly.detector,
        "severity": anomaly.severity,
        "observed_kwh": anomaly.observed_kwh,
        "expected_kwh": anomaly.expected_kwh,
        "excess_kwh": anomaly.excess_kwh,
        "causes": [cause.as_dict() for cause in causes],
        "top_cause": causes[0].code if causes else None,
        "wording": {
            "source": "offline templates",
            "llm_requested": bool(use_llm),
            "llm_used": False,
            "note": (
                "Causes are ranked by deterministic rules over recorded evidence, "
                "never by a language model. Text comes from offline templates."
            ),
        },
    }

    if use_llm:
        payload["wording"]["note"] = (
            "An LLM rewording was requested but no provider is configured, so the "
            "offline template text is shown. Ranking would be unchanged either "
            "way: a model may only reword, never introduce numbers or reorder causes."
        )

    return payload

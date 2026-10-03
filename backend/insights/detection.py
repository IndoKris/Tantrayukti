"""
Anomaly detection over hourly usage.

Three complementary detectors, because each catches something the others miss:

1. **Seasonal baseline z-score** - compares an hour against the mean and standard
   deviation for *that hour of day on that kind of day* (weekday vs weekend).
   This is what catches "3 kWh at 03:00 when 03:00 is normally 0.4 kWh".
2. **Isolation Forest** - multivariate, catches odd *combinations* (high energy
   with a low peak, say) that no single-variable rule would flag.
3. **Explicit rules** - night load, baseload step change, device left on. These
   exist because they map directly onto causes a person can act on, which is
   what Phase 14 needs.

**No fixed contamination, and no fixed percentile either.** The plan calls out
`contamination=0.02`, which forces Isolation Forest to label exactly 2% of points
as anomalies whether or not anything is wrong. A percentile cutoff on the score
distribution has the same defect in disguise - the 1st percentile is always 1% of
the data - and an earlier version of this module made exactly that mistake, which
its own tests caught by flagging anomalies in a clean week.

What is used instead: `contamination="auto"` so the forest sets its own offset,
**and** the point must independently clear a robust magnitude fence
(`median + 3 x MAD-sigma`) computed from the data. Both conditions must hold, so
a clean period yields no anomalies at all, while a genuinely odd high-usage hour
is still caught.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np

from insights.models import Anomaly, AnomalyState, Detector, Severity

#: A z-score at or above this is abnormal. 3.0 is about 1 in 370 for a normal
#: distribution, which keeps the feed actionable rather than noisy.
Z_THRESHOLD = 3.0

#: Severity cut-offs on the z-score.
Z_SEVERITY = ((8.0, Severity.CRITICAL), (5.0, Severity.HIGH), (3.0, Severity.MEDIUM))

#: Minimum samples for an hour-of-day bucket before its baseline is trusted.
MIN_BASELINE_SAMPLES = 3

#: Hours treated as unoccupied night for the night-load rule (local hours).
NIGHT_HOURS = range(1, 5)

#: Night load above this multiple of the night baseline is flagged.
NIGHT_LOAD_MULTIPLE = 2.5

#: A baseload step of at least this fraction, sustained, is a jump.
BASELOAD_JUMP_FRACTION = 0.5

#: Consecutive hours above the device-left-on threshold before it is flagged.
LEFT_ON_MIN_HOURS = 4

#: Scale factor turning a median absolute deviation into a normal-equivalent
#: standard deviation.
MAD_TO_SIGMA = 1.4826

#: An hour must exceed median + this many robust sigmas to count as high usage.
ROBUST_FENCE_SIGMAS = 3.0

#: A run hour must be at least this multiple of its hour-of-day baseline before
#: it counts towards "device left on".
LEFT_ON_BASELINE_MULTIPLE = 1.8


def robust_stats(values) -> tuple[float, float]:
    """
    Median and a robust sigma from the median absolute deviation.

    Mean and standard deviation are **not** used, because a single large spike
    inflates its own baseline: with n=10, one 12 kWh outlier among 1 kWh hours
    raises the mean and raises the standard deviation so much that the spike
    scores under 3 sigma and goes undetected. That is the classic masking
    problem, and it made the seasonal detector miss exactly the spikes it exists
    to catch. The median and MAD barely move for one outlier.
    """
    array = np.asarray(list(values), dtype=float)
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    sigma = mad * MAD_TO_SIGMA
    # Floor, so a perfectly flat history does not make every wobble infinite.
    return median, max(sigma, 0.05 * max(median, 0.01))


@dataclass
class Observation:
    """One hourly bucket, as the Phase 8 rollups produce it."""

    timestamp: datetime
    energy_kwh: float
    peak_power_w: float = 0.0
    mean_power_w: float = 0.0

    @property
    def hour(self) -> int:
        return self.timestamp.hour

    @property
    def is_weekend(self) -> bool:
        return self.timestamp.weekday() >= 5


@dataclass
class Finding:
    """A detection, before it becomes a stored `Anomaly`."""

    detector: str
    severity: str
    timestamp: datetime
    observed_kwh: float
    title: str
    expected_kwh: float | None = None
    score: float | None = None
    evidence: dict = field(default_factory=dict)

    @property
    def excess_kwh(self) -> float | None:
        if self.expected_kwh is None:
            return None
        return max(0.0, self.observed_kwh - self.expected_kwh)


def observations_from_series(series) -> list[Observation]:
    """Convert a Phase 8 hourly rollup series into observations."""
    return [
        Observation(
            timestamp=row["bucket"],
            energy_kwh=float(row["energy_kwh"]),
            peak_power_w=float(row.get("peak_power_w") or 0),
            mean_power_w=float(row.get("mean_power_w") or 0),
        )
        for row in series
        if row.get("bucket") is not None
    ]


# --- Seasonal baseline ---------------------------------------------------------


def seasonal_baseline(observations: list[Observation]) -> dict[tuple[int, bool], dict]:
    """
    Mean and standard deviation per (hour of day, is_weekend).

    Splitting weekday from weekend matters: an office at 10:00 on Sunday is not
    abnormal for being quiet, and a flat all-days baseline would either flag
    every weekend or miss every weekday problem.
    """
    buckets: dict[tuple[int, bool], list[float]] = {}
    for observation in observations:
        buckets.setdefault((observation.hour, observation.is_weekend), []).append(
            observation.energy_kwh
        )

    baseline = {}
    for key, values in buckets.items():
        if len(values) < MIN_BASELINE_SAMPLES:
            continue
        median, sigma = robust_stats(values)
        baseline[key] = {"mean": median, "std": sigma, "samples": len(values)}
    return baseline


def detect_seasonal(
    observations: list[Observation], baseline: dict | None = None
) -> list[Finding]:
    """Flag hours far from their own hour-of-day/day-type baseline."""
    baseline = baseline if baseline is not None else seasonal_baseline(observations)
    findings = []

    for observation in observations:
        stats = baseline.get((observation.hour, observation.is_weekend))
        if stats is None:
            continue

        z = (observation.energy_kwh - stats["mean"]) / stats["std"]
        if z < Z_THRESHOLD:
            continue

        severity = next(
            (level for cutoff, level in Z_SEVERITY if z >= cutoff), Severity.MEDIUM
        )
        findings.append(
            Finding(
                detector=Detector.SEASONAL_ZSCORE,
                severity=severity,
                timestamp=observation.timestamp,
                observed_kwh=observation.energy_kwh,
                expected_kwh=stats["mean"],
                score=round(float(z), 4),
                title=(
                    f"{observation.energy_kwh:.2f} kWh at "
                    f"{observation.timestamp:%H:%M} against an expected "
                    f"{stats['mean']:.2f} kWh"
                ),
                evidence={
                    "hour": observation.hour,
                    "is_weekend": observation.is_weekend,
                    "z_score": round(float(z), 4),
                    "baseline_median_kwh": round(stats["mean"], 4),
                    "baseline_robust_sigma_kwh": round(stats["std"], 4),
                    "baseline_statistic": (
                        "median and MAD-derived sigma, so a spike cannot inflate "
                        "its own baseline and mask itself"
                    ),
                    "baseline_samples": stats["samples"],
                    "threshold_z": Z_THRESHOLD,
                    "multiple_of_expected": round(
                        observation.energy_kwh / stats["mean"], 2
                    )
                    if stats["mean"] > 0
                    else None,
                },
            )
        )
    return findings


# --- Isolation Forest ----------------------------------------------------------


def detect_isolation_forest(observations: list[Observation]) -> list[Finding]:
    """
    Multivariate outliers, with a threshold validated against the data.

    `contamination="auto"` plus a percentile cutoff on the training scores means
    a clean period produces no findings. A fixed `contamination` would force a
    constant fraction of hours to be labelled anomalous regardless of whether
    anything was wrong, which is the failure the plan warns against.
    """
    if len(observations) < 48:
        return []

    from sklearn.ensemble import IsolationForest

    from ml.config import RANDOM_SEED

    features = np.asarray(
        [
            [
                observation.energy_kwh,
                observation.peak_power_w,
                observation.hour,
                1.0 if observation.is_weekend else 0.0,
            ]
            for observation in observations
        ],
        dtype=float,
    )

    model = IsolationForest(
        n_estimators=100,
        contamination="auto",  # the forest sets its own offset
        random_state=RANDOM_SEED,
    )
    model.fit(features)
    scores = model.decision_function(features)
    flagged_by_forest = model.predict(features) == -1

    # Independent magnitude fence from the data, computed **per hour-of-day and
    # day-type**. A single global fence is wrong whenever the load is bimodal: an
    # office runs ~6 kW on weekday afternoons and near zero at weekends, so the
    # whole-series median sits low and every normal weekday peak clears a global
    # fence. Measured on 14 clean simulated office days that flagged 19% of hours.
    # Against its own hour-of-day baseline, a normal weekday peak is ordinary.
    baseline = seasonal_baseline(observations)
    global_median, global_sigma = robust_stats(
        [observation.energy_kwh for observation in observations]
    )

    def fence_for(observation: Observation) -> float:
        stats = baseline.get((observation.hour, observation.is_weekend))
        if stats is None:
            return global_median + ROBUST_FENCE_SIGMAS * global_sigma
        return stats["mean"] + ROBUST_FENCE_SIGMAS * stats["std"]

    findings = []
    for observation, score, is_outlier in zip(observations, scores, flagged_by_forest):
        # Both conditions must hold, and only high usage is actionable: a quiet
        # hour is not a problem to act on.
        fence = fence_for(observation)
        if not math.isfinite(fence) or not is_outlier or observation.energy_kwh <= fence:
            continue

        stats = baseline.get((observation.hour, observation.is_weekend))
        expected = stats["mean"] if stats else global_median

        findings.append(
            Finding(
                detector=Detector.ISOLATION_FOREST,
                severity=Severity.MEDIUM,
                timestamp=observation.timestamp,
                observed_kwh=observation.energy_kwh,
                expected_kwh=expected,
                score=round(float(score), 6),
                title=(
                    f"Unusual usage pattern at {observation.timestamp:%d %b %H:%M} "
                    f"({observation.energy_kwh:.2f} kWh)"
                ),
                evidence={
                    "isolation_forest_score": round(float(score), 6),
                    "flagged_by_forest": True,
                    "contamination": "auto",
                    "magnitude_fence_kwh": round(fence, 4),
                    "fence_basis": "hour-of-day and day-type robust baseline",
                    "threshold_rule": (
                        "Isolation Forest outlier (contamination=auto, the model's "
                        "own offset) AND energy above this hour-of-day baseline's "
                        f"median + {ROBUST_FENCE_SIGMAS} robust sigma. No fixed "
                        "fraction of points is labelled anomalous."
                    ),
                    "features": ["energy_kwh", "peak_power_w", "hour", "is_weekend"],
                },
            )
        )
    return findings


# --- Explicit rules ------------------------------------------------------------


def detect_night_load(observations: list[Observation]) -> list[Finding]:
    """Load during unoccupied night hours, well above the usual night level."""
    night = [o for o in observations if o.hour in NIGHT_HOURS]
    if len(night) < MIN_BASELINE_SAMPLES:
        return []

    values = [o.energy_kwh for o in night]
    reference = float(np.median(values))
    if reference <= 0:
        reference = 0.01

    findings = []
    for observation in night:
        multiple = observation.energy_kwh / reference
        if multiple < NIGHT_LOAD_MULTIPLE:
            continue

        severity = (
            Severity.HIGH if multiple >= NIGHT_LOAD_MULTIPLE * 2 else Severity.MEDIUM
        )
        findings.append(
            Finding(
                detector=Detector.NIGHT_LOAD,
                severity=severity,
                timestamp=observation.timestamp,
                observed_kwh=observation.energy_kwh,
                expected_kwh=reference,
                score=round(multiple, 4),
                title=(
                    f"{observation.energy_kwh:.2f} kWh drawn at "
                    f"{observation.timestamp:%H:%M}, when the space should be empty"
                ),
                evidence={
                    "hour": observation.hour,
                    "night_hours": list(NIGHT_HOURS),
                    "night_median_kwh": round(reference, 4),
                    "multiple_of_night_median": round(multiple, 2),
                    "threshold_multiple": NIGHT_LOAD_MULTIPLE,
                    "rule": "Energy during unoccupied night hours well above the usual night level.",
                },
            )
        )
    return findings


def detect_baseload_jump(observations: list[Observation]) -> list[Finding]:
    """
    A step change in the overnight minimum that persists.

    Baseload is the floor of consumption - always-on equipment. A sustained step
    up means something new is running permanently, which is both expensive and
    easy to miss because it never looks like a spike.
    """
    if len(observations) < 24 * 4:
        return []

    by_day: dict[object, list[float]] = {}
    for observation in observations:
        by_day.setdefault(observation.timestamp.date(), []).append(observation.energy_kwh)

    days = sorted(by_day)
    if len(days) < 4:
        return []

    # Daily baseload = that day's minimum hourly energy.
    baseloads = {day: min(by_day[day]) for day in days if len(by_day[day]) >= 12}
    ordered = [(day, baseloads[day]) for day in days if day in baseloads]
    if len(ordered) < 4:
        return []

    half = len(ordered) // 2
    earlier = [value for _, value in ordered[:half]]
    later = [value for _, value in ordered[half:]]

    before = float(np.median(earlier))
    after = float(np.median(later))
    if before <= 0:
        return []

    increase = (after - before) / before
    if increase < BASELOAD_JUMP_FRACTION:
        return []

    first_affected_day = ordered[half][0]
    timestamp = next(
        o.timestamp for o in observations if o.timestamp.date() == first_affected_day
    )
    hours_per_day = 24
    severity = Severity.HIGH if increase >= 1.0 else Severity.MEDIUM

    return [
        Finding(
            detector=Detector.BASELOAD_JUMP,
            severity=severity,
            timestamp=timestamp,
            observed_kwh=after * hours_per_day,
            expected_kwh=before * hours_per_day,
            score=round(increase, 4),
            title=(
                f"Always-on load rose {increase:.0%}, from {before:.2f} to "
                f"{after:.2f} kWh per hour"
            ),
            evidence={
                "baseload_before_kwh_per_hour": round(before, 4),
                "baseload_after_kwh_per_hour": round(after, 4),
                "increase_fraction": round(increase, 4),
                "threshold_fraction": BASELOAD_JUMP_FRACTION,
                "changed_on": str(first_affected_day),
                "extra_kwh_per_day": round((after - before) * hours_per_day, 4),
                "rule": "Median daily minimum hourly energy stepped up and stayed up.",
            },
        )
    ]


def detect_device_left_on(observations: list[Observation]) -> list[Finding]:
    """
    A load running continuously for hours at near-constant power.

    The signature of something left switched on: not a spike, but a plateau that
    does not follow the usual daily shape.
    """
    if len(observations) < LEFT_ON_MIN_HOURS * 2:
        return []

    values = [o.energy_kwh for o in observations]
    median = float(np.median(values))
    if median <= 0:
        return []

    # Compare each hour against its OWN hour-of-day baseline, not the global
    # median. A normal evening peak is several times the daily median and holds
    # steady for hours, so a global threshold flagged every evening as a device
    # left on. Against its own 19:00 baseline, a normal evening peak is ordinary.
    baseline = seasonal_baseline(observations)

    def is_elevated(observation: Observation) -> bool:
        stats = baseline.get((observation.hour, observation.is_weekend))
        reference = stats["mean"] if stats else median
        if reference <= 0:
            reference = median
        return observation.energy_kwh >= reference * LEFT_ON_BASELINE_MULTIPLE

    findings = []

    run_start = None
    run: list[Observation] = []

    for observation in [*observations, None]:
        above = observation is not None and is_elevated(observation)
        if above:
            if run_start is None:
                run_start = observation.timestamp
            run.append(observation)
            continue

        if run_start is not None and len(run) >= LEFT_ON_MIN_HOURS:
            energies = [o.energy_kwh for o in run]
            spread = (max(energies) - min(energies)) / max(np.mean(energies), 0.01)
            # A plateau, not a varying load: low spread across the run.
            if spread <= 0.45:
                findings.append(
                    Finding(
                        detector=Detector.DEVICE_LEFT_ON,
                        severity=Severity.HIGH
                        if len(run) >= LEFT_ON_MIN_HOURS * 2
                        else Severity.MEDIUM,
                        timestamp=run_start,
                        observed_kwh=float(sum(energies)),
                        expected_kwh=median * len(run),
                        score=round(float(np.mean(energies) / median), 4),
                        title=(
                            f"Load held near {np.mean(energies):.2f} kWh/h for "
                            f"{len(run)} hours from {run_start:%d %b %H:%M}"
                        ),
                        evidence={
                            "run_hours": len(run),
                            "run_start": run_start.isoformat(),
                            "run_end": run[-1].timestamp.isoformat(),
                            "mean_kwh_per_hour": round(float(np.mean(energies)), 4),
                            "median_kwh_per_hour": round(median, 4),
                            "flatness": round(float(spread), 4),
                            "threshold_hours": LEFT_ON_MIN_HOURS,
                            "baseline_multiple_required": LEFT_ON_BASELINE_MULTIPLE,
                            "rule": (
                                "Sustained near-constant load at least "
                                f"{LEFT_ON_BASELINE_MULTIPLE}x each hour's own "
                                "hour-of-day baseline for several consecutive "
                                "hours. Compared per hour-of-day so a normal "
                                "evening peak is not mistaken for a device left on."
                            ),
                        },
                    )
                )
        run_start = None
        run = []

    return findings


# --- Pipeline ------------------------------------------------------------------

DETECTORS = (
    detect_seasonal,
    detect_isolation_forest,
    detect_night_load,
    detect_baseload_jump,
    detect_device_left_on,
)


def detect_all(observations: list[Observation]) -> list[Finding]:
    """Run every detector and return the findings, worst first."""
    findings: list[Finding] = []
    for detector in DETECTORS:
        findings.extend(detector(observations))

    from insights.models import SEVERITY_RANK

    findings.sort(
        key=lambda finding: (-SEVERITY_RANK.get(finding.severity, 0), finding.timestamp)
    )
    return findings


def persist_findings(device, findings: list[Finding], window_hours: int = 1) -> dict:
    """
    Store findings as `Anomaly` rows, idempotently.

    Re-running detection over the same window updates the existing row rather
    than duplicating it, so the feed stays stable while the detector improves.
    An anomaly a person already resolved is **not** reopened.
    """
    created = updated = skipped = 0

    for finding in findings:
        window_end = finding.timestamp + timedelta(hours=window_hours)
        existing = Anomaly.objects.filter(
            device=device, detector=finding.detector, window_start=finding.timestamp
        ).first()

        if existing and existing.state in {AnomalyState.RESOLVED, AnomalyState.DISMISSED}:
            skipped += 1
            continue

        defaults = {
            "severity": finding.severity,
            "window_end": window_end,
            "observed_kwh": Decimal(str(round(finding.observed_kwh, 4))),
            "expected_kwh": None
            if finding.expected_kwh is None
            else Decimal(str(round(finding.expected_kwh, 4))),
            "excess_kwh": None
            if finding.excess_kwh is None
            else Decimal(str(round(finding.excess_kwh, 4))),
            "score": finding.score,
            "title": finding.title,
            "evidence": finding.evidence,
        }

        _, was_created = Anomaly.objects.update_or_create(
            device=device,
            detector=finding.detector,
            window_start=finding.timestamp,
            defaults=defaults,
        )
        created += int(was_created)
        updated += int(not was_created)

    return {
        "created": created,
        "updated": updated,
        "skipped_already_closed": skipped,
        "findings": len(findings),
    }

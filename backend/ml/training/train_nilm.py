"""
NILM: step-change appliance disaggregation.

    cd backend
    python -m ml.training.train_nilm --small

**This is the step-change fallback, and it is the only NILM implemented.** The
plan's fallback for an unavailable UK-DALE dataset is exactly this, with metrics
marked "not evaluated". UK-DALE is not downloaded by this project, so there are
**no ground-truth appliance labels to score against**, and therefore no accuracy,
precision or F1 figure is produced. `metrics.json` records
`status: "not evaluated"` with the reason, rather than a number computed against
the detector's own output - which would measure nothing.

What the detector does: find sustained step changes in the aggregate power
series and match each rise to a later fall of similar magnitude, yielding
inferred on/off events with an energy estimate per event. Edges are matched by
magnitude because a 1500 W rise is far more likely to be released by a 1500 W
fall than by a 60 W one.

A CNN+LSTM trainer is deliberately **not** included: training a supervised
disaggregator with no labels would produce a model whose output could not be
checked, and the plan's honesty rule makes that worse than useless.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config as ml_config

HOUSEHOLD_FILE = "household_hourly.csv"

#: A change smaller than this is noise, not an appliance switching.
MIN_STEP_W = 150.0

#: A step must persist for at least this many samples to count.
MIN_PERSISTENCE = 2

#: A fall matches a rise when within this fraction of its magnitude.
MAGNITUDE_TOLERANCE = 0.45

#: An unmatched rise is closed after this many samples.
MAX_EVENT_SAMPLES = 24 * 3


@dataclass
class Event:
    """One inferred appliance on/off cycle."""

    start_index: int
    end_index: int
    start_time: str
    end_time: str
    magnitude_w: float
    duration_hours: float
    energy_kwh: float
    matched: bool

    def as_dict(self) -> dict:
        return asdict(self)


def detect_step_changes(
    power_w: np.ndarray,
    timestamps,
    interval_hours: float = 1.0,
    min_step_w: float = MIN_STEP_W,
) -> list[Event]:
    """
    Find sustained rises and pair each with a later fall of similar size.

    Returns the inferred events. An unmatched rise is still reported, with
    `matched=False`, so the caller can see the detector's uncertainty rather than
    only its confident output.
    """
    power_w = np.asarray(power_w, dtype=float)
    if len(power_w) < MIN_PERSISTENCE * 2 + 1:
        return []

    deltas = np.diff(power_w)
    events: list[Event] = []
    open_rises: list[tuple[int, float]] = []

    for index, delta in enumerate(deltas):
        if abs(delta) < min_step_w:
            continue

        # Persistence check: the level must actually hold after the step.
        after = power_w[index + 1 : index + 1 + MIN_PERSISTENCE]
        if len(after) < MIN_PERSISTENCE:
            continue
        before = power_w[max(0, index - MIN_PERSISTENCE + 1) : index + 1]
        if abs(float(after.mean()) - float(before.mean())) < min_step_w * 0.6:
            continue

        if delta > 0:
            open_rises.append((index + 1, float(delta)))
            continue

        # A fall: close the most recent rise of comparable magnitude.
        fall = abs(float(delta))
        match = None
        for position in range(len(open_rises) - 1, -1, -1):
            rise_index, rise = open_rises[position]
            if index + 1 - rise_index > MAX_EVENT_SAMPLES:
                continue
            if abs(rise - fall) <= MAGNITUDE_TOLERANCE * max(rise, fall):
                match = position
                break

        if match is None:
            continue

        rise_index, rise = open_rises.pop(match)
        duration = (index + 1 - rise_index) * interval_hours
        events.append(
            Event(
                start_index=rise_index,
                end_index=index + 1,
                start_time=str(timestamps[rise_index]),
                end_time=str(timestamps[min(index + 1, len(timestamps) - 1)]),
                magnitude_w=round((rise + fall) / 2, 2),
                duration_hours=round(duration, 3),
                energy_kwh=round((rise + fall) / 2 * duration / 1000, 6),
                matched=True,
            )
        )

    # Report what never closed, rather than quietly dropping it.
    for rise_index, rise in open_rises:
        events.append(
            Event(
                start_index=rise_index,
                end_index=len(power_w) - 1,
                start_time=str(timestamps[rise_index]),
                end_time=str(timestamps[-1]),
                magnitude_w=round(rise, 2),
                duration_hours=0.0,
                energy_kwh=0.0,
                matched=False,
            )
        )

    events.sort(key=lambda event: event.start_index)
    return events


def over_attribution_caveats(explained_kwh: float, total_kwh: float) -> list[str]:
    """
    Flag it when the events add up to more energy than actually flowed.

    A naive step-change detector can attribute over 100% of consumption: two
    appliances running at once produce one combined step, and matching a rise to
    a fall can span a period in which something else also switched. The share is
    therefore an upper bound on what the events explain, not a decomposition
    that sums to the total - and a reader seeing 114% deserves to be told that
    rather than left to assume a bug.
    """
    if total_kwh <= 0:
        return []
    share = explained_kwh / total_kwh
    if share <= 1.0:
        return []
    return [
        f"OVER-ATTRIBUTION: the detected events account for {share:.1%} of the "
        f"metered energy, which is more than actually flowed. Overlapping "
        f"appliances produce combined steps and a matched rise-fall pair can "
        f"span other activity, so event energy is an upper bound rather than a "
        f"decomposition that sums to the total. Treat the per-event figures as "
        f"indicative only."
    ]


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ml.training.train_nilm")
    parser.add_argument("--small", action="store_true", help="Use a reduced slice.")
    parser.add_argument(
        "--data", type=Path, default=ml_config.PROCESSED_DIR / HOUSEHOLD_FILE
    )
    parser.add_argument("--artifacts", type=Path, default=ml_config.ARTIFACTS_DIR)
    parser.add_argument("--min-step-w", type=float, default=MIN_STEP_W)
    return parser.parse_args(argv)


def run(argv=None) -> dict:
    args = parse_args(argv)

    if not args.data.exists():
        raise SystemExit(
            f"No dataset at {args.data}. Run: python -m ml.data.prepare --small"
        )

    frame = pd.read_csv(args.data, index_col="timestamp", parse_dates=True).sort_index()
    if args.small:
        frame = frame.iloc[-24 * 60 :]

    # mean_power_kw is kW; the detector works in watts.
    power_w = (frame["mean_power_kw"].to_numpy(dtype=float) * 1000).round(2)
    events = detect_step_changes(
        power_w, list(frame.index), interval_hours=1.0, min_step_w=args.min_step_w
    )

    matched = [event for event in events if event.matched]
    total_kwh = float(frame["energy_kwh"].sum())
    explained_kwh = sum(event.energy_kwh for event in matched)

    sidecar = args.data.with_suffix(args.data.suffix + ".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}

    manifest = {
        "model": "NILM step-change detector",
        "created_by": "ml/training/train_nilm.py",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "approach": (
            "Sustained step-change detection on the aggregate power series, with "
            "rises matched to later falls of comparable magnitude."
        ),
        "parameters": {
            "min_step_w": args.min_step_w,
            "min_persistence_samples": MIN_PERSISTENCE,
            "magnitude_tolerance": MAGNITUDE_TOLERANCE,
            "max_event_samples": MAX_EVENT_SAMPLES,
            "interval_hours": 1.0,
        },
        "results": {
            "samples": int(len(power_w)),
            "events_detected": len(events),
            "events_matched": len(matched),
            "events_unmatched": len(events) - len(matched),
            "total_energy_kwh": round(total_kwh, 4),
            "energy_explained_by_events_kwh": round(explained_kwh, 4),
            "share_explained": round(explained_kwh / total_kwh, 4) if total_kwh else None,
            "largest_events": [event.as_dict() for event in sorted(
                matched, key=lambda event: -event.energy_kwh
            )[:10]],
        },
        "data_provenance": {
            "dataset": provenance.get("dataset"),
            "is_synthetic": provenance.get("is_synthetic"),
        },
        # The honest part.
        "metrics": {
            "status": "not evaluated",
            "reason": (
                "NILM accuracy requires per-appliance ground truth. UK-DALE is not "
                "downloaded by this project, so there are no appliance labels to "
                "score against and no precision, recall or F1 can be computed. "
                "Scoring the detector against its own output would measure nothing."
            ),
        },
        "caveats": over_attribution_caveats(explained_kwh, total_kwh)
        + [
            "This is the step-change fallback the project plan specifies for an "
            "unavailable UK-DALE dataset, not a trained disaggregator.",
            "Events are inferred, not labelled: the detector cannot say which "
            "appliance caused a step, only that a step of that magnitude occurred.",
            "A CNN+LSTM trainer is deliberately omitted: with no labels its output "
            "could not be checked, which is worse than not having it.",
            "Hourly data limits resolution - appliances cycling within an hour are "
            "invisible. Sub-minute data would detect far more.",
        ],
    }

    paths = ml_config.ArtifactPaths(slug="nilm", directory=args.artifacts)
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(
        f"NILM step-change detector | {len(power_w)} samples\n"
        f"  events: {len(events)} detected, {len(matched)} matched to a fall, "
        f"{len(events) - len(matched)} left open\n"
        f"  energy: {explained_kwh:.2f} of {total_kwh:.2f} kWh attributed to events"
        + (f" ({explained_kwh / total_kwh:.1%})" if total_kwh else "")
    )
    print(f"  saved {paths.manifest}")
    print(
        "\nNOTE: metrics are 'not evaluated' - no appliance ground truth is "
        "available, so no accuracy figure is produced."
    )
    return manifest


def main(argv=None) -> int:
    run(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())

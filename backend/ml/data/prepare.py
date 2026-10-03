"""
Build the processed datasets the models train on.

    cd backend
    python -m ml.data.prepare --small      # fast, for the phase check and CI
    python -m ml.data.prepare              # full pipeline
    python -m ml.data.prepare --synthetic  # skip the download entirely

Writes to `ml/data/processed/`:

    household_hourly.csv            hourly load, the Phase 11 forecasting input
    emission_factors_hourly.csv     hourly grid CO2 intensity, the Phase 12 input

and a `<file>.provenance.json` beside each, recording the source, its units,
whether it is synthetic, and what cleaning removed. Downstream phases read that
sidecar so a metric can state what it was computed from instead of assuming the
data was real.

**One download attempt.** If the UCI archive cannot be fetched, the household
series falls back to the synthetic generator, every row is flagged
`is_synthetic=1`, and the provenance says so. The pipeline never retries in a
loop and never blocks (plan rules 5 and the Fallbacks section).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ml.data import clean, synthetic
from ml.data.sources import (
    PROCESSED_DIR,
    SYNTHETIC_EMISSION_PROVENANCE,
    SYNTHETIC_LOAD_PROVENANCE,
    UCI_PROVENANCE,
    DownloadUnavailable,
    Provenance,
    download_uci,
)

#: `--small` row and hour caps. Big enough for a 24-step forecast to be
#: meaningful, small enough for the check to finish in seconds.
SMALL_UCI_ROWS = 120_000  # about 83 days of 1-minute data
SMALL_LOAD_HOURS = 24 * 120
SMALL_EMISSION_HOURS = 24 * 180

HOUSEHOLD_FILE = "household_hourly.csv"
EMISSION_FILE = "emission_factors_hourly.csv"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ml.data.prepare",
        description="Prepare the processed datasets for EcoTrack's models.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Use a reduced slice of data, for the phase check and CI.",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Skip the UCI download and generate the household series instead.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the UCI archive even if it is already on disk.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROCESSED_DIR,
        help=f"Output directory (default: {PROCESSED_DIR}).",
    )
    return parser.parse_args(argv)


# --- Household series ----------------------------------------------------------


def build_household(args) -> tuple[pd.DataFrame, Provenance]:
    """
    Produce the hourly household series, from UCI if possible.

    Returns the frame and its provenance. Falls back to synthetic data on any
    download or parse failure, rather than aborting the run.
    """
    if args.synthetic:
        print("Household series: synthetic (requested with --synthetic).")
        return _synthetic_household(args, reason="requested with --synthetic")

    try:
        path = download_uci(force=args.force_download)
    except DownloadUnavailable as error:
        print(f"Household series: UCI unavailable -> synthetic fallback.\n  {error}")
        return _synthetic_household(args, reason=str(error))

    print(f"Household series: UCI dataset at {path}")
    try:
        raw = clean.load_uci_raw(path, nrows=SMALL_UCI_ROWS if args.small else None)
        cleaned, report = clean.clean_uci(raw)
        hourly = clean.to_hourly(cleaned, report)
    except (ValueError, KeyError, pd.errors.ParserError) as error:
        print(f"Household series: UCI file unusable -> synthetic fallback.\n  {error}")
        return _synthetic_household(args, reason=f"UCI file unusable: {error}")

    if hourly.empty:
        print("Household series: UCI produced no complete hours -> synthetic fallback.")
        return _synthetic_household(args, reason="UCI produced no complete hours")

    hourly["is_synthetic"] = 0

    provenance = Provenance(**UCI_PROVENANCE.as_dict())
    provenance.rows = len(hourly)
    provenance.first_timestamp = str(hourly.index.min())
    provenance.last_timestamp = str(hourly.index.max())
    provenance.notes = [*UCI_PROVENANCE.notes, *report.notes]
    if args.small:
        provenance.notes.append(
            f"--small: only the first {SMALL_UCI_ROWS} raw rows were read."
        )
    provenance.units = {
        **UCI_PROVENANCE.units,
        "energy_kwh": "kWh per hour (mean kW over the hour x 1 h)",
        "mean_power_kw": "kW (mean instantaneous power in the hour)",
        "peak_power_kw": "kW (maximum instantaneous power in the hour)",
    }
    _print_report(report)
    return hourly, provenance


def _synthetic_household(args, reason: str) -> tuple[pd.DataFrame, Provenance]:
    hours = SMALL_LOAD_HOURS if args.small else 24 * 365 * 2
    frame = synthetic.synthetic_hourly_load(hours=hours)

    provenance = Provenance(**SYNTHETIC_LOAD_PROVENANCE.as_dict())
    provenance.rows = len(frame)
    provenance.first_timestamp = str(frame.index.min())
    provenance.last_timestamp = str(frame.index.max())
    provenance.notes = [
        *SYNTHETIC_LOAD_PROVENANCE.notes,
        f"Fallback reason: {reason}.",
        f"Seed {synthetic.DEFAULT_SEED}; the series is reproducible.",
    ]
    return frame, provenance


def _print_report(report: clean.CleaningReport) -> None:
    data = report.as_dict()
    print(
        f"  cleaned: {data['rows_in']} raw rows -> {data['hours_out']} hourly rows "
        f"({data['missing_power_rows']} missing power, "
        f"{data['implausible_power_rows']} implausible power, "
        f"{data['implausible_voltage_rows']} implausible voltage, "
        f"{data['hours_dropped_incomplete']} incomplete hours dropped)"
    )


# --- Emission factor series ----------------------------------------------------


def build_emission_factors(args) -> tuple[pd.DataFrame, Provenance]:
    """Generate the synthetic grid CO2 intensity series. Always synthetic."""
    hours = SMALL_EMISSION_HOURS if args.small else 24 * 730
    frame = synthetic.synthetic_emission_factors(hours=hours)
    summary = synthetic.emission_factor_summary(frame)

    provenance = Provenance(**SYNTHETIC_EMISSION_PROVENANCE.as_dict())
    provenance.rows = len(frame)
    provenance.first_timestamp = str(frame.index.min())
    provenance.last_timestamp = str(frame.index.max())
    provenance.notes = [
        *SYNTHETIC_EMISSION_PROVENANCE.notes,
        f"Seed {synthetic.DEFAULT_SEED + 1}; the series is reproducible.",
        f"Mean {summary['mean_kg_co2_per_kwh']} kg CO2/kWh, range "
        f"{summary['min_kg_co2_per_kwh']}-{summary['max_kg_co2_per_kwh']}.",
        f"Cleanest hour {summary['cleanest_hour']:02d}:00 "
        f"({summary['cleanest_hour_mean']}), dirtiest hour "
        f"{summary['dirtiest_hour']:02d}:00 ({summary['dirtiest_hour_mean']}).",
    ]

    print(
        f"Emission factors: SYNTHETIC, {summary['rows']} hours, "
        f"mean {summary['mean_kg_co2_per_kwh']} kg CO2/kWh "
        f"(cleanest {summary['cleanest_hour']:02d}:00, "
        f"dirtiest {summary['dirtiest_hour']:02d}:00)"
    )
    return frame, provenance


# --- Writing -------------------------------------------------------------------


def write_dataset(frame: pd.DataFrame, provenance: Provenance, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=True)
    sidecar = provenance.write(path)

    label = "SYNTHETIC" if provenance.is_synthetic else "real measured data"
    print(f"  wrote {path} ({len(frame)} rows, {label})")
    print(f"  wrote {sidecar}")


def main(argv=None) -> int:
    args = parse_args(argv)
    out = Path(args.out)

    print(f"Preparing datasets in {out}{' (--small)' if args.small else ''}")

    household, household_provenance = build_household(args)
    write_dataset(household, household_provenance, out / HOUSEHOLD_FILE)

    emissions, emission_provenance = build_emission_factors(args)
    write_dataset(emissions, emission_provenance, out / EMISSION_FILE)

    splits = clean.time_ordered_split(household)
    print(
        "  time-ordered split: "
        + ", ".join(f"{name} {len(part)}" for name, part in splits.items())
        + " (chronological, never random)"
    )

    if household_provenance.is_synthetic:
        print(
            "\nNOTE: the household series is SYNTHETIC. Every metric derived from "
            "it must be labelled synthetic wherever it is reported."
        )
    print(
        "NOTE: the emission factor series is always SYNTHETIC - no real hourly "
        "grid CO2 intensity series is downloaded by this project."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

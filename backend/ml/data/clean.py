"""
Cleaning and hourly resampling.

**The unit conversion this module exists for.** The UCI file records
`Global_active_power` in **kilowatts** sampled every minute, while the
sub-metering columns record **watt-hours per minute**. Averaging kilowatts over
an hour gives kilowatts, not kilowatt-hours; the plan forbids mixing the two, so
every output column here is named for its unit:

    energy_kwh     - energy in the interval            (kWh)
    mean_power_kw  - mean instantaneous power          (kW)
    peak_power_kw  - maximum instantaneous power       (kW)

For a series of 1-minute kW samples, interval energy is
`mean(kW) x interval_hours`. Over a full hour of complete data that is
`mean(kW) x 1`, which is why the two numbers look identical in the output and
why the column names have to disambiguate them.

**Incomplete hours are dropped rather than scaled up.** An hour holding 12 of
its 60 minutes would otherwise contribute an eighth of the energy it should and
quietly bias every model trained on it. `min_coverage` sets the threshold and the
number of hours dropped is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: UCI columns, in file order.
UCI_COLUMNS = [
    "Date",
    "Time",
    "Global_active_power",
    "Global_reactive_power",
    "Voltage",
    "Global_intensity",
    "Sub_metering_1",
    "Sub_metering_2",
    "Sub_metering_3",
]

#: Sampling interval of the raw UCI file.
RAW_INTERVAL_MINUTES = 1

#: Minimum fraction of an hour's samples that must be present to keep the hour.
DEFAULT_MIN_COVERAGE = 0.8

#: Physically implausible readings for a domestic supply, used to drop outliers.
MAX_PLAUSIBLE_POWER_KW = 20.0
VOLTAGE_RANGE_V = (180.0, 280.0)


@dataclass
class CleaningReport:
    """What cleaning did, so the pipeline can state it rather than hide it."""

    rows_in: int = 0
    rows_after_parse: int = 0
    missing_power_rows: int = 0
    implausible_power_rows: int = 0
    implausible_voltage_rows: int = 0
    hours_out: int = 0
    hours_dropped_incomplete: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rows_in": self.rows_in,
            "rows_after_parse": self.rows_after_parse,
            "missing_power_rows": self.missing_power_rows,
            "implausible_power_rows": self.implausible_power_rows,
            "implausible_voltage_rows": self.implausible_voltage_rows,
            "hours_out": self.hours_out,
            "hours_dropped_incomplete": self.hours_dropped_incomplete,
            "notes": self.notes,
        }


def load_uci_raw(path, nrows: int | None = None) -> pd.DataFrame:
    """
    Read the UCI text file into a frame indexed by timestamp.

    `?` is the file's missing-value marker. `nrows` limits the read for `--small`,
    which keeps the check fast without needing a separate sample file.
    """
    frame = pd.read_csv(
        path,
        sep=";",
        na_values=["?", ""],
        low_memory=False,
        nrows=nrows,
    )

    missing = [column for column in UCI_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"The UCI file is missing expected columns: {missing}")

    timestamp = pd.to_datetime(
        frame["Date"] + " " + frame["Time"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )
    frame = frame.drop(columns=["Date", "Time"])
    frame.insert(0, "timestamp", timestamp)

    numeric = [column for column in frame.columns if column != "timestamp"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")

    return frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()


def clean_uci(frame: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """
    Drop unusable rows and record what was removed.

    Rows with no active power are dropped outright: it is the target variable, so
    imputing it would be inventing the thing the model is supposed to predict.
    Implausible values are dropped rather than clipped, because a 90 kW reading
    on a domestic supply is a sensor fault, not a large load.
    """
    report = CleaningReport(rows_in=len(frame), rows_after_parse=len(frame))

    missing_power = frame["Global_active_power"].isna()
    report.missing_power_rows = int(missing_power.sum())
    frame = frame.loc[~missing_power]

    implausible_power = (frame["Global_active_power"] < 0) | (
        frame["Global_active_power"] > MAX_PLAUSIBLE_POWER_KW
    )
    report.implausible_power_rows = int(implausible_power.sum())
    frame = frame.loc[~implausible_power]

    voltage = frame["Voltage"]
    implausible_voltage = voltage.notna() & (
        (voltage < VOLTAGE_RANGE_V[0]) | (voltage > VOLTAGE_RANGE_V[1])
    )
    report.implausible_voltage_rows = int(implausible_voltage.sum())
    frame = frame.loc[~implausible_voltage]

    report.notes.append(
        "Rows with no Global_active_power were dropped, not imputed: it is the "
        "forecasting target, so filling it would fabricate the label."
    )
    return frame, report


def to_hourly(
    frame: pd.DataFrame,
    report: CleaningReport | None = None,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    interval_minutes: int = RAW_INTERVAL_MINUTES,
) -> pd.DataFrame:
    """
    Resample 1-minute samples to hourly rows with explicit units.

    Returns columns:

    * `energy_kwh`    - `mean(kW) x 1 h`, the energy used in the hour
    * `mean_power_kw` - mean instantaneous power in the hour
    * `peak_power_kw` - maximum instantaneous power in the hour
    * `mean_voltage_v`, `mean_current_a`
    * `sample_count`, `coverage` - how complete the hour was
    * calendar features used by every model downstream

    Hours below `min_coverage` are dropped and counted in the report.
    """
    expected_per_hour = 60 / interval_minutes

    grouped = frame.resample("1h")
    hourly = pd.DataFrame(
        {
            "mean_power_kw": grouped["Global_active_power"].mean(),
            "peak_power_kw": grouped["Global_active_power"].max(),
            "mean_voltage_v": grouped["Voltage"].mean(),
            "mean_current_a": grouped["Global_intensity"].mean(),
            "sample_count": grouped["Global_active_power"].count(),
        }
    )

    hourly["coverage"] = hourly["sample_count"] / expected_per_hour

    # mean kW over one hour x 1 h = kWh. Named explicitly so the two never mix.
    hourly["energy_kwh"] = hourly["mean_power_kw"] * 1.0

    before = len(hourly)
    hourly = hourly.loc[hourly["coverage"] >= min_coverage].copy()
    dropped = before - len(hourly)

    hourly = add_calendar_features(hourly)

    if report is not None:
        report.hours_out = len(hourly)
        report.hours_dropped_incomplete = int(dropped)
        report.notes.append(
            f"Hours with under {min_coverage:.0%} of their {int(expected_per_hour)} "
            f"expected samples were dropped ({dropped} hours). Scaling a partial "
            f"hour up would understate or overstate its energy."
        )

    return hourly


def add_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Add the calendar features every model here uses.

    Hour and month are also encoded as sine/cosine pairs so a model sees hour 23
    and hour 0 as adjacent rather than 23 units apart.
    """
    frame = frame.copy()
    index = frame.index

    frame["hour"] = index.hour
    frame["day_of_week"] = index.dayofweek
    frame["month"] = index.month
    frame["is_weekend"] = (index.dayofweek >= 5).astype(int)

    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour"] / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour"] / 24)
    frame["month_sin"] = np.sin(2 * np.pi * (frame["month"] - 1) / 12)
    frame["month_cos"] = np.cos(2 * np.pi * (frame["month"] - 1) / 12)

    return frame


def time_ordered_split(
    frame: pd.DataFrame, train: float = 0.7, validation: float = 0.15
) -> dict[str, pd.DataFrame]:
    """
    Split chronologically, never randomly.

    A random split on a time series leaks the future into the training set and
    produces scores that cannot be reproduced in production. The plan requires a
    time-ordered split, so it is done here, once, for every model to reuse.
    """
    if not 0 < train < 1 or not 0 <= validation < 1 or train + validation >= 1:
        raise ValueError("train and validation must be fractions summing to under 1.")

    frame = frame.sort_index()
    total = len(frame)
    train_end = int(total * train)
    validation_end = train_end + int(total * validation)

    return {
        "train": frame.iloc[:train_end],
        "validation": frame.iloc[train_end:validation_end],
        "test": frame.iloc[validation_end:],
    }

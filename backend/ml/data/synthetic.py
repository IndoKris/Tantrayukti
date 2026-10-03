"""
Synthetic data generators.

Two of them, for two different reasons:

* `synthetic_hourly_load` stands in for the UCI household series when the
  download is unavailable, so Phase 11 can still train and the pipeline never
  blocks. Every row it produces is labelled synthetic.

* `synthetic_emission_factors` generates the grid CO2-intensity rows the Phase 12
  random forest needs. There is no public hourly CO2 intensity series for the
  Indian grid that this project downloads, so there is nothing real to fall back
  to here - the synthetic series is the only source, which makes labelling it
  non-negotiable.

**What "plausible shape" means and does not mean.** The emission-factor generator
encodes three real mechanisms: coal-heavy baseload overnight (high intensity),
solar generation diluting the mix around midday (low intensity), and gas or
liquid-fuel peakers in the evening ramp (high intensity again). The *shape* is
therefore defensible. The *values* are chosen to sit either side of the project's
0.82 kg/kWh static default and are not measurements of any grid. A model trained
on this learns the generator's assumptions; Phase 12 must say so next to its
metrics rather than implying it learned the grid.

Everything is seeded, so a run is reproducible and Phase 12's metrics are
comparable between runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.clean import add_calendar_features

#: Default seed, so repeated runs produce identical data.
DEFAULT_SEED = 20261003

# --- Household load ------------------------------------------------------------

#: Hour-of-day multipliers for a domestic load, normalised around 1.0.
_DIURNAL_SHAPE = np.array(
    [
        0.45, 0.40, 0.38, 0.37, 0.38, 0.45,  # 00-05 overnight trough
        0.70, 1.05, 1.15, 0.95, 0.85, 0.85,  # 06-11 morning peak then settle
        0.90, 0.85, 0.80, 0.85, 1.00, 1.30,  # 12-17 afternoon rise
        1.65, 1.80, 1.70, 1.35, 0.95, 0.60,  # 18-23 evening peak and decline
    ]
)

#: Monthly multipliers: heating in winter, cooling in summer.
_SEASONAL_SHAPE = np.array(
    [1.25, 1.20, 1.05, 0.95, 0.95, 1.05, 1.15, 1.15, 1.00, 0.95, 1.10, 1.25]
)


def synthetic_hourly_load(
    hours: int = 24 * 365,
    start: str = "2024-01-01 00:00",
    mean_kw: float = 1.1,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """
    Generate an hourly household load series shaped like a real one.

    Columns match `clean.to_hourly`, so Phase 11 can train on either source
    without branching. Returns kWh per hour plus the mean and peak power that
    produced it, with units in the column names.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(start=start, periods=hours, freq="1h")

    diurnal = _DIURNAL_SHAPE[index.hour]
    seasonal = _SEASONAL_SHAPE[index.month - 1]
    # Weekends sit slightly higher and flatter: people are at home all day.
    weekend = np.where(index.dayofweek >= 5, 1.12, 1.0)

    # Multiplicative noise keeps the series positive; a slow random walk adds the
    # week-to-week drift a flat sinusoid would lack.
    noise = rng.lognormal(mean=0.0, sigma=0.18, size=hours)
    drift = np.cumsum(rng.normal(0.0, 0.004, size=hours))
    drift = 1 + drift - drift.mean()

    mean_power_kw = mean_kw * diurnal * seasonal * weekend * noise * drift
    mean_power_kw = np.clip(mean_power_kw, 0.05, 18.0)

    # Peaks inside the hour exceed the hourly mean; appliances cycle.
    peak_power_kw = np.clip(mean_power_kw * rng.uniform(1.15, 2.4, size=hours), 0.05, 20.0)

    frame = pd.DataFrame(
        {
            # mean kW over one hour x 1 h = kWh.
            "energy_kwh": mean_power_kw,
            "mean_power_kw": mean_power_kw,
            "peak_power_kw": peak_power_kw,
            "mean_voltage_v": rng.normal(233.0, 2.5, size=hours),
            "mean_current_a": mean_power_kw * 1000 / (233.0 * 0.95),
            "sample_count": 60,
            "coverage": 1.0,
        },
        index=index,
    )
    frame.index.name = "timestamp"
    frame["is_synthetic"] = 1

    return add_calendar_features(frame)


# --- Grid emission factor ------------------------------------------------------

#: Hour-of-day CO2 intensity in kg/kWh. Overnight coal is dirtiest, midday solar
#: cleanest, the evening peak dirty again. Centred near the 0.82 static default.
_INTENSITY_SHAPE = np.array(
    [
        0.93, 0.94, 0.94, 0.93, 0.92, 0.90,  # 00-05 coal baseload
        0.86, 0.81, 0.74, 0.68, 0.63, 0.60,  # 06-11 solar ramping up
        0.58, 0.59, 0.62, 0.68, 0.77, 0.86,  # 12-17 solar fading
        0.92, 0.95, 0.94, 0.93, 0.93, 0.93,  # 18-23 evening peakers
    ]
)

#: Monthly multipliers: the monsoon lifts hydro share, summer leans on thermal.
_INTENSITY_SEASON = np.array(
    [1.02, 1.02, 1.01, 1.03, 1.04, 0.99, 0.94, 0.93, 0.96, 1.00, 1.02, 1.03]
)

#: National demand proxy in MW, used as the `load_mw` feature.
_BASE_LOAD_MW = 160_000.0


def synthetic_emission_factors(
    hours: int = 24 * 730,
    start: str = "2024-01-01 00:00",
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """
    Generate hourly grid CO2 intensity rows for the Phase 12 random forest.

    Features: `hour`, `month`, `day_of_week`, `is_weekend`, the sine/cosine
    encodings, and `load_mw` (a demand proxy). Target: `kg_co2_per_kwh`.

    The relationship is deliberately non-trivial - intensity rises with load
    because peaking plants are dirtier - so a random forest has something real to
    learn and a naive mean baseline is genuinely beatable. That makes the Phase 12
    metrics meaningful as a check on the pipeline, *not* as evidence about the
    actual grid.
    """
    rng = np.random.default_rng(seed + 1)
    index = pd.date_range(start=start, periods=hours, freq="1h")

    # Demand: diurnal shape, seasonal swing, weekday/weekend difference, noise.
    demand_shape = _DIURNAL_SHAPE[index.hour]
    demand_season = _SEASONAL_SHAPE[index.month - 1]
    weekday = np.where(index.dayofweek >= 5, 0.93, 1.0)
    load_mw = (
        _BASE_LOAD_MW
        * (0.72 + 0.28 * demand_shape / _DIURNAL_SHAPE.mean())
        * demand_season
        * weekday
        * rng.normal(1.0, 0.03, size=hours)
    )

    # Intensity: hour-of-day mix, season, and a load-driven term for peakers.
    load_normalised = (load_mw - load_mw.mean()) / load_mw.std()
    intensity = (
        _INTENSITY_SHAPE[index.hour]
        * _INTENSITY_SEASON[index.month - 1]
        * (1 + 0.035 * load_normalised)
        + rng.normal(0.0, 0.012, size=hours)
    )
    intensity = np.clip(intensity, 0.35, 1.15)

    frame = pd.DataFrame(
        {"kg_co2_per_kwh": intensity, "load_mw": load_mw},
        index=index,
    )
    frame.index.name = "timestamp"
    frame["is_synthetic"] = 1

    return add_calendar_features(frame)


def emission_factor_summary(frame: pd.DataFrame) -> dict:
    """Headline statistics, for the provenance sidecar and the data README."""
    intensity = frame["kg_co2_per_kwh"]
    by_hour = frame.groupby("hour")["kg_co2_per_kwh"].mean()
    return {
        "rows": int(len(frame)),
        "mean_kg_co2_per_kwh": round(float(intensity.mean()), 4),
        "min_kg_co2_per_kwh": round(float(intensity.min()), 4),
        "max_kg_co2_per_kwh": round(float(intensity.max()), 4),
        "cleanest_hour": int(by_hour.idxmin()),
        "cleanest_hour_mean": round(float(by_hour.min()), 4),
        "dirtiest_hour": int(by_hour.idxmax()),
        "dirtiest_hour_mean": round(float(by_hour.max()), 4),
    }

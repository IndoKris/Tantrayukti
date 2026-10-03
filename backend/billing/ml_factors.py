"""
Optional model-derived emission factor.

The Phase 9 static factor (0.82 kg CO2/kWh) stays the **default**. This module
adds the Phase 12 random forest as an explicitly-requested option, so a caller
can ask for an hour-by-hour factor instead of one flat number.

Three rules, all from the plan:

1. The static factor remains the fallback. If the model is missing, the response
   uses the static factor and says why.
2. The model is trained on synthetic data, so every response built from it
   carries `trained_on_synthetic` and a caveat.
3. Nothing silently substitutes one for the other - `applied` always states
   which was used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from ml import config as ml_config


class EmissionModelUnavailable(RuntimeError):
    """No trained emission-factor model. Callers fall back to the static factor."""


@dataclass
class EmissionModel:
    """The loaded random forest plus its manifest."""

    model: object
    features: list[str]
    manifest: dict

    @property
    def trained_on_synthetic(self) -> bool:
        return bool(self.manifest.get("data_provenance", {}).get("is_synthetic"))


def load_emission_model(artifacts=None) -> EmissionModel:
    """Load the Phase 12 random forest, or raise `EmissionModelUnavailable`."""
    import joblib

    paths = ml_config.ArtifactPaths(
        slug="emission_rf", directory=artifacts or ml_config.ARTIFACTS_DIR
    )
    if not paths.sklearn_model.exists() or not paths.manifest.exists():
        raise EmissionModelUnavailable(
            f"No emission-factor model at {paths.sklearn_model}. Train with: "
            f"python -m ml.training.train_emission_rf --small"
        )

    bundle = joblib.load(paths.sklearn_model)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    return EmissionModel(
        model=bundle["model"], features=list(bundle["features"]), manifest=manifest
    )


def _feature_row(hour: int, month: int, day_of_week: int, load_mw: float, names) -> list[float]:
    import math

    values = {
        "hour": float(hour),
        "month": float(month),
        "day_of_week": float(day_of_week),
        "is_weekend": 1.0 if day_of_week >= 5 else 0.0,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "month_sin": math.sin(2 * math.pi * (month - 1) / 12),
        "month_cos": math.cos(2 * math.pi * (month - 1) / 12),
        "load_mw": float(load_mw),
    }
    return [values.get(name, 0.0) for name in names]


#: National demand proxy used when the caller has no grid-load figure. The model
#: was trained with load as a feature, so a value is required; the mean of the
#: training range is the least-assuming choice, and it is reported.
DEFAULT_LOAD_MW = 160_000.0


def modelled_co2(
    hourly_kwh: dict[int, Decimal],
    month: int,
    day_of_week: int = 2,
    artifacts=None,
) -> dict:
    """
    CO2 for energy broken down by hour of day, using the hourly modelled factor.

    `hourly_kwh` maps local hour-of-day to kWh, exactly as the Phase 9 time-of-use
    code produces. Returns per-hour factors, the energy-weighted mean factor, and
    the total kg CO2, with provenance.
    """
    import numpy as np

    loaded = load_emission_model(artifacts)

    hours = sorted(hourly_kwh)
    rows = np.asarray(
        [
            _feature_row(hour, month, day_of_week, DEFAULT_LOAD_MW, loaded.features)
            for hour in hours
        ],
        dtype=float,
    )
    factors = loaded.model.predict(rows)

    total_kwh = sum(Decimal(hourly_kwh[hour]) for hour in hours)
    total_kg = sum(
        Decimal(hourly_kwh[hour]) * Decimal(str(round(float(factor), 6)))
        for hour, factor in zip(hours, factors)
    )
    weighted_mean = (total_kg / total_kwh) if total_kwh > 0 else Decimal("0")

    return {
        "applied": "modelled",
        "energy_kwh": total_kwh,
        "kg_co2": total_kg,
        "weighted_mean_kg_co2_per_kwh": weighted_mean,
        "per_hour": [
            {
                "hour": hour,
                "kg_co2_per_kwh": Decimal(str(round(float(factor), 6))),
                "energy_kwh": Decimal(hourly_kwh[hour]),
            }
            for hour, factor in zip(hours, factors)
        ],
        "assumed_load_mw": DEFAULT_LOAD_MW,
        "factor": {
            "name": "Phase 12 random forest (hourly)",
            "kind": "modelled",
            "is_verified": False,
            "trained_on_synthetic": loaded.trained_on_synthetic,
            "source": (
                "ml/training/train_emission_rf.py. "
                + " ".join(loaded.manifest.get("caveats", []))
            ),
        },
        "caveats": [
            "The static 0.82 kg CO2/kWh factor remains the default; this hourly "
            "factor was explicitly requested.",
            "A national demand proxy of "
            f"{DEFAULT_LOAD_MW:,.0f} MW was assumed, because no live grid-load "
            "feed is wired up.",
        ]
        + loaded.manifest.get("caveats", []),
    }

"""
Load a trained forecaster and produce a recursive 24-hour forecast.

The model predicts **one hour ahead**. The 24-hour horizon is built by feeding
each prediction back in as the next input, which is what a deployed forecaster
can actually do with only history available. Error compounds across the horizon,
so `forecast()` says so in its output rather than presenting hour 24 as being as
trustworthy as hour 1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config as ml_config
from ml.training.windows import inverse_target


class ModelUnavailable(RuntimeError):
    """No trained model on disk. The API reports this rather than inventing numbers."""


@dataclass
class LoadedModel:
    """A trained model plus everything needed to use it."""

    predict_fn: object
    scaler: object
    manifest: dict

    @property
    def lookback(self) -> int:
        return int(self.manifest["config"]["lookback_hours"])

    @property
    def horizon(self) -> int:
        return int(self.manifest["config"]["horizon_hours"])

    @property
    def features(self) -> list[str]:
        return list(self.manifest["dataset"]["features"])

    @property
    def target(self) -> str:
        return str(self.manifest["config"]["target"])

    @property
    def n_columns(self) -> int:
        return 1 + len(self.features)

    @property
    def is_fallback(self) -> bool:
        return bool(self.manifest["backend"]["is_fallback"])


def load_model(artifacts: Path | None = None, slug: str = "lstm_forecast") -> LoadedModel:
    """
    Load the trained model, scaler and manifest.

    Raises `ModelUnavailable` when any piece is missing, so the caller can return
    a clear "not trained yet" rather than a fabricated forecast.
    """
    import joblib

    paths = ml_config.ArtifactPaths(
        slug=slug, directory=artifacts or ml_config.ARTIFACTS_DIR
    )

    if not paths.manifest.exists():
        raise ModelUnavailable(
            f"No manifest at {paths.manifest}. Train first: "
            f"python -m ml.training.train_lstm --small"
        )

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))

    if not paths.scaler.exists():
        raise ModelUnavailable(f"No scaler at {paths.scaler}.")
    scaler = joblib.load(paths.scaler)

    backend_name = manifest["backend"]["backend"]
    if backend_name == "keras-lstm":
        if not paths.keras_model.exists():
            raise ModelUnavailable(f"No Keras model at {paths.keras_model}.")
        import keras

        model = keras.models.load_model(paths.keras_model)

        def predict_fn(x):
            return model.predict(x, verbose=0).reshape(-1)
    else:
        if not paths.sklearn_model.exists():
            raise ModelUnavailable(f"No model at {paths.sklearn_model}.")
        model = joblib.load(paths.sklearn_model)

        def predict_fn(x):
            return np.asarray(model.predict(x.reshape(len(x), -1))).reshape(-1)

    return LoadedModel(predict_fn=predict_fn, scaler=scaler, manifest=manifest)


def calendar_features(timestamp, names: list[str]) -> list[float]:
    """Compute the exogenous features for a single future hour."""
    values = {
        "hour_sin": np.sin(2 * np.pi * timestamp.hour / 24),
        "hour_cos": np.cos(2 * np.pi * timestamp.hour / 24),
        "month_sin": np.sin(2 * np.pi * (timestamp.month - 1) / 12),
        "month_cos": np.cos(2 * np.pi * (timestamp.month - 1) / 12),
        "is_weekend": 1.0 if timestamp.weekday() >= 5 else 0.0,
        "hour": float(timestamp.hour),
        "month": float(timestamp.month),
        "day_of_week": float(timestamp.weekday()),
    }
    return [float(values.get(name, 0.0)) for name in names]


def forecast_from_history(
    model: LoadedModel,
    history_kwh: np.ndarray,
    last_timestamp: pd.Timestamp,
    horizon: int | None = None,
) -> dict:
    """
    Produce a recursive multi-step forecast from the last `lookback` hours.

    `history_kwh` must hold at least `model.lookback` values in chronological
    order, in the target's units (kWh).
    """
    horizon = horizon or model.horizon
    history_kwh = np.asarray(history_kwh, dtype=float).reshape(-1)

    if len(history_kwh) < model.lookback:
        raise ValueError(
            f"Need at least {model.lookback} hours of history, got {len(history_kwh)}."
        )

    window_values = history_kwh[-model.lookback :]
    step_timestamps = [
        pd.Timestamp(last_timestamp) + timedelta(hours=offset + 1)
        for offset in range(model.lookback)
    ]
    # Rebuild the scaled window: the target column plus each hour's features.
    rows = []
    base = pd.Timestamp(last_timestamp) - timedelta(hours=model.lookback - 1)
    for index, value in enumerate(window_values):
        stamp = base + timedelta(hours=index)
        rows.append([value, *calendar_features(stamp, model.features)])
    window = model.scaler.transform(np.asarray(rows, dtype=float))

    predictions_scaled = []
    cursor = pd.Timestamp(last_timestamp)

    for _ in range(horizon):
        prediction = float(model.predict_fn(window.reshape(1, model.lookback, -1))[0])
        predictions_scaled.append(prediction)

        cursor = cursor + timedelta(hours=1)
        # Feed the prediction back in as the newest timestep.
        next_row = np.zeros(model.n_columns)
        next_row[0] = prediction
        unscaled_features = calendar_features(cursor, model.features)
        scaled_features = model.scaler.transform(
            np.asarray([[0.0, *unscaled_features]], dtype=float)
        )[0][1:]
        next_row[1:] = scaled_features

        window = np.vstack([window[1:], next_row])

    predicted_kwh = inverse_target(model.scaler, predictions_scaled, model.n_columns)
    # Energy cannot be negative; clip rather than report an impossible value.
    predicted_kwh = np.clip(predicted_kwh, 0.0, None)

    timestamps = [
        (pd.Timestamp(last_timestamp) + timedelta(hours=offset + 1)).isoformat()
        for offset in range(horizon)
    ]

    return {
        "horizon_hours": horizon,
        "lookback_hours": model.lookback,
        "unit": "kWh per hour",
        "points": [
            {"timestamp": stamp, "energy_kwh": round(float(value), 6)}
            for stamp, value in zip(timestamps, predicted_kwh)
        ],
        "total_kwh": round(float(predicted_kwh.sum()), 6),
        "peak_kwh": round(float(predicted_kwh.max()), 6),
        "model": {
            "backend": model.manifest["backend"]["backend"],
            "architecture": model.manifest["architecture"],
            "is_fallback": model.is_fallback,
            "preset": model.manifest["preset"],
            "trained_on": model.manifest["data_provenance"].get("dataset"),
            "trained_on_synthetic": model.manifest["data_provenance"].get("is_synthetic"),
        },
        "caveats": [
            "Produced recursively from a one-step-ahead model: each prediction is "
            "fed back as input, so error compounds and later hours are less "
            "reliable than earlier ones.",
            "Metrics for this model are in ml/artifacts/metrics.json and are "
            "error measures (MAE/RMSE/MAPE/R2), not accuracy.",
        ]
        + (
            [
                "FALLBACK MODEL: this is not the stacked LSTM the plan specifies. "
                "Keras/TensorFlow was unavailable at training time."
            ]
            if model.is_fallback
            else []
        ),
    }

"""
Regression metrics and naive baselines.

**These are error metrics, not accuracy.** The plan is explicit: a regression
result is never to be called "accuracy". Nothing in this module produces a
percentage-correct figure, and the vocabulary used throughout is error.

**A score means nothing without a baseline.** A MAPE of 18% sounds poor until you
learn the persistence baseline scores 31%, or embarrassing until you learn it
scores 12%. Every model here is reported alongside three naive baselines, with
the skill improvement stated as a percentage of the baseline's error:

* `persistence`     - tomorrow's hour equals the last observed value
* `seasonal_naive`  - this hour equals the same hour yesterday
* `train_mean`      - every hour equals the training-set mean

**MAPE and zeros.** Mean absolute percentage error divides by the actual value,
so a single near-zero actual can make it enormous or infinite. Rather than
silently dropping those rows or clipping them, `mape` excludes actuals below a
stated threshold and **reports how many rows it excluded**, so a reader can tell
whether the figure covers the whole test set.
"""

from __future__ import annotations

import numpy as np

#: Actuals with magnitude below this are excluded from MAPE, and counted.
MAPE_FLOOR = 1e-3


def mae(actual, predicted) -> float:
    """Mean absolute error, in the units of the target."""
    actual, predicted = _as_arrays(actual, predicted)
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual, predicted) -> float:
    """Root mean squared error, in the units of the target."""
    actual, predicted = _as_arrays(actual, predicted)
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def mape(actual, predicted) -> tuple[float | None, int]:
    """
    Mean absolute percentage error, and the number of rows excluded.

    Returns `(None, excluded)` when every actual is below the floor, rather than
    returning a number computed from nothing.
    """
    actual, predicted = _as_arrays(actual, predicted)
    usable = np.abs(actual) >= MAPE_FLOOR
    excluded = int((~usable).sum())

    if not usable.any():
        return None, excluded

    errors = np.abs((actual[usable] - predicted[usable]) / actual[usable])
    return float(np.mean(errors) * 100), excluded


def r2(actual, predicted) -> float | None:
    """
    Coefficient of determination.

    Returns None when the actuals have zero variance, where R2 is undefined
    rather than zero.
    """
    actual, predicted = _as_arrays(actual, predicted)
    total = float(np.sum((actual - np.mean(actual)) ** 2))
    if total == 0:
        return None
    residual = float(np.sum((actual - predicted) ** 2))
    return float(1 - residual / total)


def score(actual, predicted, label: str = "") -> dict:
    """Every metric for one series, as a plain dict for `metrics.json`."""
    actual, predicted = _as_arrays(actual, predicted)
    mape_value, mape_excluded = mape(actual, predicted)

    return {
        "label": label,
        "n": int(len(actual)),
        "mae": round(mae(actual, predicted), 6),
        "rmse": round(rmse(actual, predicted), 6),
        "mape_percent": None if mape_value is None else round(mape_value, 4),
        "mape_rows_excluded": mape_excluded,
        "r2": None if r2(actual, predicted) is None else round(r2(actual, predicted), 6),
        "actual_mean": round(float(np.mean(actual)), 6),
        "predicted_mean": round(float(np.mean(predicted)), 6),
        "note": "Error metrics, not accuracy. Units match the target (kWh).",
    }


# --- Baselines -----------------------------------------------------------------


def persistence_baseline(history_last_value: float, horizon: int) -> np.ndarray:
    """Repeat the last observed value across the horizon."""
    return np.full(horizon, float(history_last_value))


def seasonal_naive_baseline(history: np.ndarray, horizon: int, period: int = 24) -> np.ndarray:
    """
    Repeat the same hour from one period ago.

    Usually the strongest of the three for hourly load: it captures the daily
    cycle for free, so a model that cannot beat it has learned nothing useful.
    """
    history = np.asarray(history, dtype=float)
    if len(history) < period:
        return persistence_baseline(history[-1] if len(history) else 0.0, horizon)

    window = history[-period:]
    repeats = int(np.ceil(horizon / period))
    return np.tile(window, repeats)[:horizon]


def mean_baseline(train_mean: float, horizon: int) -> np.ndarray:
    """Predict the training-set mean for every step."""
    return np.full(horizon, float(train_mean))


def baseline_scores(actual, history, train_mean: float, period: int = 24) -> dict:
    """Score all three baselines over the same actuals as the model."""
    actual = np.asarray(actual, dtype=float)
    horizon = len(actual)
    history = np.asarray(history, dtype=float)

    return {
        "persistence": score(
            actual,
            persistence_baseline(history[-1] if len(history) else 0.0, horizon),
            label="Persistence: last observed value repeated",
        ),
        "seasonal_naive": score(
            actual,
            seasonal_naive_baseline(history, horizon, period),
            label=f"Seasonal naive: same hour {period} h earlier",
        ),
        "train_mean": score(
            actual, mean_baseline(train_mean, horizon), label="Training-set mean"
        ),
    }


def skill_vs_baselines(model: dict, baselines: dict) -> dict:
    """
    Improvement over each baseline, as a percentage of the baseline's error.

    Positive means the model has lower error. Reported for MAE and RMSE because
    both are in the target's units and neither is distorted by near-zero
    actuals the way MAPE is.
    """
    skill = {}
    for name, baseline in baselines.items():
        entry = {}
        for metric in ("mae", "rmse"):
            baseline_value = baseline.get(metric)
            model_value = model.get(metric)
            if baseline_value in (None, 0) or model_value is None:
                entry[f"{metric}_improvement_percent"] = None
            else:
                entry[f"{metric}_improvement_percent"] = round(
                    (baseline_value - model_value) / baseline_value * 100, 3
                )
        entry["beats_baseline_on_mae"] = (
            None
            if baseline.get("mae") is None or model.get("mae") is None
            else bool(model["mae"] < baseline["mae"])
        )
        skill[name] = entry
    return skill


def _as_arrays(actual, predicted) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(actual, dtype=float).reshape(-1)
    predicted = np.asarray(predicted, dtype=float).reshape(-1)
    if len(actual) != len(predicted):
        raise ValueError(
            f"actual and predicted must be the same length, got {len(actual)} and {len(predicted)}."
        )
    if len(actual) == 0:
        raise ValueError("Cannot score an empty series.")
    return actual, predicted

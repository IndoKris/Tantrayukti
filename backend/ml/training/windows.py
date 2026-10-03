"""
Supervised windowing and scaling for the forecaster.

**The scaler is fit on the training split only.** Fitting it on the whole series
leaks the test set's mean and range into training and inflates every score -
quietly, and in a way that looks like a better model. The plan requires
train-only fitting; `build_dataset` is the single place it happens.

Window layout: `lookback_hours` of history produce one next-hour prediction.
Each timestep carries the scaled target plus the exogenous calendar features for
*that* hour, so the model can learn "18:00 on a weekday" rather than only the
shape of the preceding curve. The 24-hour horizon is produced by applying the
one-step model recursively (see `ml/inference.py`), which is what the plan asks
for and what a deployed forecaster can actually do.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Dataset:
    """Windowed splits plus the scaler and metadata needed to invert them."""

    x_train: np.ndarray
    y_train: np.ndarray
    x_validation: np.ndarray
    y_validation: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray

    #: Fit on the training split only.
    scaler: object
    feature_names: list[str]
    target: str
    lookback: int

    #: Unscaled test actuals and the index they belong to, for reporting.
    test_index: pd.DatetimeIndex
    train_mean: float
    #: Unscaled training series, used by the baselines.
    train_series: np.ndarray

    @property
    def n_columns(self) -> int:
        """
        Width of a window timestep: the target **plus** the exogenous features.

        Named `n_columns` rather than `n_features` because it includes the
        target, which is what `inverse_target` needs. Calling it `n_features`
        invited an off-by-one against the scaler's width.
        """
        return self.x_train.shape[2]

    @property
    def n_exogenous_features(self) -> int:
        """Number of exogenous features, excluding the target."""
        return self.n_columns - 1

    def summary(self) -> dict:
        return {
            "lookback_hours": self.lookback,
            "features": self.feature_names,
            "target": self.target,
            "n_columns": self.n_columns,
            "n_exogenous_features": self.n_exogenous_features,
            "train_windows": int(len(self.x_train)),
            "validation_windows": int(len(self.x_validation)),
            "test_windows": int(len(self.x_test)),
            "train_mean_kwh": round(float(self.train_mean), 6),
        }


def make_windows(
    values: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    Turn a 2-D array of (timesteps, features) into sliding windows.

    Column 0 must be the target. Returns `(x, y)` where `x` has shape
    `(windows, lookback, features)` and `y` is the next step's target.
    """
    if len(values) <= lookback:
        return (
            np.empty((0, lookback, values.shape[1])),
            np.empty((0,)),
        )

    windows = []
    targets = []
    for start in range(len(values) - lookback):
        windows.append(values[start : start + lookback])
        targets.append(values[start + lookback, 0])

    return np.asarray(windows, dtype="float32"), np.asarray(targets, dtype="float32")


def build_dataset(frame: pd.DataFrame, config) -> Dataset:
    """
    Build scaled, windowed splits from a processed hourly frame.

    Order of operations matters and is deliberate:

    1. trim to `max_rows` (most recent rows, so `--small` trains on recent data);
    2. split chronologically;
    3. fit the scaler on **train only**;
    4. transform all three splits with that scaler;
    5. window each split independently, so no window straddles a split boundary.

    Step 5 matters: windowing before splitting would place windows containing
    training timesteps into the test set.
    """
    from sklearn.preprocessing import MinMaxScaler

    target = config.target
    features = [name for name in config.features if name in frame.columns]
    missing = [name for name in config.features if name not in frame.columns]
    if missing:
        raise ValueError(f"The processed dataset is missing feature columns: {missing}")
    if target not in frame.columns:
        raise ValueError(f"The processed dataset has no target column '{target}'.")

    frame = frame.sort_index()
    if config.max_rows is not None and len(frame) > config.max_rows:
        frame = frame.iloc[-config.max_rows :]

    columns = [target, *features]
    values = frame[columns].astype("float64")

    total = len(values)
    train_end = int(total * config.train_fraction)
    validation_end = train_end + int(total * config.validation_fraction)

    if train_end <= config.lookback_hours:
        raise ValueError(
            f"Not enough data: {total} rows gives a {train_end}-row training split, "
            f"which cannot fill a {config.lookback_hours}-hour lookback window."
        )

    train = values.iloc[:train_end]
    validation = values.iloc[train_end:validation_end]
    test = values.iloc[validation_end:]

    # Fit on train only. This is the line that prevents leakage.
    scaler = MinMaxScaler()
    scaler.fit(train.to_numpy())

    scaled = {
        "train": scaler.transform(train.to_numpy()),
        "validation": scaler.transform(validation.to_numpy())
        if len(validation)
        else np.empty((0, len(columns))),
        "test": scaler.transform(test.to_numpy()) if len(test) else np.empty((0, len(columns))),
    }

    x_train, y_train = make_windows(scaled["train"], config.lookback_hours)
    x_validation, y_validation = make_windows(scaled["validation"], config.lookback_hours)
    x_test, y_test = make_windows(scaled["test"], config.lookback_hours)

    return Dataset(
        x_train=x_train,
        y_train=y_train,
        x_validation=x_validation,
        y_validation=y_validation,
        x_test=x_test,
        y_test=y_test,
        scaler=scaler,
        feature_names=features,
        target=target,
        lookback=config.lookback_hours,
        test_index=test.index[config.lookback_hours :],
        train_mean=float(train[target].mean()),
        train_series=train[target].to_numpy(dtype=float),
    )


def inverse_target(scaler, scaled_values, n_columns: int) -> np.ndarray:
    """
    Invert the scaler for the target column only.

    `MinMaxScaler` expects the full feature width, so the target is padded into
    a zero matrix, inverted, and column 0 taken back out.
    """
    scaled_values = np.asarray(scaled_values, dtype=float).reshape(-1)
    padded = np.zeros((len(scaled_values), n_columns))
    padded[:, 0] = scaled_values
    return scaler.inverse_transform(padded)[:, 0]

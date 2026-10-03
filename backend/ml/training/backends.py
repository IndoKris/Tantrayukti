"""
Model backends for the load forecaster.

The plan specifies a stacked LSTM (128 then 64 units, dropout 0.2) and names
TensorFlow/Keras in the stack. Keras is a 335 MB install, so it lives in a
separate `[deep]` extra and this module degrades cleanly when it is absent:

* `KerasLstmBackend`   - the specified stacked LSTM.
* `SklearnMlpBackend`  - a multilayer perceptron over the same flattened
                         lookback window, used only when Keras is unavailable.

**The fallback is never silently substituted.** `select_backend` reports which
one it chose and why, the choice is written into the model manifest, and
`metrics.json` records `backend` and `is_fallback` alongside every score. A
figure produced by the MLP must never be read as an LSTM result - the plan's
honesty rule covers the model's identity as much as its numbers.

Both backends see identical inputs and produce identical output shapes, so
`ml/inference.py` and the evaluation code do not branch on which is in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


def keras_available() -> tuple[bool, str]:
    """Whether Keras can be imported, and the reason when it cannot."""
    try:
        import keras  # noqa: F401, PLC0415

        import tensorflow as tf  # noqa: PLC0415

        return True, f"tensorflow {tf.__version__}"
    except Exception as error:  # ImportError, or a DLL/CPU-feature failure
        return False, f"{type(error).__name__}: {str(error)[:200]}"


class Backend(Protocol):
    """What the training and inference code needs from a model backend."""

    name: str
    is_fallback: bool
    description: str

    def build(self, lookback: int, n_features: int) -> None: ...

    def fit(self, x_train, y_train, x_validation, y_validation, config) -> dict: ...

    def predict(self, x) -> np.ndarray: ...

    def save(self, paths) -> str: ...


@dataclass
class KerasLstmBackend:
    """
    The stacked LSTM the plan specifies.

    Two LSTM layers (128 then 64 units) with dropout 0.2 between and after,
    then a single-output dense layer. One step is predicted at a time;
    `inference.py` applies it recursively for the 24-hour horizon.
    """

    name: str = "keras-lstm"
    is_fallback: bool = False
    description: str = "Stacked LSTM (128, 64), dropout 0.2, Keras/TensorFlow"
    model: object | None = None

    def build(self, lookback: int, n_features: int) -> None:
        import keras

        from ml.config import RANDOM_SEED

        keras.utils.set_random_seed(RANDOM_SEED)

        self.model = keras.Sequential(
            [
                keras.layers.Input(shape=(lookback, n_features)),
                # return_sequences so the second LSTM receives a sequence.
                keras.layers.LSTM(128, return_sequences=True),
                keras.layers.Dropout(0.2),
                keras.layers.LSTM(64),
                keras.layers.Dropout(0.2),
                keras.layers.Dense(1),
            ],
            name="ecotrack_lstm_forecast",
        )
        self.model.compile(optimizer="adam", loss="mse", metrics=["mae"])

    def fit(self, x_train, y_train, x_validation, y_validation, config) -> dict:
        import keras

        self.model.optimizer.learning_rate = config.learning_rate
        history = self.model.fit(
            x_train,
            y_train,
            validation_data=(x_validation, y_validation)
            if len(x_validation)
            else None,
            epochs=config.epochs,
            batch_size=config.batch_size,
            shuffle=False,  # a time series must not be shuffled
            verbose=2,
            callbacks=[keras.callbacks.TerminateOnNaN()],
        )
        return {
            "epochs_run": len(history.history.get("loss", [])),
            "final_train_loss": float(history.history["loss"][-1]),
            "final_validation_loss": (
                float(history.history["val_loss"][-1])
                if "val_loss" in history.history
                else None
            ),
        }

    def predict(self, x) -> np.ndarray:
        return self.model.predict(x, verbose=0).reshape(-1)

    def save(self, paths) -> str:
        paths.keras_model.parent.mkdir(parents=True, exist_ok=True)
        self.model.save(paths.keras_model)
        return str(paths.keras_model)


@dataclass
class SklearnMlpBackend:
    """
    Fallback used only when Keras is unavailable.

    An MLP over the flattened lookback window. It is **not** an LSTM: it has no
    recurrence and no memory across the window beyond what flattening exposes.
    Everything it produces is labelled `is_fallback=True` so no score of its is
    ever reported as an LSTM result.
    """

    name: str = "sklearn-mlp"
    is_fallback: bool = True
    description: str = (
        "MLPRegressor (128, 64) over the flattened lookback window. "
        "FALLBACK - not an LSTM; Keras/TensorFlow was unavailable."
    )
    model: object | None = None
    unavailable_reason: str = ""

    def build(self, lookback: int, n_features: int) -> None:
        from sklearn.neural_network import MLPRegressor

        from ml.config import RANDOM_SEED

        self.model = MLPRegressor(
            hidden_layer_sizes=(128, 64),
            activation="relu",
            solver="adam",
            random_state=RANDOM_SEED,
            early_stopping=False,
            max_iter=1,  # driven epoch-by-epoch in fit(), via warm_start
            warm_start=True,
        )

    def fit(self, x_train, y_train, x_validation, y_validation, config) -> dict:
        self.model.set_params(
            learning_rate_init=config.learning_rate, batch_size=min(config.batch_size, len(x_train))
        )
        flat_train = x_train.reshape(len(x_train), -1)

        losses = []
        for epoch in range(config.epochs):
            self.model.fit(flat_train, y_train)
            losses.append(float(self.model.loss_))
            print(f"  epoch {epoch + 1}/{config.epochs}  loss {losses[-1]:.6f}")

        validation_loss = None
        if len(x_validation):
            predicted = self.predict(x_validation)
            validation_loss = float(np.mean((predicted - y_validation) ** 2))

        return {
            "epochs_run": config.epochs,
            "final_train_loss": losses[-1] if losses else None,
            "final_validation_loss": validation_loss,
        }

    def predict(self, x) -> np.ndarray:
        return np.asarray(self.model.predict(x.reshape(len(x), -1))).reshape(-1)

    def save(self, paths) -> str:
        import joblib

        paths.sklearn_model.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, paths.sklearn_model)
        return str(paths.sklearn_model)


def select_backend(prefer_keras: bool = True) -> tuple[Backend, dict]:
    """
    Choose a backend and report the choice.

    Returns the backend and a dict recording what was selected, what was
    available, and why - written into the manifest and into `metrics.json`.
    """
    available, detail = keras_available()

    if prefer_keras and available:
        return KerasLstmBackend(), {
            "backend": "keras-lstm",
            "is_fallback": False,
            "keras_available": True,
            "detail": detail,
            "note": "Stacked LSTM as specified by the project plan.",
        }

    reason = (
        "Keras was not requested." if not prefer_keras else f"Keras unavailable ({detail})."
    )
    return SklearnMlpBackend(unavailable_reason=reason), {
        "backend": "sklearn-mlp",
        "is_fallback": True,
        "keras_available": available,
        "detail": detail,
        "note": (
            f"FALLBACK MODEL. {reason} An MLP over the flattened lookback window "
            f"was trained instead of the specified stacked LSTM. Scores from this "
            f"backend must not be reported as LSTM results. Install with "
            f"`uv sync --extra ml --extra deep` to train the LSTM."
        ),
    }

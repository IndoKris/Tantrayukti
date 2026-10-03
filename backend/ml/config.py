"""
Training configuration.

Two presets. `--small` is the one the phase check runs and the one CI uses: it
trains for about five epochs on a reduced window, which is enough to prove the
pipeline end to end without a GPU. `full` is the same architecture with more
epochs and the whole series.

**Models are trained once with the config given.** The plan forbids re-training
to chase a better score, because a number tuned against the test set is not a
measurement of anything. Whatever these settings produce is what
`metrics.json` reports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = ML_DIR / "data" / "processed"
ARTIFACTS_DIR = ML_DIR / "artifacts"

#: The single file every metric shown in the UI or docs must come from.
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"

#: Seed for every stochastic step, so a run is reproducible.
RANDOM_SEED = 20261003


@dataclass
class LstmConfig:
    """
    Stacked LSTM for 24-hour-ahead load forecasting.

    The architecture is fixed by the plan: 128 units then 64 units, dropout 0.2.
    Only the training budget changes between presets.
    """

    name: str = "small"

    # --- Architecture (fixed by the plan) ---
    units: tuple[int, int] = (128, 64)
    dropout: float = 0.2

    # --- Windowing ---
    #: Hours of history fed to the model.
    lookback_hours: int = 24
    #: Hours predicted. Produced recursively, one step at a time.
    horizon_hours: int = 24

    # --- Training budget ---
    epochs: int = 5
    batch_size: int = 64
    learning_rate: float = 0.001
    #: Cap on rows used, so `--small` stays fast. None means the whole series.
    max_rows: int | None = 4000

    # --- Split (chronological, never random) ---
    train_fraction: float = 0.7
    validation_fraction: float = 0.15

    #: Target column in the processed dataset.
    target: str = "energy_kwh"
    #: Exogenous features appended to the lagged target.
    features: tuple[str, ...] = (
        "hour_sin",
        "hour_cos",
        "month_sin",
        "month_cos",
        "is_weekend",
    )

    def as_dict(self) -> dict:
        return asdict(self)


SMALL = LstmConfig(name="small", epochs=5, max_rows=4000)

FULL = LstmConfig(
    name="full",
    epochs=40,
    max_rows=None,
    batch_size=128,
)

PRESETS: dict[str, LstmConfig] = {"small": SMALL, "full": FULL}


@dataclass
class ArtifactPaths:
    """Where a trained model and its companions live."""

    slug: str
    directory: Path = field(default=ARTIFACTS_DIR)

    @property
    def keras_model(self) -> Path:
        return self.directory / f"{self.slug}.keras"

    @property
    def sklearn_model(self) -> Path:
        return self.directory / f"{self.slug}.joblib"

    @property
    def scaler(self) -> Path:
        return self.directory / f"{self.slug}_scaler.joblib"

    @property
    def manifest(self) -> Path:
        """Describes the trained model: backend, config, feature order, data source."""
        return self.directory / f"{self.slug}_manifest.json"


FORECAST_ARTIFACTS = ArtifactPaths(slug="lstm_forecast")

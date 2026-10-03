"""
Train the 24-hour load forecaster.

    cd backend
    python -m ml.training.train_lstm --small    # the phase check
    python -m ml.training.train_lstm            # full preset

Writes to `ml/artifacts/`:

    lstm_forecast.keras / .joblib    the trained model
    lstm_forecast_scaler.joblib      the scaler, fit on the training split only
    lstm_forecast_manifest.json      backend, config, feature order, data provenance

**Trained once with the given config.** The plan forbids re-training to chase a
better score, so there is no tuning loop here and no early-stopping restore from
a best epoch chosen on the test set. Whatever this run produces is what
`ml/evaluation/evaluate_all.py` reports.

**The data's provenance follows the model.** The manifest records whether the
training data was real or synthetic, read from the Phase 10 sidecar, so
`metrics.json` can state it and the UI can show it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config as ml_config
from ml.training import backends, windows

HOUSEHOLD_FILE = "household_hourly.csv"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ml.training.train_lstm",
        description="Train the stacked-LSTM 24-hour load forecaster.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Use the reduced preset (about 5 epochs), for the phase check and CI.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=ml_config.PROCESSED_DIR / HOUSEHOLD_FILE,
        help="Processed hourly dataset to train on.",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=ml_config.ARTIFACTS_DIR,
        help="Directory for the model, scaler and manifest.",
    )
    parser.add_argument(
        "--no-keras",
        action="store_true",
        help="Force the scikit-learn fallback even if Keras is installed.",
    )
    return parser.parse_args(argv)


def load_provenance(data_path: Path) -> dict:
    """Read the Phase 10 sidecar so the model knows what it was trained on."""
    sidecar = data_path.with_suffix(data_path.suffix + ".provenance.json")
    if not sidecar.exists():
        return {
            "dataset": "unknown",
            "is_synthetic": None,
            "note": (
                f"No provenance sidecar at {sidecar.name}. Run "
                f"`python -m ml.data.prepare --small` first."
            ),
        }
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    return {
        "dataset": payload.get("dataset"),
        "is_synthetic": payload.get("is_synthetic"),
        "source": payload.get("source"),
        "rows": payload.get("rows"),
        "first_timestamp": payload.get("first_timestamp"),
        "last_timestamp": payload.get("last_timestamp"),
    }


def train(argv=None) -> dict:
    """Train and save the model. Returns the manifest."""
    args = parse_args(argv)
    cfg = ml_config.PRESETS["small" if args.small else "full"]

    if not args.data.exists():
        raise SystemExit(
            f"No processed dataset at {args.data}.\n"
            f"Run: python -m ml.data.prepare {'--small' if args.small else ''}"
        )

    frame = pd.read_csv(args.data, index_col="timestamp", parse_dates=True)
    provenance = load_provenance(args.data)

    print(
        f"Training the forecaster | preset '{cfg.name}' | {len(frame)} hourly rows\n"
        f"  data: {provenance.get('dataset')} "
        f"(synthetic={provenance.get('is_synthetic')})"
    )

    dataset = windows.build_dataset(frame, cfg)
    summary = dataset.summary()
    print(
        f"  windows: train {summary['train_windows']}, "
        f"validation {summary['validation_windows']}, test {summary['test_windows']} "
        f"| lookback {cfg.lookback_hours} h | {summary['n_columns']} columns"
    )
    print("  scaler fit on the TRAINING split only (no leakage from validation/test)")

    backend, selection = backends.select_backend(prefer_keras=not args.no_keras)
    print(f"  backend: {backend.name} - {backend.description}")
    if selection["is_fallback"]:
        print(f"  ! {selection['note']}")

    backend.build(cfg.lookback_hours, dataset.n_columns)
    history = backend.fit(
        dataset.x_train,
        dataset.y_train,
        dataset.x_validation,
        dataset.y_validation,
        cfg,
    )
    print(
        f"  trained {history['epochs_run']} epoch(s) | "
        f"train loss {history['final_train_loss']:.6f}"
        + (
            f" | validation loss {history['final_validation_loss']:.6f}"
            if history.get("final_validation_loss") is not None
            else ""
        )
    )

    paths = ml_config.ArtifactPaths(slug="lstm_forecast", directory=args.artifacts)
    model_path = backend.save(paths)

    import joblib

    joblib.dump(dataset.scaler, paths.scaler)

    manifest = {
        "model": "24-hour load forecaster",
        "created_by": "ml/training/train_lstm.py",
        "preset": cfg.name,
        "config": cfg.as_dict(),
        "backend": selection,
        "architecture": backend.description,
        "training": history,
        "dataset": summary,
        "data_provenance": provenance,
        "artifacts": {
            "model": model_path,
            "scaler": str(paths.scaler),
        },
        "scaler": {
            "fit_on": "training split only",
            "note": (
                "Fitting the scaler on the full series would leak the test set's "
                "range into training and inflate every score."
            ),
        },
        "horizon_note": (
            "The model predicts one hour ahead. The 24-hour forecast is produced "
            "recursively by feeding each prediction back as input, so error "
            "compounds across the horizon - see ml/inference.py."
        ),
    }
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(f"  saved {model_path}")
    print(f"  saved {paths.scaler}")
    print(f"  saved {paths.manifest}")

    if provenance.get("is_synthetic"):
        print(
            "\nNOTE: trained on SYNTHETIC data. Every metric derived from this "
            "model must be labelled synthetic."
        )
    if selection["is_fallback"]:
        print(
            "NOTE: trained with the FALLBACK backend, not the specified LSTM. "
            "Scores must not be reported as LSTM results."
        )

    return manifest


def main(argv=None) -> int:
    train(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())

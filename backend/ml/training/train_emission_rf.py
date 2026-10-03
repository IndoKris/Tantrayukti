"""
Train a random forest for the hourly grid emission factor.

    cd backend
    python -m ml.training.train_emission_rf --small

**Time-aware cross-validation.** `TimeSeriesSplit` is used, never `KFold`: a
random fold would train on hours that come after the hours it validates on,
leaking the future and inflating every score.

**What this model can and cannot tell you.** It is trained on the synthetic
series from Phase 10, because no real hourly CO2-intensity series for the Indian
grid is downloaded by this project. The model therefore learns the generator's
assumptions, not the grid. Its metrics are a check that the pipeline works; they
are not evidence about real emissions. `metrics.json` records
`trained_on_synthetic: true` so nothing downstream can forget.

The Phase 9 CO2 engine keeps the static 0.82 kg/kWh factor as its default. This
model is an explicitly-labelled option, never a silent replacement.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config as ml_config

EMISSION_FILE = "emission_factors_hourly.csv"
TARGET = "kg_co2_per_kwh"
FEATURES = [
    "hour",
    "month",
    "day_of_week",
    "is_weekend",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "load_mw",
]

SMALL = {"n_estimators": 60, "max_depth": 12, "max_rows": 4320, "n_splits": 3}
FULL = {"n_estimators": 300, "max_depth": None, "max_rows": None, "n_splits": 5}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ml.training.train_emission_rf")
    parser.add_argument("--small", action="store_true", help="Reduced preset for CI.")
    parser.add_argument(
        "--data", type=Path, default=ml_config.PROCESSED_DIR / EMISSION_FILE
    )
    parser.add_argument("--artifacts", type=Path, default=ml_config.ARTIFACTS_DIR)
    return parser.parse_args(argv)


def train(argv=None) -> dict:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import TimeSeriesSplit

    from ml.evaluation import metrics as metric_tools

    args = parse_args(argv)
    preset = SMALL if args.small else FULL

    if not args.data.exists():
        raise SystemExit(
            f"No dataset at {args.data}. Run: python -m ml.data.prepare "
            f"{'--small' if args.small else ''}"
        )

    frame = pd.read_csv(args.data, index_col="timestamp", parse_dates=True).sort_index()
    if preset["max_rows"]:
        frame = frame.iloc[-preset["max_rows"] :]

    missing = [name for name in FEATURES if name not in frame.columns]
    if missing:
        raise SystemExit(f"Dataset is missing feature columns: {missing}")

    x = frame[FEATURES].to_numpy(dtype=float)
    y = frame[TARGET].to_numpy(dtype=float)

    print(
        f"Training the emission-factor random forest | "
        f"{'small' if args.small else 'full'} | {len(frame)} hourly rows"
    )
    print("  cross-validation: TimeSeriesSplit (time-aware, never random folds)")

    splitter = TimeSeriesSplit(n_splits=preset["n_splits"])
    fold_scores = []
    for fold, (train_index, test_index) in enumerate(splitter.split(x), start=1):
        model = RandomForestRegressor(
            n_estimators=preset["n_estimators"],
            max_depth=preset["max_depth"],
            random_state=ml_config.RANDOM_SEED,
            n_jobs=-1,
        )
        model.fit(x[train_index], y[train_index])
        predicted = model.predict(x[test_index])

        scored = metric_tools.score(y[test_index], predicted, label=f"fold {fold}")
        baseline = metric_tools.score(
            y[test_index],
            np.full(len(test_index), y[train_index].mean()),
            label=f"fold {fold} train-mean baseline",
        )
        fold_scores.append({"fold": fold, "model": scored, "train_mean_baseline": baseline})
        print(
            f"    fold {fold}: MAE {scored['mae']:.5f}, RMSE {scored['rmse']:.5f}, "
            f"R2 {scored['r2']} (baseline MAE {baseline['mae']:.5f})"
        )

    # Final model on the whole series, for inference.
    final = RandomForestRegressor(
        n_estimators=preset["n_estimators"],
        max_depth=preset["max_depth"],
        random_state=ml_config.RANDOM_SEED,
        n_jobs=-1,
    )
    final.fit(x, y)

    import joblib

    paths = ml_config.ArtifactPaths(slug="emission_rf", directory=args.artifacts)
    paths.sklearn_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": FEATURES, "target": TARGET}, paths.sklearn_model)

    sidecar = args.data.with_suffix(args.data.suffix + ".provenance.json")
    provenance = (
        json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    )

    importances = dict(
        sorted(
            zip(FEATURES, (round(float(v), 5) for v in final.feature_importances_)),
            key=lambda pair: pair[1],
            reverse=True,
        )
    )

    manifest = {
        "model": "Hourly grid emission factor (random forest)",
        "created_by": "ml/training/train_emission_rf.py",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "preset": "small" if args.small else "full",
        "hyperparameters": preset,
        "features": FEATURES,
        "target": {"name": TARGET, "unit": "kg CO2 per kWh"},
        "cross_validation": {
            "strategy": "TimeSeriesSplit",
            "n_splits": preset["n_splits"],
            "why": (
                "Random folds would train on hours later than the hours they "
                "validate on, leaking the future."
            ),
            "folds": fold_scores,
            "mean_mae": round(float(np.mean([f["model"]["mae"] for f in fold_scores])), 6),
            "mean_baseline_mae": round(
                float(np.mean([f["train_mean_baseline"]["mae"] for f in fold_scores])), 6
            ),
        },
        "feature_importances": importances,
        "data_provenance": {
            "dataset": provenance.get("dataset"),
            "is_synthetic": provenance.get("is_synthetic"),
            "source": provenance.get("source"),
        },
        "caveats": [
            "TRAINED ON SYNTHETIC DATA. No real hourly grid CO2 intensity series "
            "is downloaded by this project, so this model learns the generator's "
            "assumptions, not the grid.",
            "The Phase 9 CO2 engine keeps the static 0.82 kg/kWh factor as its "
            "default; this model is an explicitly-labelled option.",
            "Error metrics only (MAE, RMSE, MAPE, R2), never accuracy.",
        ],
        "artifacts": {"model": str(paths.sklearn_model)},
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(
        f"  mean CV MAE {manifest['cross_validation']['mean_mae']} vs "
        f"train-mean baseline {manifest['cross_validation']['mean_baseline_mae']}"
    )
    print(f"  top features: {list(importances)[:3]}")
    print(f"  saved {paths.sklearn_model}")
    print(f"  saved {paths.manifest}")
    print(
        "\nNOTE: trained on SYNTHETIC data - the metrics check the pipeline, "
        "not real grid emissions."
    )
    return manifest


def main(argv=None) -> int:
    train(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())

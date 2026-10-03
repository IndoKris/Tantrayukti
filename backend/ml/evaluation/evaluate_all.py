"""
Evaluate every trained model and write `ml/artifacts/metrics.json`.

    cd backend
    python -m ml.evaluation.evaluate_all

`metrics.json` is the **single source** of every metric shown in the UI or the
docs. The plan forbids hard-coding or inventing accuracy figures, so this script
is the only thing that writes it, and it records for each model: the backend
used, whether that backend was a fallback, whether the training data was
synthetic, the error metrics, the naive baselines, and the skill against them.

Phases 12 and 13 append their own sections; this script merges rather than
overwrites, so one model's evaluation never silently deletes another's.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config as ml_config
from ml import inference
from ml.evaluation import metrics as metric_tools
from ml.training import windows
from ml.training.windows import inverse_target

HOUSEHOLD_FILE = "household_hourly.csv"


def load_metrics(path: Path) -> dict:
    """Read the existing metrics file, so other models' sections survive."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  ! {path} was not valid JSON; starting a fresh file.")
    return {}


def write_metrics(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def evaluate_forecast(
    data_path: Path, artifacts: Path
) -> dict:
    """
    Score the forecaster on its held-out test split, against three baselines.

    Both one-step and recursive 24-step horizons are reported: the one-step
    figure is what the model was trained for, and the 24-step figure is what the
    UI actually shows, which is always worse. Reporting only the former would
    overstate what the dashboard delivers.
    """
    model = inference.load_model(artifacts=artifacts)
    cfg_dict = model.manifest["config"]
    cfg = ml_config.LstmConfig(**{**cfg_dict, "units": tuple(cfg_dict["units"]), "features": tuple(cfg_dict["features"])})

    frame = pd.read_csv(data_path, index_col="timestamp", parse_dates=True)
    dataset = windows.build_dataset(frame, cfg)

    if len(dataset.x_test) == 0:
        return {
            "status": "not evaluated",
            "reason": "The test split produced no complete windows.",
        }

    # --- One step ahead ---
    predicted_scaled = model.predict_fn(dataset.x_test)
    predicted = inverse_target(model.scaler, predicted_scaled, dataset.n_columns)
    actual = inverse_target(model.scaler, dataset.y_test, dataset.n_columns)
    predicted = np.clip(predicted, 0.0, None)

    one_step = metric_tools.score(actual, predicted, label="One hour ahead")
    one_step_baselines = metric_tools.baseline_scores(
        actual,
        history=dataset.train_series,
        train_mean=dataset.train_mean,
    )

    # --- Recursive 24 steps, which is what the dashboard shows ---
    recursive = evaluate_recursive(model, frame, cfg)

    return {
        "status": "evaluated",
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": {
            "architecture": model.manifest["architecture"],
            "backend": model.manifest["backend"]["backend"],
            "is_fallback": model.is_fallback,
            "backend_note": model.manifest["backend"]["note"],
            "preset": model.manifest["preset"],
        },
        "data": {
            **model.manifest["data_provenance"],
            "test_windows": int(len(dataset.x_test)),
        },
        "target": {"name": cfg.target, "unit": "kWh per hour"},
        "one_step": {
            "model": one_step,
            "baselines": one_step_baselines,
            "skill_vs_baselines": metric_tools.skill_vs_baselines(
                one_step, one_step_baselines
            ),
        },
        "recursive_24h": recursive,
        "caveats": _caveats(model),
    }


def evaluate_recursive(model, frame: pd.DataFrame, cfg) -> dict:
    """
    Score full 24-hour recursive forecasts over the test period.

    A forecast is issued every 24 hours across the test split and scored against
    what actually happened, which is how the dashboard's overlay is produced.
    """
    frame = frame.sort_index()
    if cfg.max_rows is not None and len(frame) > cfg.max_rows:
        frame = frame.iloc[-cfg.max_rows :]

    total = len(frame)
    test_start = int(total * (cfg.train_fraction + cfg.validation_fraction))
    series = frame[cfg.target].to_numpy(dtype=float)
    index = frame.index

    horizon = cfg.horizon_hours
    lookback = cfg.lookback_hours

    actuals: list[float] = []
    predictions: list[float] = []
    issued = 0

    cursor = max(test_start, lookback)
    while cursor + horizon <= total:
        history = series[cursor - lookback : cursor]
        truth = series[cursor : cursor + horizon]
        result = inference.forecast_from_history(
            model, history, index[cursor - 1], horizon=horizon
        )
        predictions.extend(point["energy_kwh"] for point in result["points"])
        actuals.extend(truth.tolist())
        issued += 1
        cursor += horizon

    if not actuals:
        return {
            "status": "not evaluated",
            "reason": "The test split was shorter than one 24-hour horizon.",
        }

    scored = metric_tools.score(actuals, predictions, label="24 hours ahead, recursive")
    baselines = metric_tools.baseline_scores(
        actuals,
        history=series[:test_start],
        train_mean=float(series[:test_start].mean()),
    )

    return {
        "status": "evaluated",
        "forecasts_issued": issued,
        "horizon_hours": horizon,
        "model": scored,
        "baselines": baselines,
        "skill_vs_baselines": metric_tools.skill_vs_baselines(scored, baselines),
        "note": (
            "This is the horizon the dashboard displays. Error is higher than the "
            "one-step figure because each prediction is fed back as input."
        ),
    }


def _caveats(model) -> list[str]:
    caveats = [
        "All figures are error metrics (MAE, RMSE, MAPE, R2), never accuracy.",
        "MAPE excludes actuals below 0.001 kWh; the excluded row count is reported "
        "alongside it.",
        "The scaler was fit on the training split only.",
        "The split is chronological, never random.",
    ]
    if model.is_fallback:
        caveats.insert(
            0,
            "FALLBACK BACKEND: these are not results for the stacked LSTM the plan "
            "specifies. Keras/TensorFlow was unavailable at training time, so an "
            "MLP over the flattened lookback window was trained instead.",
        )
    if model.manifest["data_provenance"].get("is_synthetic"):
        caveats.insert(0, "Trained on SYNTHETIC data; see the data provenance block.")
    return caveats


def read_manifest_section(slug: str, artifacts: Path, title: str) -> dict:
    """
    Fold a training manifest into metrics.json.

    The Phase 12 models are evaluated during training (time-aware CV for the
    random forest, an OLS prediction interval for the trend), so their metrics
    already live in their manifests. Copying them here keeps metrics.json the
    single place every reported figure comes from, rather than having the UI
    read three different files.
    """
    manifest_path = ml_config.ArtifactPaths(slug=slug, directory=artifacts).manifest
    if not manifest_path.exists():
        return {
            "status": "not evaluated",
            "reason": f"No manifest at {manifest_path.name}. Train the model first.",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"status": "not evaluated", "reason": f"{manifest_path.name}: {error}"}

    return {"status": "evaluated", "title": title, **manifest}


def main(argv=None) -> int:
    artifacts = ml_config.ARTIFACTS_DIR
    data_path = ml_config.PROCESSED_DIR / HOUSEHOLD_FILE
    metrics_path = ml_config.METRICS_PATH

    payload = load_metrics(metrics_path)
    payload.setdefault("schema", 1)
    payload["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload["generated_by"] = "ml/evaluation/evaluate_all.py"
    payload["honesty_note"] = (
        "Every metric shown in the EcoTrack UI or docs comes from this file. "
        "Nothing here is hand-written. Regression results are error metrics, "
        "never accuracy."
    )

    print("Evaluating models")

    try:
        payload["load_forecast"] = evaluate_forecast(data_path, artifacts)
        section = payload["load_forecast"]
        if section["status"] == "evaluated":
            one = section["one_step"]["model"]
            print(
                f"  load_forecast one-step: MAE {one['mae']} kWh, RMSE {one['rmse']}, "
                f"MAPE {one['mape_percent']}%, R2 {one['r2']}"
            )
            skill = section["one_step"]["skill_vs_baselines"]["seasonal_naive"]
            print(
                f"    vs seasonal naive: MAE improvement "
                f"{skill['mae_improvement_percent']}%"
            )
            recursive = section["recursive_24h"]
            if recursive["status"] == "evaluated":
                row = recursive["model"]
                print(
                    f"  load_forecast 24h recursive: MAE {row['mae']} kWh, "
                    f"RMSE {row['rmse']}, MAPE {row['mape_percent']}%, R2 {row['r2']} "
                    f"({recursive['forecasts_issued']} forecasts)"
                )
        else:
            print(f"  load_forecast: {section['status']} - {section.get('reason')}")
    except inference.ModelUnavailable as error:
        payload["load_forecast"] = {"status": "not evaluated", "reason": str(error)}
        print(f"  load_forecast: not evaluated - {error}")
    except FileNotFoundError as error:
        payload["load_forecast"] = {"status": "not evaluated", "reason": str(error)}
        print(f"  load_forecast: not evaluated - {error}")

    # --- Phase 12 models, evaluated at training time ---
    payload["emission_factor_model"] = read_manifest_section(
        "emission_rf", artifacts, "Hourly grid emission factor (random forest)"
    )
    section = payload["emission_factor_model"]
    if section["status"] == "evaluated":
        cv = section["cross_validation"]
        print(
            f"  emission_factor_model: mean CV MAE {cv['mean_mae']} kg CO2/kWh "
            f"vs train-mean baseline {cv['mean_baseline_mae']} "
            f"({cv['strategy']}, {cv['n_splits']} folds)"
        )
    else:
        print(f"  emission_factor_model: {section['status']} - {section.get('reason')}")

    payload["co2_trend"] = read_manifest_section(
        "co2_trend", artifacts, "Linear CO2 trend with prediction interval"
    )
    section = payload["co2_trend"]
    if section["status"] == "evaluated":
        fit = section["fit"]
        print(
            f"  co2_trend: slope {fit['slope_per_day']:+.3g}/day ({fit['direction']}), "
            f"R2 {fit['r2']}, p {fit['p_value']}, "
            f"significant={fit['is_significant']}"
        )
    else:
        print(f"  co2_trend: {section['status']} - {section.get('reason')}")

    payload["nilm"] = read_manifest_section(
        "nilm", artifacts, "NILM step-change detector"
    )
    section = payload["nilm"]
    if section["status"] == "evaluated":
        results = section["results"]
        print(
            f"  nilm: {results['events_matched']} matched event(s) of "
            f"{results['events_detected']} detected; metrics "
            f"{section['metrics']['status']} (no appliance ground truth)"
        )
    else:
        print(f"  nilm: {section['status']} - {section.get('reason')}")

    write_metrics(payload, metrics_path)
    print(f"  wrote {metrics_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

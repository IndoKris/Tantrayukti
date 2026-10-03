"""
Fit a linear CO2 trend with a prediction interval.

    cd backend
    python -m ml.training.train_co2_trend

Ordinary least squares of daily CO2 against time, with a **prediction interval**
rather than a bare line. A trend line without an interval invites reading noise
as a result; the interval states how wide the uncertainty actually is.

The interval is the standard OLS prediction interval:

    y_hat +/- t(1-a/2, n-2) * s * sqrt(1 + 1/n + (x - x_bar)^2 / Sxx)

which widens away from the centre of the data - correctly, since extrapolation
is less certain than interpolation.

The slope's p-value is reported too, so a flat-but-noisy series is not presented
as a trend. If the slope is not significant, `is_significant` is false and the
caveats say the data does not support claiming a direction.
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
DEFAULT_ALPHA = 0.05


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ml.training.train_co2_trend")
    parser.add_argument(
        "--data", type=Path, default=ml_config.PROCESSED_DIR / EMISSION_FILE
    )
    parser.add_argument("--artifacts", type=Path, default=ml_config.ARTIFACTS_DIR)
    parser.add_argument(
        "--horizon-days", type=int, default=30, help="Days to project forward."
    )
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    return parser.parse_args(argv)


def fit_trend(x: np.ndarray, y: np.ndarray, alpha: float = DEFAULT_ALPHA) -> dict:
    """
    Least-squares fit with prediction-interval machinery and a slope p-value.

    Returns the coefficients and everything needed to widen the interval at an
    arbitrary x, so projection does not have to re-derive the statistics.
    """
    from scipy import stats

    n = len(x)
    if n < 3:
        raise ValueError(f"Need at least 3 points to fit a trend with an interval, got {n}.")

    x_mean = float(x.mean())
    sxx = float(((x - x_mean) ** 2).sum())
    if sxx == 0:
        raise ValueError("All x values are identical; a slope is undefined.")

    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = y - fitted

    degrees_of_freedom = n - 2
    residual_std = float(np.sqrt((residuals**2).sum() / degrees_of_freedom))
    slope_std_error = residual_std / np.sqrt(sxx)

    t_statistic = float(slope / slope_std_error) if slope_std_error else 0.0
    p_value = float(2 * (1 - stats.t.cdf(abs(t_statistic), degrees_of_freedom)))
    t_critical = float(stats.t.ppf(1 - alpha / 2, degrees_of_freedom))

    total = float(((y - y.mean()) ** 2).sum())
    r_squared = float(1 - (residuals**2).sum() / total) if total else None

    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "n": n,
        "x_mean": x_mean,
        "sxx": sxx,
        "residual_std": residual_std,
        "slope_std_error": float(slope_std_error),
        "t_statistic": t_statistic,
        "p_value": p_value,
        "t_critical": t_critical,
        "alpha": alpha,
        "r2": r_squared,
        "is_significant": bool(p_value < alpha),
    }


def predict_with_interval(fit: dict, x_new: np.ndarray) -> list[dict]:
    """Point prediction plus the prediction interval at each new x."""
    x_new = np.asarray(x_new, dtype=float)
    centre = fit["slope"] * x_new + fit["intercept"]
    margin = (
        fit["t_critical"]
        * fit["residual_std"]
        * np.sqrt(1 + 1 / fit["n"] + (x_new - fit["x_mean"]) ** 2 / fit["sxx"])
    )
    return [
        {
            "x": float(x),
            "predicted": round(float(value), 6),
            "lower": round(float(value - half), 6),
            "upper": round(float(value + half), 6),
        }
        for x, value, half in zip(x_new, centre, margin)
    ]


def train(argv=None) -> dict:
    args = parse_args(argv)

    if not args.data.exists():
        raise SystemExit(
            f"No dataset at {args.data}. Run: python -m ml.data.prepare --small"
        )

    frame = pd.read_csv(args.data, index_col="timestamp", parse_dates=True).sort_index()

    # Daily mean CO2 intensity; a daily series is what a trend panel shows.
    daily = frame["kg_co2_per_kwh"].resample("1D").mean().dropna()
    if len(daily) < 3:
        raise SystemExit(f"Only {len(daily)} daily points; need at least 3.")

    x = np.arange(len(daily), dtype=float)
    y = daily.to_numpy(dtype=float)

    print(f"Fitting the CO2 trend | {len(daily)} daily points")
    fit = fit_trend(x, y, alpha=args.alpha)

    future_x = np.arange(len(daily), len(daily) + args.horizon_days, dtype=float)
    projection = predict_with_interval(fit, future_x)
    future_dates = pd.date_range(
        start=daily.index[-1] + pd.Timedelta(days=1), periods=args.horizon_days, freq="1D"
    )
    for point, stamp in zip(projection, future_dates):
        point["date"] = stamp.date().isoformat()

    direction = (
        "rising" if fit["slope"] > 0 else "falling" if fit["slope"] < 0 else "flat"
    )

    sidecar = args.data.with_suffix(args.data.suffix + ".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}

    caveats = [
        "Ordinary least squares on daily means. A straight line cannot represent "
        "seasonality; the prediction interval widens with distance from the data.",
        "The interval is a prediction interval (for a new observation), not a "
        "narrower confidence interval for the mean.",
        "TRAINED ON SYNTHETIC DATA - no real grid CO2 series is used here.",
    ]
    if not fit["is_significant"]:
        caveats.insert(
            0,
            f"The slope is NOT statistically significant (p = {fit['p_value']:.4f} "
            f"at alpha = {args.alpha}). The data does not support claiming a "
            f"direction of travel.",
        )

    manifest = {
        "model": "Linear CO2 trend with prediction interval",
        "created_by": "ml/training/train_co2_trend.py",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "unit": "kg CO2 per kWh (daily mean)",
        "fit": {
            "slope_per_day": round(fit["slope"], 9),
            "intercept": round(fit["intercept"], 6),
            "r2": None if fit["r2"] is None else round(fit["r2"], 6),
            "p_value": round(fit["p_value"], 8),
            "is_significant": fit["is_significant"],
            "alpha": args.alpha,
            "n_days": fit["n"],
            "residual_std": round(fit["residual_std"], 6),
            "direction": direction,
        },
        "projection": {
            "horizon_days": args.horizon_days,
            "points": projection,
        },
        "data_provenance": {
            "dataset": provenance.get("dataset"),
            "is_synthetic": provenance.get("is_synthetic"),
        },
        "caveats": caveats,
    }

    paths = ml_config.ArtifactPaths(slug="co2_trend", directory=args.artifacts)
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(
        f"  slope {fit['slope']:+.6g} kg CO2/kWh per day ({direction}), "
        f"R2 {fit['r2']:.4f}, p {fit['p_value']:.4g} "
        f"({'significant' if fit['is_significant'] else 'NOT significant'})"
    )
    first = projection[0]
    print(
        f"  day+1 projection {first['predicted']} "
        f"[{first['lower']}, {first['upper']}] at {int((1 - args.alpha) * 100)}%"
    )
    print(f"  saved {paths.manifest}")
    return manifest


def main(argv=None) -> int:
    train(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())

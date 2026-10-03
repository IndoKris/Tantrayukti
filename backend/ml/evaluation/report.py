"""
Generate `docs/ML_EVALUATION.md` from `ml/artifacts/metrics.json`.

    cd backend
    python -m ml.evaluation.report

The document is **generated, never hand-written**. That is the mechanism behind
the project's honesty rule: if a figure appears in the docs it came out of
`metrics.json`, and if `metrics.json` says a model was not evaluated the
document says so too rather than quietly omitting the section.

Running this with no `metrics.json` writes a document that says no evaluation
has been run, which is more useful than failing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ml import config as ml_config

DOCS_DIR = Path(ml_config.ML_DIR).parent.parent / "docs"
OUTPUT = DOCS_DIR / "ML_EVALUATION.md"


def fmt(value) -> str:
    """Render a metric for a table cell, without inventing precision."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def heading(lines: list[str], payload: dict) -> None:
    lines += [
        "# ML evaluation",
        "",
        "> **This file is generated.** It is written by",
        "> `backend/ml/evaluation/report.py` from",
        "> `backend/ml/artifacts/metrics.json`. Do not edit it by hand — your",
        "> changes will be overwritten, and a hand-edited number would defeat the",
        "> point of the file existing.",
        "",
        f"- Metrics generated: `{payload.get('generated_at', 'unknown')}`",
        f"- By: `{payload.get('generated_by', 'unknown')}`",
        f"- Document generated: `{datetime.now(UTC).isoformat(timespec='seconds')}`",
        "",
        "## The rules these numbers follow",
        "",
        "- **Error metrics, never accuracy.** MAE, RMSE, MAPE and R² measure error.",
        "  A regression result is never reported as an accuracy percentage.",
        "- **Every model is shown against naive baselines.** A MAE means nothing",
        "  without knowing what persistence or a seasonal-naive forecast scores.",
        "- **MAPE excludes near-zero actuals** and reports how many rows it",
        "  dropped, because dividing by a value near zero makes it explode.",
        "- **Synthetic data and fallback models are labelled** wherever they were",
        "  used. A score from a fallback backend is not a score for the specified",
        "  architecture.",
        "- **\"Not evaluated\" is a valid result** and appears as such, rather than",
        "  the section being left out.",
        "",
    ]


def score_table(lines: list[str], title: str, score: dict | None) -> None:
    if not score:
        return
    lines += [
        f"**{title}**",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| MAE | {fmt(score.get('mae'))} |",
        f"| RMSE | {fmt(score.get('rmse'))} |",
        f"| MAPE (%) | {fmt(score.get('mape_percent'))} |",
        f"| R² | {fmt(score.get('r2'))} |",
        f"| Samples | {fmt(score.get('n'))} |",
    ]
    if score.get("mape_rows_excluded"):
        lines.append(
            f"| Rows excluded from MAPE | {fmt(score['mape_rows_excluded'])} |"
        )
    lines.append("")


def caveats(lines: list[str], items) -> None:
    if not items:
        return
    lines += ["**Caveats**", ""]
    lines += [f"- {item}" for item in items]
    lines.append("")


def not_evaluated(lines: list[str], section: dict) -> None:
    lines += [
        f"**Not evaluated.** {section.get('reason', 'No reason recorded.')}",
        "",
    ]


def forecast_section(lines: list[str], section: dict) -> None:
    lines += ["## Load forecast (24 hours ahead)", ""]
    if section.get("status") != "evaluated":
        not_evaluated(lines, section)
        return

    model = section.get("model", {})
    data = section.get("data", {})

    lines += [
        f"- Architecture: {model.get('architecture', 'unknown')}",
        f"- Backend: `{model.get('backend', 'unknown')}`",
        f"- Preset: `{model.get('preset', 'unknown')}`",
        f"- Trained on: {data.get('dataset', 'unknown')} "
        f"(synthetic: {fmt(data.get('is_synthetic'))})",
        f"- Test windows: {fmt(data.get('test_windows'))}",
        "",
    ]

    if model.get("is_fallback"):
        lines += [
            "> **Fallback backend.** These are not results for the stacked LSTM",
            f"> the project plan specifies. {model.get('backend_note', '')}",
            "",
        ]

    one_step = section.get("one_step", {})
    score_table(lines, "One hour ahead", one_step.get("model"))

    baselines = one_step.get("baselines") or {}
    skill = one_step.get("skill_vs_baselines") or {}
    if baselines:
        lines += [
            "**Versus naive baselines (one hour ahead)**",
            "",
            "| Baseline | MAE | RMSE | Model MAE improvement | Beats it on MAE |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, row in baselines.items():
            entry = skill.get(name, {})
            lines.append(
                f"| {name} | {fmt(row.get('mae'))} | {fmt(row.get('rmse'))} | "
                f"{fmt(entry.get('mae_improvement_percent'))}% | "
                f"{fmt(entry.get('beats_baseline_on_mae'))} |"
            )
        lines.append("")

    recursive = section.get("recursive_24h", {})
    if recursive.get("status") == "evaluated":
        lines += [
            "### Recursive 24-hour horizon",
            "",
            "This is the horizon the dashboard actually displays, and it is worse",
            "than the one-step figure because each prediction is fed back as input",
            "and error compounds.",
            "",
            f"- Forecasts issued: {fmt(recursive.get('forecasts_issued'))}",
            "",
        ]
        score_table(lines, "24 hours ahead, recursive", recursive.get("model"))
    elif recursive:
        lines += ["### Recursive 24-hour horizon", ""]
        not_evaluated(lines, recursive)

    caveats(lines, section.get("caveats"))


def emission_section(lines: list[str], section: dict) -> None:
    lines += ["## Grid emission factor (random forest)", ""]
    if section.get("status") != "evaluated":
        not_evaluated(lines, section)
        return

    cv = section.get("cross_validation", {})
    lines += [
        f"- Target: {section.get('target', {}).get('name')} "
        f"({section.get('target', {}).get('unit')})",
        f"- Cross-validation: {cv.get('strategy')}, {fmt(cv.get('n_splits'))} folds",
        f"- Why: {cv.get('why', '')}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Mean CV MAE | {fmt(cv.get('mean_mae'))} |",
        f"| Train-mean baseline MAE | {fmt(cv.get('mean_baseline_mae'))} |",
        "",
    ]

    folds = cv.get("folds") or []
    if folds:
        lines += [
            "**Per fold**",
            "",
            "| Fold | MAE | RMSE | R² | Baseline MAE |",
            "| --- | --- | --- | --- | --- |",
        ]
        for fold in folds:
            model = fold.get("model", {})
            baseline = fold.get("train_mean_baseline", {})
            lines.append(
                f"| {fmt(fold.get('fold'))} | {fmt(model.get('mae'))} | "
                f"{fmt(model.get('rmse'))} | {fmt(model.get('r2'))} | "
                f"{fmt(baseline.get('mae'))} |"
            )
        lines.append("")

    importances = section.get("feature_importances") or {}
    if importances:
        lines += ["**Feature importances**", "", "| Feature | Importance |", "| --- | --- |"]
        lines += [f"| {name} | {fmt(value)} |" for name, value in importances.items()]
        lines.append("")

    caveats(lines, section.get("caveats"))


def trend_section(lines: list[str], section: dict) -> None:
    lines += ["## CO₂ trend (linear, with prediction interval)", ""]
    if section.get("status") != "evaluated":
        not_evaluated(lines, section)
        return

    fit = section.get("fit", {})
    lines += [
        f"- Unit: {section.get('unit')}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Slope per day | {fmt(fit.get('slope_per_day'))} |",
        f"| Direction | {fmt(fit.get('direction'))} |",
        f"| R² | {fmt(fit.get('r2'))} |",
        f"| p-value | {fmt(fit.get('p_value'))} |",
        f"| Statistically significant (α = {fmt(fit.get('alpha'))}) | "
        f"{fmt(fit.get('is_significant'))} |",
        f"| Days fitted | {fmt(fit.get('n_days'))} |",
        f"| Residual std | {fmt(fit.get('residual_std'))} |",
        "",
    ]

    points = (section.get("projection") or {}).get("points") or []
    if points:
        first = points[0]
        lines += [
            f"First projected day: **{fmt(first.get('predicted'))}** "
            f"[{fmt(first.get('lower'))}, {fmt(first.get('upper'))}] — a prediction",
            "interval for a new observation, which widens with distance from the data.",
            "",
        ]

    caveats(lines, section.get("caveats"))


def anomaly_section(lines: list[str], section: dict) -> None:
    lines += ["## Anomaly detection", ""]
    if section.get("status") != "evaluated":
        not_evaluated(lines, section)
        return

    lines += [
        f"- Evaluated by: `{section.get('evaluated_by')}`",
        f"- Data: {section.get('data')}",
        f"- Labels: {section.get('labels')}",
        f"- Detectors: {', '.join(section.get('detectors', []))}",
        "",
        "| Scenario | Precision | Recall | F1 | TP | FP | FN | Faulty hours |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in (section.get("scenarios") or {}).items():
        lines.append(
            f"| {name} | {fmt(row.get('precision'))} | {fmt(row.get('recall'))} | "
            f"{fmt(row.get('f1'))} | {fmt(row.get('true_positives'))} | "
            f"{fmt(row.get('false_positives'))} | {fmt(row.get('false_negatives'))} | "
            f"{fmt(row.get('faulty_hours'))} |"
        )
    lines.append("")

    caveats(lines, section.get("caveats"))


def nilm_section(lines: list[str], section: dict) -> None:
    lines += ["## NILM (appliance disaggregation)", ""]
    if section.get("status") != "evaluated":
        not_evaluated(lines, section)
        return

    metrics = section.get("metrics", {})
    results = section.get("results", {})

    lines += [
        f"- Approach: {section.get('approach')}",
        "",
        f"> **Metrics: {metrics.get('status', 'unknown')}.** "
        f"{metrics.get('reason', '')}",
        "",
        "**What the detector found** (descriptive, not an accuracy measure)",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        f"| Samples | {fmt(results.get('samples'))} |",
        f"| Events detected | {fmt(results.get('events_detected'))} |",
        f"| Events matched to a fall | {fmt(results.get('events_matched'))} |",
        f"| Events left open | {fmt(results.get('events_unmatched'))} |",
        f"| Total metered energy (kWh) | {fmt(results.get('total_energy_kwh'))} |",
        f"| Energy attributed to events (kWh) | "
        f"{fmt(results.get('energy_explained_by_events_kwh'))} |",
        f"| Share attributed | {fmt(results.get('share_explained'))} |",
        "",
    ]

    caveats(lines, section.get("caveats"))


SECTIONS = (
    ("load_forecast", forecast_section),
    ("emission_factor_model", emission_section),
    ("co2_trend", trend_section),
    ("anomaly_detection", anomaly_section),
    ("nilm", nilm_section),
)


def build(payload: dict) -> str:
    lines: list[str] = []
    heading(lines, payload)

    for key, renderer in SECTIONS:
        section = payload.get(key)
        if isinstance(section, dict):
            renderer(lines, section)

    note = payload.get("honesty_note")
    if note:
        lines += ["---", "", f"_{note}_", ""]

    lines += [
        "## Reproducing these numbers",
        "",
        "```bash",
        "cd backend",
        "python -m ml.data.prepare --small",
        "python -m ml.training.train_lstm --small",
        "python -m ml.training.train_emission_rf --small",
        "python -m ml.training.train_co2_trend",
        "python -m ml.training.train_nilm --small",
        "python -m ml.evaluation.evaluate_all",
        "python manage.py test insights.tests.test_anomaly   # writes the anomaly section",
        "python -m ml.evaluation.report                      # regenerates this file",
        "```",
        "",
        "Every step is seeded, so the figures are reproducible. Models are trained",
        "**once** with the given config: the project plan forbids re-training to",
        "chase a better score, because a number tuned against the test set is not",
        "a measurement of anything.",
        "",
    ]

    return "\n".join(lines)


def main(argv=None) -> int:
    path = ml_config.METRICS_PATH

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            payload = {
                "generated_at": "unreadable",
                "generated_by": f"{path.name} is not valid JSON: {error}",
            }
    else:
        payload = {
            "generated_at": "never",
            "generated_by": "no evaluation has been run",
            "load_forecast": {
                "status": "not evaluated",
                "reason": (
                    f"No {path.name} exists. Run the commands under "
                    f"'Reproducing these numbers' below."
                ),
            },
        }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build(payload), encoding="utf-8")

    print(f"Wrote {OUTPUT} from {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

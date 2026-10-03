# ML evaluation

> **This file is generated.** It is written by
> `backend/ml/evaluation/report.py` from
> `backend/ml/artifacts/metrics.json`. Do not edit it by hand — your
> changes will be overwritten, and a hand-edited number would defeat the
> point of the file existing.

- Metrics generated: `2026-10-03T11:18:11+00:00`
- By: `ml/evaluation/evaluate_all.py`
- Document generated: `2026-10-03T11:24:04+00:00`

## The rules these numbers follow

- **Error metrics, never accuracy.** MAE, RMSE, MAPE and R² measure error.
  A regression result is never reported as an accuracy percentage.
- **Every model is shown against naive baselines.** A MAE means nothing
  without knowing what persistence or a seasonal-naive forecast scores.
- **MAPE excludes near-zero actuals** and reports how many rows it
  dropped, because dividing by a value near zero makes it explode.
- **Synthetic data and fallback models are labelled** wherever they were
  used. A score from a fallback backend is not a score for the specified
  architecture.
- **"Not evaluated" is a valid result** and appears as such, rather than
  the section being left out.

## Load forecast (24 hours ahead)

- Architecture: MLPRegressor (128, 64) over the flattened lookback window. FALLBACK - not an LSTM; Keras/TensorFlow was unavailable.
- Backend: `sklearn-mlp`
- Preset: `small`
- Trained on: UCI Individual household electric power consumption (synthetic: no)
- Test windows: 277

> **Fallback backend.** These are not results for the stacked LSTM
> the project plan specifies. FALLBACK MODEL. Keras unavailable (ModuleNotFoundError: No module named 'keras'). An MLP over the flattened lookback window was trained instead of the specified stacked LSTM. Scores from this backend must not be reported as LSTM results. Install with `uv sync --extra ml --extra deep` to train the LSTM.

**One hour ahead**

| Metric | Value |
| --- | --- |
| MAE | 0.765185 |
| RMSE | 1.04146 |
| MAPE (%) | 158.786 |
| R² | -0.043574 |
| Samples | 277 |

**Versus naive baselines (one hour ahead)**

| Baseline | MAE | RMSE | Model MAE improvement | Beats it on MAE |
| --- | --- | --- | --- | --- |
| persistence | 0.596311 | 1.17857 | -28.32% | no |
| seasonal_naive | 0.91114 | 1.19652 | 16.019% | yes |
| train_mean | 1.17261 | 1.28731 | 34.745% | yes |

### Recursive 24-hour horizon

This is the horizon the dashboard actually displays, and it is worse
than the one-step figure because each prediction is fed back as input
and error compounds.

- Forecasts issued: 12

**24 hours ahead, recursive**

| Metric | Value |
| --- | --- |
| MAE | 0.964256 |
| RMSE | 1.25034 |
| MAPE (%) | 214.725 |
| R² | -0.539707 |
| Samples | 288 |

**Caveats**

- FALLBACK BACKEND: these are not results for the stacked LSTM the plan specifies. Keras/TensorFlow was unavailable at training time, so an MLP over the flattened lookback window was trained instead.
- All figures are error metrics (MAE, RMSE, MAPE, R2), never accuracy.
- MAPE excludes actuals below 0.001 kWh; the excluded row count is reported alongside it.
- The scaler was fit on the training split only.
- The split is chronological, never random.

## Grid emission factor (random forest)

- Target: kg_co2_per_kwh (kg CO2 per kWh)
- Cross-validation: TimeSeriesSplit, 3 folds
- Why: Random folds would train on hours later than the hours they validate on, leaking the future.

| Metric | Value |
| --- | --- |
| Mean CV MAE | 0.019082 |
| Train-mean baseline MAE | 0.117765 |

**Per fold**

| Fold | MAE | RMSE | R² | Baseline MAE |
| --- | --- | --- | --- | --- |
| 1 | 0.015077 | 0.018889 | 0.981898 | 0.118659 |
| 2 | 0.017868 | 0.021772 | 0.97495 | 0.118081 |
| 3 | 0.024301 | 0.0289 | 0.955627 | 0.116556 |

**Feature importances**

| Feature | Importance |
| --- | --- |
| hour_cos | 0.89771 |
| hour | 0.05114 |
| load_mw | 0.02469 |
| hour_sin | 0.01299 |
| month_cos | 0.00577 |
| month | 0.0054 |
| day_of_week | 0.00136 |
| month_sin | 0.00066 |
| is_weekend | 0.00028 |

**Caveats**

- TRAINED ON SYNTHETIC DATA. No real hourly grid CO2 intensity series is downloaded by this project, so this model learns the generator's assumptions, not the grid.
- The Phase 9 CO2 engine keeps the static 0.82 kg/kWh factor as its default; this model is an explicitly-labelled option.
- Error metrics only (MAE, RMSE, MAPE, R2), never accuracy.

## CO₂ trend (linear, with prediction interval)

- Unit: kg CO2 per kWh (daily mean)

| Metric | Value |
| --- | --- |
| Slope per day | -0.000315399 |
| Direction | falling |
| R² | 0.661225 |
| p-value | 0 |
| Statistically significant (α = 0.05) | yes |
| Days fitted | 180 |
| Residual std | 0.011796 |

First projected day: **0.802433** [0.778895, 0.825971] — a prediction
interval for a new observation, which widens with distance from the data.

**Caveats**

- Ordinary least squares on daily means. A straight line cannot represent seasonality; the prediction interval widens with distance from the data.
- The interval is a prediction interval (for a new observation), not a narrower confidence interval for the mean.
- TRAINED ON SYNTHETIC DATA - no real grid CO2 series is used here.

## Anomaly detection

- Evaluated by: `insights/tests/test_anomaly.py::SimulatorFaultEvaluationTests`
- Data: Phase 7 simulator, office site, 14 days hourly, seed 99
- Labels: Per-sample fault labels emitted by the simulator, so these are real labels rather than a self-assessment.
- Detectors: isolation_forest, seasonal_zscore, rule_night_load, rule_baseload_jump, rule_device_left_on

| Scenario | Precision | Recall | F1 | TP | FP | FN | Faulty hours |
| --- | --- | --- | --- | --- | --- | --- | --- |
| night_load | 1 | 1 | 1 | 20 | 0 | 0 | 20 |
| baseload_jump | 0.9836 | 0.4478 | 0.6154 | 60 | 1 | 74 | 134 |
| ac_left_on | 0.9844 | 0.7412 | 0.8456 | 63 | 1 | 22 | 85 |
| all_faults | 0.9836 | 0.4478 | 0.6154 | 60 | 1 | 74 | 134 |

**Caveats**

- Scored on SYNTHETIC simulator data, not on real faults.
- An anomaly is counted as a hit only when its hour matches a faulty hour exactly; a detector that flags the hour after a fault starts is counted as a miss, so recall is conservative.
- The baseload-jump detector reports one finding for a multi-day condition by design, so its recall per faulty hour is low while its precision is high.

## NILM (appliance disaggregation)

- Approach: Sustained step-change detection on the aggregate power series, with rises matched to later falls of comparable magnitude.

> **Metrics: not evaluated.** NILM accuracy requires per-appliance ground truth. UK-DALE is not downloaded by this project, so there are no appliance labels to score against and no precision, recall or F1 can be computed. Scoring the detector against its own output would measure nothing.

**What the detector found** (descriptive, not an accuracy measure)

| Quantity | Value |
| --- | --- |
| Samples | 1440 |
| Events detected | 393 |
| Events matched to a fall | 364 |
| Events left open | 29 |
| Total metered energy (kWh) | 2023.09 |
| Energy attributed to events (kWh) | 2317.6 |
| Share attributed | 1.1456 |

**Caveats**

- This is the step-change fallback the project plan specifies for an unavailable UK-DALE dataset, not a trained disaggregator.
- Events are inferred, not labelled: the detector cannot say which appliance caused a step, only that a step of that magnitude occurred.
- A CNN+LSTM trainer is deliberately omitted: with no labels its output could not be checked, which is worse than not having it.
- Hourly data limits resolution - appliances cycling within an hour are invisible. Sub-minute data would detect far more.

---

_Every metric shown in the EcoTrack UI or docs comes from this file. Nothing here is hand-written. Regression results are error metrics, never accuracy._

## Reproducing these numbers

```bash
cd backend
python -m ml.data.prepare --small
python -m ml.training.train_lstm --small
python -m ml.training.train_emission_rf --small
python -m ml.training.train_co2_trend
python -m ml.training.train_nilm --small
python -m ml.evaluation.evaluate_all
python manage.py test insights.tests.test_anomaly   # writes the anomaly section
python -m ml.evaluation.report                      # regenerates this file
```

Every step is seeded, so the figures are reproducible. Models are trained
**once** with the given config: the project plan forbids re-training to
chase a better score, because a number tuned against the test set is not
a measurement of anything.

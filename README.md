# Tantrayukti Team 100X
YCCE-26 Nagpur~

## EcoTrack

An energy, cost and CO₂ monitoring dashboard. It records energy use, estimates
cost and CO₂, compares usage across spaces and time periods, **detects abnormal
usage automatically, explains the likely cause, and recommends specific actions
with estimated savings** in kWh, rupees and kg CO₂.

React 19 + Vite + Tailwind v4 + Recharts + Leaflet · Django 5.2 + DRF + JWT ·
PostgreSQL with SQLite fallback · scikit-learn (TensorFlow optional) · ESP32
firmware · n8n workflow · Docker Compose · GitHub Actions.

---

## Quick start

### With Docker

```bash
docker compose up --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py seed_spaces
docker compose exec backend python manage.py seed_tariffs
```

→ **http://localhost:8080**

### Locally

```bash
# Backend
cd backend
uv sync --extra ml                 # add --extra deep for the real LSTM
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_spaces
uv run python manage.py seed_tariffs
uv run python manage.py seed_activity_factors
uv run python manage.py seed_gamification
uv run python manage.py seed_no2
uv run python manage.py runserver
```

```bash
# Telemetry — no hardware needed
python simulator/run.py --days 7 --post --register --username <you> --password <pw>
```

```bash
# ML pipeline
cd backend
uv run python -m ml.data.prepare --small
uv run python -m ml.training.train_lstm --small
uv run python -m ml.training.train_emission_rf --small
uv run python -m ml.training.train_co2_trend
uv run python -m ml.training.train_nilm --small
uv run python -m ml.evaluation.evaluate_all
uv run python -m ml.evaluation.report
```

```bash
# Frontend
cd frontend && npm install && npm run dev
```

→ **http://localhost:5173** — use `localhost`, not `127.0.0.1`: Vite binds
IPv6-only on some Windows setups.

Then follow **[docs/DEMO.md](docs/DEMO.md)**.

---

## What it does

| Area | Capability |
| --- | --- |
| **Record** | Device-token ingestion, batch upload, idempotent offline backfill, digital-twin device status |
| **Cost** | Cumulative slab tariffs, time-of-day surcharge/rebate, fixed charge, tax — with per-line formulas |
| **CO₂** | `kWh × factor`, the factor's provenance returned every time, optional hourly modelled factor |
| **Compare** | Space vs space normalised per m² and per person; period vs period with pro-rating |
| **Detect** | Isolation Forest + robust seasonal z-score + three rules, with severity and a lifecycle |
| **Explain** | Rule-ranked causes with the evidence behind each |
| **Recommend** | Four actions costing kWh / ₹ / kg CO₂ per month, with the formula, assumptions and payback |
| **Forecast** | 24-hour recursive load forecast, scored against three naive baselines |
| **Verify** | Proof of saving: a claimed reduction checked against the meter |
| **Log** | Five activity categories, auditable CSV export, budget vs usage |
| **Play** | XP, levels, streaks, EcoCoins, badges, challenges, leaderboard |
| **Community** | Leaflet map with city-level rounding, 20-city NO₂, validated hotspots, CO₂ trend |
| **Ingest** | Chat ingestion behind an extractor interface, plus an n8n workflow |
| **Hardware** | ESP32 true-power meter with a flash ring buffer |

---

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/DEMO.md](docs/DEMO.md) | 12-minute demo script, with the fault-to-recommendation chain |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Apps, data flow, and the decisions behind them |
| [docs/API.md](docs/API.md) | Every endpoint, auth scheme and unit convention |
| [docs/ML_EVALUATION.md](docs/ML_EVALUATION.md) | **Generated** from `metrics.json` — never hand-written |
| [PROGRESS.md](PROGRESS.md) | Status of all 25 build phases |
| [AUDIT.md](AUDIT.md) | Pre-existing repo state, every conflict, and how it was resolved |
| [BACKLOG.md](BACKLOG.md) | Deferred work, with the reason |
| [simulator/README.md](simulator/README.md) | Load generator and fault injection |
| [firmware/README.md](firmware/README.md) | Wiring, calibration and the safety warning |
| [automation/README.md](automation/README.md) | n8n workflow setup |
| [backend/ml/data/README.md](backend/ml/data/README.md) | Dataset provenance and the kW/kWh trap |

---

## Limitations — read this before quoting any number

This project treats honesty as a feature. Nothing below is hidden in a footnote.

### Models

- **The LSTM is not what is running.** TensorFlow would not download in this
  environment (DNS failure on a 335 MB wheel), so the active forecaster is a
  labelled scikit-learn MLP fallback. `is_fallback` travels from the model
  manifest through `metrics.json` to the API and the UI. Install with
  `uv sync --extra ml --extra deep` and re-run training — no code changes.
- **The forecast is poor.** MAE 0.765 kWh, MAPE 158.8%, **R² −0.044**. It beats
  the seasonal-naive baseline on MAE by 16% but is worse than predicting the test
  mean on R². It was **not tuned**, because the plan forbids re-training to chase
  a score.
- **The emission-factor model learned a generator, not a grid.** No public hourly
  CO₂-intensity series for India is downloaded, so it trains on synthetic data.
  Its good CV score (MAE 0.019 vs 0.118 baseline) validates the pipeline, not the
  grid.
- **NILM is unscored.** No UK-DALE labels exist here, so metrics are
  `"not evaluated"`. It also over-attributes — 114.6% of metered energy in the
  last run — which the manifest states explicitly.

### Data

- **Tariffs are illustrative.** `is_sample=true`, with a source beginning
  "ILLUSTRATIVE SAMPLE RATES — not an actual utility tariff."
- **The CO₂ factor is a static default.** 0.82 kg/kWh, `is_verified=false`, with
  a note pointing at the CEA CO₂ Baseline Database.
- **NO₂ is a static fallback**, `is_measured=false` on every row. No Earth Engine
  credentials.
- **Activity factors are unverified estimates**, all 23 of them, flagged as such.
- **The training data is one French household** (UCI dataset 235). Its load shape
  is not representative of an Indian home or office.

### Units and interpretation

- **NO₂ is a tropospheric column** in µmol/m², **not** a surface concentration.
  No ppb conversion exists in the codebase, and a test enforces that no response
  field implies one.
- **`energy_wh` is interval energy**, never a cumulative meter total.
- **Savings are estimates with stated assumptions**, not guarantees. Proof of
  saving on the Profile page is the only figure checked against a meter.

### Security

- **Device tokens prove possession of a secret, not payload integrity.** The
  token is stored hashed and compared in constant time, but nothing signs the
  reading, so it is not proof the values came from that hardware. Stated in
  `backend/telemetry/authentication.py` and on the BACKLOG.
- **Logout is client-side.** The access token stays valid until it expires;
  server-side revocation needs simplejwt's blacklist app.
- **Refresh tokens live in `localStorage`**, readable by any script on the
  origin. An httpOnly cookie is the hardening step.
- **The ESP32 posts over plain HTTP by default**, sending its token in clear
  text. Use HTTPS beyond a trusted LAN.

### Not implemented

- No frontend tests — the UI is verified by lint, `tsc` and build only.
- No PDF export (CSV only).
- `pio run` has not been executed: PlatformIO is absent here, so the firmware is
  committed unbuilt.
- Roles are global, not per organisation.

---

## Tests

```bash
cd backend && uv run python manage.py test     # 597 tests
cd frontend && npm run lint && npm run build
python simulator/run.py --days 7 --dry-run
docker compose config --quiet
```

CI runs all of it plus the full ML pipeline on every push
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

---

## Repository layout

```
backend/        Django: accounts, spaces, telemetry, billing, insights,
                activity, gamification, satellite, ml/
frontend/       React 19 + Vite + Tailwind v4
simulator/      Stdlib-only load generator with fault injection
firmware/       ESP32 PlatformIO project
automation/     n8n workflow + setup guide
docs/           Architecture, API, ML evaluation, demo script
```

# EcoTrack: Phased Build Instructions for Claude Code

You are building **EcoTrack** (energy, cost and CO2 monitoring platform) from an empty repo, in **25 phases**. The user commits manually after each phase.

## HOW TO RUN (read first, obey always)

1. **One phase per run.** When the user says `Phase N` or `next`, do ONLY that phase. Then STOP. Never start the next phase on your own.
2. At the start of a run read only: this file, `PROGRESS.md`, and the files listed under that phase's **Touch**. Do not re-scan the whole repo.
3. Build only the phase's **Deliverables**. Ideas that belong elsewhere go in `BACKLOG.md` (one line each). No scope creep, no refactoring earlier phases.
4. Run the phase's **Check** command. If it fails: fix and re-run, **maximum 2 fix attempts**. If it still fails, STOP, mark the phase `BLOCKED` in `PROGRESS.md` with the exact error, and report. Do not keep retrying.
5. Try each network download or install **once**. If it fails, use the fallback in "Fallbacks" and continue. Never wait in retry loops.
6. Train models once with the small config given. Never re-train to chase a better score.
7. Do **not** run `git commit`, `git push` or `git add`. You may run `git status` and `git diff --stat`.
8. Keep each phase to about 15 files or fewer. If it grows, deliver the core and move the rest to `BACKLOG.md`.
9. Never delete or rename anything created in an earlier phase except to fix a bug (note it in the handoff).
10. When done, update `PROGRESS.md` (status `DONE`, one-line summary), then print the **Handoff block** below and stop.

### Handoff block (print exactly this shape)
```
PHASE N DONE: <title>
Files: <created/changed, short list>
Check: <command> -> <PASS/FAIL + one line>
Commit: git add -A && git commit -m "<message from the phase>"
Next: Phase N+1 <title>  (say "next" to continue)
Issues: <none or short list>
```

## TARGET REPO (existing, not empty)

You are working **inside the existing repository `IndoKris/Tantrayukti`** (README title "Tantrayukti Team 100X", YCCE-26 Nagpur). It already has `backend/`, `frontend/`, `README.md` and `.gitattributes`, with prior commits. Rules:

- **Adapt this plan to the repo, never overwrite it.** Read a file before changing it. Add new files and extend existing ones. Do not delete, rename or recreate existing code.
- If existing code conflicts with this plan, **keep the existing code** unless it contradicts the Mission, and record the conflict in `AUDIT.md`.
- Keep the existing README title lines; add to the README, do not replace it.
- If `backend/` or `frontend/` uses a **different framework** than this plan (for example Node/Express or FastAPI instead of Django, or a non-React frontend), **STOP and ask the user** which to keep before continuing. Do not guess.
- Stay on the current branch. Do not create, switch or delete branches.

## MISSION (highest authority)

A dashboard that records energy use, estimates **cost** and **CO2**, **compares usage** across spaces and time periods, **detects abnormal usage automatically**, **explains the likely cause**, and **suggests specific actions with estimated savings** (kWh, rupees, kg CO2). The last four must work end to end in the demo.

**Precedence when instructions conflict:** 1) Mission, 2) working tested code, including what already exists in the repo (never leave a broken build), 3) existing repo conventions, 4) the phase list below, 5) reference repo layout if `reference/` exists, 6) style.

**Honesty rule:** never hard-code or invent accuracy numbers. Every metric shown in the UI or docs comes from `backend/ml/artifacts/metrics.json`, produced by the evaluation code.

## STACK AND LAYOUT

React 18 + Vite + Tailwind + Recharts + Framer Motion + Leaflet | Django + DRF + JWT | PostgreSQL via `DATABASE_URL`, **SQLite fallback** | scikit-learn, TensorFlow/Keras, pandas, joblib | n8n workflow JSON | ESP32 firmware (PlatformIO) | Docker Compose, GitHub Actions.

```
backend/{config,accounts,spaces,telemetry,billing,insights,activity,gamification,satellite,ml/{data,training,evaluation,artifacts}}
frontend/src/{pages,components,api,hooks}   simulator/   firmware/   automation/   docs/   .github/workflows/
```

## FALLBACKS (use instead of stopping)

No Postgres: SQLite. No GPU: small LSTM, few epochs. UCI data unavailable: synthetic generator, label results "synthetic". UK-DALE unavailable: NILM step-change fallback, metrics "not evaluated". No Gemini/Whisper keys: mock extractors behind the same interface, flagged in the UI. No Earth Engine: static city NO2 CSV, stated in the UI. No hardware: simulator posts to the same endpoint.

## KNOWN PROBLEMS IN THE REFERENCE PROJECT (do not copy)

- No Isolation Forest `contamination` that forces a fixed count of anomalies. Use a validated score threshold.
- Report MAE, RMSE, MAPE, R2 vs a naive baseline. Never call regression results "accuracy".
- Never mix kW and kWh. Label units everywhere.
- Satellite NO2 is a column (mol/m2), not surface ppb. Show column units or document the conversion.
- Default emission factor 0.82 kg/kWh is static: show its source in the UI, offer the dynamic RF factor as an option.
- Do not claim "cryptographic" verification unless implemented (use signed device tokens plus server-side comparison).

---

## THE 25 PHASES

### Part A: Foundation

**Phase 1: Audit existing repo and add tracking**
- Touch: root, and read-only inspection of `backend/` and `frontend/`.
- Deliverables: `AUDIT.md` (frameworks and versions found in `backend/` and `frontend/`, entry points, how to run each, existing features and routes, what is reusable, conflicts with this plan, open questions); `PROGRESS.md` (table of all 25 phases, status `TODO`, Phase 1 `DONE`); `BACKLOG.md`; `.gitignore` created only if missing, otherwise appended with missing entries; extra folders from the layout created only where absent, with `.gitkeep`; README gets a short "Project plan" section added below the existing text.
- Check: `AUDIT.md` exists, `PROGRESS.md` lists 25 rows, `git status` shows no deleted files and no modified existing files other than `README.md` and `.gitignore`.
- Commit: `chore: audit existing repo and add progress tracking`

**Phase 2: Backend skeleton**
- Touch: `backend/`.
- Deliverables: if `backend/` already contains a working Django/DRF project, **extend it** (add the health endpoint, env-based settings with SQLite fallback, CORS, `requirements.txt` and `.env.example` only where missing). Otherwise create the Django project `config`, DRF, CORS, env-based settings with SQLite fallback, `requirements.txt`, `.env.example`, `GET /api/health/`.
- Check: `cd backend && python manage.py check && python manage.py test`
- Commit: `feat(backend): django and drf skeleton with health endpoint`

**Phase 3: Frontend skeleton**
- Touch: `frontend/`.
- Deliverables: if `frontend/` already contains a working React app, **extend it** (add missing router pages, layout shell and API client without replacing existing pages). Otherwise create a Vite React app, Tailwind, router with placeholder pages (Dashboard, Spaces, Insights, Reports, Community, Profile), layout shell, API client with base URL env.
- Check: `cd frontend && npm install && npm run build`
- Commit: `feat(frontend): vite react shell with routing and tailwind`

**Phase 4: Auth and roles**
- Touch: `backend/accounts`, `frontend/src/api`, login page.
- Deliverables: custom user with roles (admin, manager, member), JWT login/refresh, protected-route helper, login page, tests.
- Check: `python manage.py test accounts`
- Commit: `feat(accounts): jwt auth and roles`

**Phase 5: Spaces hierarchy**
- Touch: `backend/spaces`.
- Deliverables: Organisation > Building > Floor > Room models with area and occupancy, CRUD API scoped by user, seed command with a sample office and a sample home, tests.
- Check: `python manage.py test spaces && python manage.py seed_spaces`
- Commit: `feat(spaces): hierarchy models, api and seed data`

### Part B: Data pipeline

**Phase 6: Telemetry ingestion**
- Touch: `backend/telemetry`.
- Deliverables: Device and Reading models (voltage, current, power factor, active power W, energy Wh, timestamp), device token auth, `POST /api/readings/` (single and batch, validation, chronological backfill), device status ("digital twin": last seen, online/offline, buffered count), tests.
- Check: `python manage.py test telemetry`
- Commit: `feat(telemetry): reading ingestion, backfill and device status`

**Phase 7: Simulator**
- Touch: `simulator/`.
- Deliverables: script that generates realistic load for a home and an office (fridge, AC, lights, washer, standby) and posts to the API or writes a CSV; option `--fault` to inject AC-left-on, night load, baseload jump; fixed random seed.
- Check: `python simulator/run.py --days 7 --dry-run` prints counts per appliance.
- Commit: `feat(simulator): appliance load generator with fault injection`

**Phase 8: Rollups API**
- Touch: `backend/telemetry`.
- Deliverables: hourly/daily/monthly aggregation by device and space, `GET /api/usage/?space=&period=&from=&to=`, tests with simulator data.
- Check: `python manage.py test telemetry.tests.test_rollups`
- Commit: `feat(telemetry): usage rollups by space and period`

**Phase 9: Cost and CO2 engines**
- Touch: `backend/billing`.
- Deliverables: tariff models (slab, time-of-day, fixed charge) with seed values clearly marked sample, bill estimate and month projection endpoint, CO2 engine (`kWh x factor`, default 0.82 kg/kWh, factor source returned in every response), unit tests for slabs and ToU.
- Check: `python manage.py test billing`
- Commit: `feat(billing): tariff cost and co2 engines`

### Part C: Machine learning

**Phase 10: ML data and synthetic generator**
- Touch: `backend/ml/data`.
- Deliverables: loader for UCI household power data (one download attempt, else fallback), cleaning and hourly resampling, synthetic generator for grid emission factor training rows (labelled synthetic), data README stating provenance.
- Check: `python -m ml.data.prepare --small` writes a processed sample file.
- Commit: `feat(ml): data loaders, cleaning and synthetic generator`

**Phase 11: LSTM forecasting**
- Touch: `backend/ml/training`, `ml/evaluation`, `ml/inference.py`, `insights`.
- Deliverables: stacked LSTM (128 then 64 units, dropout 0.2), time-ordered split, scaler fit on train only, small config (about 5 epochs), recursive 24-step inference from the last 24 h, naive baselines, MAE/RMSE/MAPE/R2 written to `metrics.json`, `GET /api/forecast/<device>/`.
- Check: `python -m ml.training.train_lstm --small && python -m ml.evaluation.evaluate_all`
- Commit: `feat(ml): stacked lstm with recursive 24h forecast and metrics`

**Phase 12: Emission RF and CO2 trend**
- Touch: `backend/ml/training`, `billing`.
- Deliverables: Random Forest for dynamic emission factor (hour, month, load) with time-aware CV and metrics, linear regression CO2 trend with prediction interval, both optional in the CO2 engine (static factor remains the fallback), metrics appended to `metrics.json`.
- Check: `python -m ml.training.train_emission_rf --small && python -m ml.training.train_co2_trend`
- Commit: `feat(ml): dynamic emission factor model and co2 trend regression`

**Phase 13: Usage anomaly detection**
- Touch: `backend/insights`, `ml/training`.
- Deliverables: anomaly pipeline per space/device combining Isolation Forest, seasonal baseline z-score (hour-of-day x weekday) and rules (night load, baseload jump, device left on), severity levels, Anomaly model with states (open, acknowledged, resolved), evaluation on simulator-injected faults reporting precision/recall/F1 into `metrics.json`.
- Check: `python manage.py test insights.tests.test_anomaly`
- Commit: `feat(insights): usage anomaly detection with severity and states`

**Phase 14: Cause explanation**
- Touch: `backend/insights`.
- Deliverables: rule engine that ranks likely causes with evidence (hour, expected vs actual, device, schedule mismatch, occupancy) and returns structured JSON, template text generator (works offline), optional LLM wording behind a flag using only the structured facts, tests for each injected fault type.
- Check: `python manage.py test insights.tests.test_causes`
- Commit: `feat(insights): ranked cause explanation with evidence`

**Phase 15: Recommendations with savings**
- Touch: `backend/insights`.
- Deliverables: action catalogue (setpoint change, schedule shift, standby cut-off, replace appliance) each computing kWh, rupees and kg CO2 saved per month with the formula and assumptions returned, payback for paid actions, linked to anomaly causes, tests.
- Check: `python manage.py test insights.tests.test_recommendations`
- Commit: `feat(insights): savings recommendation engine`

**Phase 16: Comparison APIs**
- Touch: `backend/insights`.
- Deliverables: space vs space (normalised by area and occupancy, ranked) and period vs period (day, week, month, same weekday last week) endpoints, tests.
- Check: `python manage.py test insights.tests.test_compare`
- Commit: `feat(insights): space and period comparison apis`

### Part D: Frontend

**Phase 17: Live monitor**
- Touch: `frontend/src/pages/Dashboard`, `components`.
- Deliverables: live wattage chart, cumulative Wh, cost and CO2 cards (showing factor source), device online/offline badges, 24 h forecast overlay.
- Check: `cd frontend && npm run lint && npm run build`
- Commit: `feat(ui): live monitor with forecast overlay`

**Phase 18: Comparison and bill views**
- Touch: `frontend/src/pages/Spaces`, `Reports`.
- Deliverables: spaces tree, space-vs-space and period-vs-period charts, bill estimate and projection card.
- Check: `npm run lint && npm run build`
- Commit: `feat(ui): space and period comparison with bill projection`

**Phase 19: Anomalies, causes, recommendations, demo mode**
- Touch: `frontend/src/pages/Insights`.
- Deliverables: alert feed with severity and acknowledge/resolve, cause card with evidence, recommendation card with kWh/rupee/CO2 savings and formula, **Demo mode** button that injects a fault and shows detection to recommendation, ML metrics page reading `metrics.json`.
- Check: `npm run lint && npm run build`; manual: demo button produces an anomaly.
- Commit: `feat(ui): anomaly feed, causes, savings and demo mode`

### Part E: Remaining features

**Phase 20: Activity logging and reports**
- Touch: `backend/activity`, frontend Reports.
- Deliverables: five categories (transport, home energy, diet, shopping, waste) with per-category emission factors, manual form UI, reports page with budget vs usage and top emitters, CSV export (PDF if time allows, else BACKLOG).
- Check: `python manage.py test activity && npm run build`
- Commit: `feat(activity): five-category logging and reports`

**Phase 21: Gamification and proof of saving**
- Touch: `backend/gamification`, frontend Profile.
- Deliverables: XP, levels, streaks, EcoCoins, badges, challenges, leaderboard; proof-of-saving check comparing a claimed reduction with telemetry; manual entries tagged unverified and excluded from ranking; profile, challenges and leaderboard pages.
- Check: `python manage.py test gamification && npm run build`
- Commit: `feat(gamification): xp, challenges, leaderboard and proof of saving`

**Phase 22: Community map and satellite module**
- Touch: `backend/satellite`, frontend Community.
- Deliverables: Leaflet heatmap with coordinates rounded to city level, 20-city NO2 module (static CSV fallback), Isolation Forest hotspots with a validated threshold, `GET /api/satellite-hotspots/`, correct NO2 units shown, linear CO2 trend panel.
- Check: `python manage.py test satellite && npm run build`
- Commit: `feat(satellite): community heatmap and no2 hotspot module`

**Phase 23: Chat ingestion, n8n and NILM**
- Touch: `backend/telemetry` or `activity`, `automation/`, `ml/training`.
- Deliverables: `POST /api/ingest/chat/` with range validation, mock Gemini/Whisper extractors behind an interface, n8n workflow JSON (webhook, switch text/image/audio, extract, insert, reply) with setup README, NILM step-change detector plus optional CNN+LSTM trainer, metrics written or marked "not evaluated".
- Check: `python manage.py test telemetry.tests.test_chat_ingest`
- Commit: `feat(ingest): chat ingestion, n8n workflow and nilm`

**Phase 24: ESP32 firmware**
- Touch: `firmware/`.
- Deliverables: PlatformIO project, `config.example.h`, ZMPT101B + SCT-013 sampling with EmonLib, RMS, power factor, active power, 30 s JSON POST with device token, flash buffer and chronological backfill, wiring README.
- Check: `ls firmware` and, if PlatformIO is installed, `pio run`; otherwise skip the build and say so.
- Commit: `feat(firmware): esp32 true-power meter with offline buffer`

**Phase 25: Packaging, docs and final check**
- Touch: root, `docs/`, `.github/`.
- Deliverables: `docker-compose.yml` (backend, frontend, db), CI workflow (lint, build, tests), `docs/ARCHITECTURE.md`, `API.md`, `ML_EVALUATION.md` generated from `metrics.json`, `DEMO.md` script (inject fault, detect, explain, recommend), final README with install steps and limitations, tick all rows in `PROGRESS.md`.
- Check: backend tests + frontend build pass; `docker compose config` is valid.
- Commit: `docs: packaging, ci and final documentation`

---

## DEFINITION OF DONE

All 25 rows are `DONE`, tests and build pass, `metrics.json` exists, and `docs/DEMO.md` works: inject a fault, see the anomaly, ranked cause and a recommendation with savings.

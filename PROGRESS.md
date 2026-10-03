# PROGRESS — EcoTrack 25-phase build

Authoritative plan: `CLAUDE-plan.md`. One phase per run; the user commits after each phase.
Status values: `TODO` · `IN PROGRESS` · `BLOCKED` · `DONE`

| # | Phase | Part | Status | Summary |
| --- | --- | --- | --- | --- |
| 1 | Audit existing repo and add tracking | A Foundation | DONE | Audited repo (empty uv backend, React 19 + TS Vite frontend); added AUDIT/PROGRESS/BACKLOG, root .gitignore, layout folders, README plan section. |
| 2 | Backend skeleton | A Foundation | DONE | Django 5.2 + DRF + CORS in `config/`, env-driven settings with SQLite fallback, requirements.txt, .env.example, `GET /api/health/`; 8 tests pass. |
| 3 | Frontend skeleton | A Foundation | DONE | Tailwind v4 + react-router 7 added to the existing React 19/TS app; layout shell, 6 placeholder pages + 404, API client with `VITE_API_BASE_URL` and dev proxy; starter page preserved at `/welcome`. |
| 4 | Auth and roles | A Foundation | DONE | Custom `accounts.User` with admin/manager/member roles, JWT login/refresh/verify/me with role claim, role permission classes, frontend AuthProvider + ProtectedRoute + login page; 25 accounts tests (33 total) pass. |
| 5 | Spaces hierarchy | A Foundation | DONE | Organisation > Building > Floor > Room with derived area/occupancy, membership-scoped CRUD + `/tree/`, idempotent `seed_spaces` (office + home); 46 spaces tests (79 total) pass. |
| 6 | Telemetry ingestion | B Data pipeline | DONE | Device + Reading models with named units, hashed device-token auth, `POST /api/readings/` (single/list/wrapped, validated, idempotent chronological backfill), digital-twin status; 69 telemetry tests (148 total) pass. |
| 7 | Simulator | B Data pipeline | DONE | Stdlib-only generator for home + office (6 appliances each + mains sum), seeded and byte-reproducible, 3 injectable faults with per-sample labels, CSV or live POST with device auto-registration. |
| 8 | Rollups API | B Data pipeline | DONE | `GET /api/usage/` with hour/day/month local-time buckets, grouping by time/device/room, scope by space or device, and an explicit metering mode that prevents mains+appliance double counting; 64 rollup tests (212 total) pass. |
| 9 | Cost and CO2 engines | B Data pipeline | DONE | Cumulative slab + time-of-day + fixed charge + tax engines returning per-line formulas, month projection with stated assumptions, CO2 engine always naming its factor source; sample rates flagged; 96 billing tests (308 total) pass. |
| 10 | ML data and synthetic generator | C Machine learning | DONE | UCI loader (one download attempt, synthetic fallback), kW->kWh cleaning with coverage filtering, chronological split, synthetic emission-factor generator, provenance sidecars + data README; 44 ml tests (352 total) pass. |
| 11 | LSTM forecasting | C Machine learning | DONE | Stacked-LSTM spec implemented with a Keras backend plus a labelled sklearn-MLP fallback (TensorFlow download failed); train-only scaler, chronological split, recursive 24-step inference, 3 naive baselines, MAE/RMSE/MAPE/R2 in metrics.json, `GET /api/forecast/<device>/`. |
| 12 | Emission RF and CO2 trend | C Machine learning | DONE | Random forest with TimeSeriesSplit CV (MAE 0.019 vs 0.118 baseline), OLS CO2 trend with prediction interval and slope p-value, both optional in the CO2 engine via `?emission_model=rf`; static 0.82 factor remains the default. |
| 13 | Usage anomaly detection | C Machine learning | DONE | Isolation Forest + robust seasonal z-score + 3 rules, severity and open/ack/resolved states; no fixed contamination or fixed percentile; precision/recall/F1 vs simulator faults written to metrics.json (night-load F1 1.00, ac-left-on 0.85). |
| 14 | Cause explanation | C Machine learning | DONE | Rule-ranked causes with evidence and confidence, offline templates, optional LLM rewording behind a flag that never introduces numbers; one test per injected fault type. |
| 15 | Recommendations with savings | C Machine learning | DONE | Four-action catalogue computing kWh/INR/kg CO2 per month with the formula, assumptions and payback returned; priced at the marginal slab rate via the Phase 9 engines. |
| 16 | Comparison APIs | C Machine learning | DONE | Space-vs-space normalised per m2 and per person with unmeasured spaces excluded and listed; period-vs-period for day/week/month/same-weekday with pro-rating for incomplete periods. |
| 17 | Live monitor | D Frontend | DONE | Hourly energy chart with dashed 24 h forecast overlay, energy/peak/cost/CO2 tiles naming their sources, device online/offline badges, factor provenance panel. |
| 18 | Comparison and bill views | D Frontend | DONE | Spaces tree from the single prefetched tree call, normalised ranked comparison bars, period comparison with pro-rating, bill estimate and projection with slab breakdown. |
| 19 | Anomalies, causes, recommendations, demo mode | D Frontend | DONE | Anomaly feed with severity and ack/resolve/dismiss, cause card with evidence, recommendation card with savings and formulas, one-click demo fault injection, ML metrics page reading metrics.json. |
| 20 | Activity logging and reports | E Remaining | DONE | Five categories with 23 seeded unverified factors, snapshotted per-entry factors, owner-private entries, budget vs usage, top emitters, auditable CSV export; 38 tests. |
| 21 | Gamification and proof of saving | E Remaining | DONE | XP/levels/streaks/EcoCoins, 7 badges, challenges, leaderboard ranked on VERIFIED savings only; proof-of-saving compares a claim against telemetry with window-length normalisation; 45 tests. |
| 22 | Community map and satellite module | E Remaining | DONE | Leaflet map with coordinates rounded to ~100 m on save, 20-city NO2 static fallback in umol/m2 of tropospheric column (no ppb conversion), Isolation Forest hotspots on a validated threshold, CO2 trend panel; 32 tests. |
| 23 | Chat ingestion, n8n and NILM | E Remaining | DONE | `POST /api/ingest/chat/` with range validation and interval spreading, mock text extractor plus declining image/audio extractors, n8n workflow JSON + setup README, NILM step-change detector with metrics 'not evaluated'; 39 tests. |
| 24 | ESP32 firmware | E Remaining | DONE | PlatformIO project, config.example.h, EmonLib real-power sampling, 30 s JSON POST with device token, NVS flash ring buffer with chronological replay, wiring and calibration README. `pio run` skipped - PlatformIO not installed here. |
| 25 | Packaging, docs and final check | E Remaining | DONE | docker-compose (db/backend/frontend) + Dockerfiles + nginx, CI workflow covering backend/simulator/frontend/compose, ARCHITECTURE/API/DEMO docs, ML_EVALUATION.md generated from metrics.json, final README with limitations. |

## Definition of done

All 25 rows `DONE`, backend tests and frontend build pass, `backend/ml/artifacts/metrics.json` exists,
and `docs/DEMO.md` works end to end: inject a fault → anomaly detected → ranked cause → recommendation
with kWh / rupee / kg CO2 savings.

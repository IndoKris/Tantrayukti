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
| 11 | LSTM forecasting | C Machine learning | TODO | |
| 12 | Emission RF and CO2 trend | C Machine learning | TODO | |
| 13 | Usage anomaly detection | C Machine learning | TODO | |
| 14 | Cause explanation | C Machine learning | TODO | |
| 15 | Recommendations with savings | C Machine learning | TODO | |
| 16 | Comparison APIs | C Machine learning | TODO | |
| 17 | Live monitor | D Frontend | TODO | |
| 18 | Comparison and bill views | D Frontend | TODO | |
| 19 | Anomalies, causes, recommendations, demo mode | D Frontend | TODO | |
| 20 | Activity logging and reports | E Remaining | TODO | |
| 21 | Gamification and proof of saving | E Remaining | TODO | |
| 22 | Community map and satellite module | E Remaining | TODO | |
| 23 | Chat ingestion, n8n and NILM | E Remaining | TODO | |
| 24 | ESP32 firmware | E Remaining | TODO | |
| 25 | Packaging, docs and final check | E Remaining | TODO | |

## Definition of done

All 25 rows `DONE`, backend tests and frontend build pass, `backend/ml/artifacts/metrics.json` exists,
and `docs/DEMO.md` works end to end: inject a fault → anomaly detected → ranked cause → recommendation
with kWh / rupee / kg CO2 savings.

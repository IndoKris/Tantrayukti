# PROGRESS — EcoTrack 25-phase build

Authoritative plan: `CLAUDE-plan.md`. One phase per run; the user commits after each phase.
Status values: `TODO` · `IN PROGRESS` · `BLOCKED` · `DONE`

| # | Phase | Part | Status | Summary |
| --- | --- | --- | --- | --- |
| 1 | Audit existing repo and add tracking | A Foundation | DONE | Audited repo (empty uv backend, React 19 + TS Vite frontend); added AUDIT/PROGRESS/BACKLOG, root .gitignore, layout folders, README plan section. |
| 2 | Backend skeleton | A Foundation | TODO | |
| 3 | Frontend skeleton | A Foundation | TODO | |
| 4 | Auth and roles | A Foundation | TODO | |
| 5 | Spaces hierarchy | A Foundation | TODO | |
| 6 | Telemetry ingestion | B Data pipeline | TODO | |
| 7 | Simulator | B Data pipeline | TODO | |
| 8 | Rollups API | B Data pipeline | TODO | |
| 9 | Cost and CO2 engines | B Data pipeline | TODO | |
| 10 | ML data and synthetic generator | C Machine learning | TODO | |
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

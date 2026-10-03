# Tantrayukti Team 100X
YCCE-26 Nagpur~

## Project plan

This repo is being built out as **EcoTrack** — an energy, cost and CO2 monitoring dashboard that
records energy use, estimates cost and CO2, compares usage across spaces and time periods, detects
abnormal usage automatically, explains the likely cause, and suggests specific actions with estimated
savings in kWh, rupees and kg CO2.

**Stack:** React + Vite + TypeScript + Tailwind + Recharts + Leaflet (frontend) · Django + DRF + JWT
(backend) · PostgreSQL with SQLite fallback · scikit-learn and TensorFlow/Keras for forecasting,
anomaly detection and emission modelling · ESP32 firmware and a load simulator for data.

**Build tracking**

| Document | Purpose |
| --- | --- |
| [`CLAUDE-plan.md`](CLAUDE-plan.md) | The authoritative 25-phase build plan |
| [`PROGRESS.md`](PROGRESS.md) | Status of all 25 phases |
| [`AUDIT.md`](AUDIT.md) | What existed in this repo before the build, and conflicts with the plan |
| [`BACKLOG.md`](BACKLOG.md) | Deferred ideas, kept out of phase scope |

Metrics shown anywhere in the UI or docs come from `backend/ml/artifacts/metrics.json`, produced by
the evaluation code — never hard-coded.

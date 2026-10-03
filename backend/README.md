# EcoTrack backend

Django 5.2 + Django REST Framework API for energy, cost and CO2 monitoring.

## Requirements

- Python >= 3.12 (pinned to 3.12 in `.python-version`; see `../AUDIT.md` Q1)
- [`uv`](https://docs.astral.sh/uv/) for dependency management, or plain `pip`

## Setup

```bash
cd backend
uv sync                      # creates .venv and installs dependencies
uv sync --extra postgres     # add this if you will use PostgreSQL
cp .env.example .env         # optional: every value has a working default
uv run python manage.py migrate
uv run python manage.py runserver
```

Without `uv`:

```bash
python -m venv .venv
.venv/Scripts/activate       # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

With the virtual environment activated, the plan's commands work verbatim
(`python manage.py check`, `python manage.py test`).

## Commands

| Command | Purpose |
| --- | --- |
| `uv run python manage.py check` | Django system checks |
| `uv run python manage.py test` | Run the test suite |
| `uv run python manage.py migrate` | Apply migrations |
| `uv run python manage.py createsuperuser` | Admin user for `/admin/` |
| `uv run python manage.py runserver` | Dev server on http://127.0.0.1:8000 |

## Configuration

All settings are environment-driven; see [`.env.example`](.env.example) for the full list.
A `.env` file in this directory is loaded automatically, and real environment variables override it.

**Database.** Set `DATABASE_URL` to use PostgreSQL. When it is empty or unset the project falls
back to SQLite at `backend/db.sqlite3`, so no database server is needed to run or demo the project.
`GET /api/health/` reports which path is active, so the fallback is never silent.

**Dependencies.** `pyproject.toml` is the source of truth. After changing it, regenerate the
pinned list:

```bash
uv export --format requirements-txt --no-hashes --no-emit-project --extra postgres -o requirements.txt
```

## Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/health/` | none | Liveness probe: version, environment, database engine and reachability |
| — | `/admin/` | session | Django admin |

DRF defaults to `IsAuthenticated`, so new endpoints are private unless they opt out the way
`HealthView` does. JWT authentication arrives in Phase 4.

### `GET /api/health/`

```json
{
  "status": "ok",
  "service": "ecotrack-backend",
  "version": "0.1.0",
  "environment": "development",
  "debug": true,
  "time": "2026-10-03T05:59:32.678143+00:00",
  "database": { "engine": "sqlite3", "configured_via": "sqlite-fallback", "reachable": true }
}
```

Returns `200` with `"status": "ok"` when the database answers, `503` with `"status": "degraded"`
and an `error` field when it does not.

## Layout

```
backend/
  manage.py
  config/            project settings, root URLs, health endpoint
  accounts/          Phase 4  - custom user and roles
  spaces/            Phase 5  - organisation > building > floor > room
  telemetry/         Phase 6  - devices, readings, rollups
  billing/           Phase 9  - tariffs, cost and CO2 engines
  insights/          Phase 13 - anomalies, causes, recommendations, comparisons
  activity/          Phase 20 - five-category activity logging
  gamification/      Phase 21 - XP, challenges, leaderboard
  satellite/         Phase 22 - NO2 hotspots
  ml/                Phases 10-12 - data, training, evaluation, artifacts
  main.py            pre-existing stub from the original scaffold; unused
```

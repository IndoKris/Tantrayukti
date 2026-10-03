# EcoTrack load simulator

Generates realistic appliance load for a home and an office, with optional fault
injection, and either summarises it, writes CSV, or posts it to the API as real
device telemetry.

**Stdlib only.** It runs on a bare Python 3.10+ with no virtualenv and no
`pip install` — the backend venv is not needed.

> The output is **synthetic sample data**, not measured consumption. The load
> curves have realistic *shape* (diurnal peaks, weekday/weekend difference,
> compressor cycling); they are not a validated building-physics model.

## Quick start

```bash
# Summary only, nothing written
python simulator/run.py --days 7 --dry-run

# CSV for offline work and ML training
python simulator/run.py --days 30 --csv data/load.csv

# Inject faults for the anomaly demo
python simulator/run.py --days 14 --fault ac-left-on --fault night-load --dry-run

# Post to a running backend, registering devices as needed
python simulator/run.py --days 2 --post --register --username demo --password '...'
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--days N` | 7 | Days of data to generate |
| `--interval SECONDS` | 300 | Sampling interval |
| `--site home\|office\|both` | both | Which site to simulate |
| `--seed N` | 20261003 | Random seed; identical runs are byte-identical |
| `--start ISO8601` | now − days | UTC start time |
| `--fault NAME` | none | Repeatable; see Faults below |
| `--dry-run` | on when no other output | Print the per-appliance summary |
| `--csv PATH` | — | Write every sample to CSV |
| `--post` | — | Post readings to the API |
| `--api-url URL` | `http://127.0.0.1:8000` | Backend base URL |
| `--register` | — | Create/reuse a device per appliance and cache tokens |
| `--username` / `--password` | — | Credentials for `--register` (needs manager role) |
| `--tokens PATH` | — | JSON map `"<site>.<appliance>" → token`, instead of `--register` |

## What it generates

Per site, one series per appliance **plus a `mains` series that is their sum**.
Both are needed: per-appliance series drive device-level anomaly detection
(Phase 13), and the mains aggregate is what NILM disaggregates (Phase 23). The
summary prints both so the sum always reconciles.

| Home | Office |
| --- | --- |
| Refrigerator (cycling, 140 W) | HVAC (thermostatic, 3600 W) |
| Bedroom AC (thermostatic, 1500 W) | Lighting (scheduled, 850 W) |
| Lighting (scheduled, 180 W) | Workstations (scheduled, 1250 W) |
| Washing machine (intermittent, 520 W) | Server rack (always-on, 420 W) |
| Television (scheduled, 110 W) | Canteen refrigerator (cycling, 210 W) |
| Standby (always-on, 34 W) | Standby (always-on, 95 W) |

Units follow `telemetry.Reading`: **W** for power, **Wh** for interval energy.
Current is derived as `I = P / (V × pf)`, so a posted reading is internally
consistent and passes the server-side check that active power cannot exceed
apparent power.

## Faults

Faults begin **60% of the way into the run**, leaving clean history for a
baseline to be learned from before anything goes wrong.

| `--fault` | What it does |
| --- | --- |
| `ac-left-on` | The AC/HVAC keeps running at 55–75% rated power during hours it would otherwise be idle |
| `night-load` | An extra ~900 W appears between 01:00 and 05:00 on lighting/workstations |
| `baseload-jump` | The always-on draw steps up by ~420 W and stays up |

**Every sample records which fault was active**, in the `fault` CSV column.
Phase 13 measures the detector's precision/recall against exactly these labels,
so an unlabelled injection would make the evaluation meaningless.

## Reproducibility

Each appliance gets its own RNG seeded from `seed:site:appliance`, so adding an
appliance does not shift the numbers generated for the others, and two runs with
the same arguments produce byte-identical CSV. This matters because Phase 13
compares detector scores across runs.

## Posting notes

`--register` logs in, finds the rooms created by `manage.py seed_spaces`, creates
a device per appliance, and caches the tokens in `simulator/.tokens.json`
(gitignored — it holds live device credentials).

Run the seed first, or registration has no rooms to attach to:

```bash
cd backend && uv run python manage.py seed_spaces
```

Re-posting the same window is safe: `(device, timestamp)` is unique server-side,
so a replay reports `duplicates` and creates nothing. If a device already exists
but its token is not cached, `--register` rotates the token, which needs the
**admin** role.

## Exit codes

`0` on success. `1` when posting fails, the token file is unreadable, or no
token is available for a series — so a scripted run cannot mistake a failed
upload for a successful one.

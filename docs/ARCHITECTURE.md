# Architecture

EcoTrack records energy use, estimates cost and CO₂, compares usage across spaces
and time, detects abnormal usage, explains the likely cause, and recommends
actions with estimated savings.

## Shape

```
    ESP32 meter ──┐
                  │  POST /api/readings/   (device token)
    simulator ────┤
                  │
    chat / n8n ───┤  POST /api/ingest/chat/ (user JWT)
                  ▼
         ┌──────────────────┐
         │  telemetry       │  Device, Reading  ·  rollups
         └────────┬─────────┘
                  │  hourly / daily / monthly kWh
      ┌───────────┼───────────┬──────────────┬─────────────┐
      ▼           ▼           ▼              ▼             ▼
   billing     insights    gamification   satellite     ml/
   cost+CO₂    anomalies   proof of       NO₂ +         forecast,
               causes      saving         community     emission RF,
               savings                    map           CO₂ trend, NILM
      └───────────┴───────────┴──────────────┴─────────────┘
                              │  DRF + JWT
                              ▼
                   React 19 + Vite + Tailwind v4
                   Recharts · Leaflet
```

## Backend apps

| App | Owns | Key idea |
| --- | --- | --- |
| `accounts` | Custom user, roles, JWT | Roles ranked; the JWT carries a role claim but **authorisation always reads the database** |
| `spaces` | Organisation → Building → Floor → Room, Membership | Area and occupancy resolve upwards; unknown stays `None`, never `0` |
| `telemetry` | Device, Reading, rollups, chat ingest | Device-token auth; `(device, timestamp)` unique so replays are idempotent |
| `billing` | Tariffs, slabs, time-of-day, CO₂ engine | Every bill returns per-line formulas |
| `insights` | Anomalies, causes, recommendations, comparisons, forecast API | Rule-ranked causes with evidence |
| `activity` | Five-category manual logging | Entries are always `is_verified=False` |
| `gamification` | XP, badges, challenges, proof of saving | Leaderboard ranks **verified** savings only |
| `satellite` | City NO₂, community map, hotspots | NO₂ is a **column density**, coordinates rounded to ~100 m |
| `ml/` | Data prep, training, evaluation, inference | Plain package, not a Django app |

## Decisions worth knowing

### Scoping lives in `get_queryset`

Every viewset filters to the caller's organisations in `get_queryset`, so a
foreign object returns **404, not 403**. A forgotten object-level permission
check therefore cannot leak data through a detail route, a nested write or a
query-param filter. Activity entries and saving claims go further and are scoped
to `request.user`, because a diet log is personal data rather than building data.

### `metering=auto` prevents a factor-of-two error

A room can hold both a whole-space mains meter and per-appliance meters covering
the same load. Summing every device would report roughly double. `auto` uses
mains meters when present, else appliance meters, and **every response states
which was applied**. Measured on seeded data: `auto` 13.85 kWh from 3 devices,
`all` 27.54 kWh from 15.

Billing, comparisons and proof-of-saving all draw energy through the same
rollups, so they cannot disagree with the dashboard.

### Units are in the field names

`active_power_w` (W, instantaneous) and `energy_wh` (Wh, **this interval only**)
are different quantities and never share an axis or a column. The UCI loader
exists largely to handle this: that file mixes kilowatts with watt-hours in one
CSV.

### Buckets are local-time

`TruncHour`/`TruncDay`/`TruncMonth` use `Asia/Kolkata`. A test stores readings at
23:30 and 00:30 IST either side of midnight and asserts they land in *different*
daily buckets — in UTC they would share a day, smearing time-of-day tariffs and
the night-load rule across midnight.

### Decimals are strings on the wire

`config/encoders.py` installs a renderer that emits `Decimal` as a JSON string.
DRF's default calls `float(obj)`, which turned the emission factor `0.82` into
`0.81999999999999995` and made hand-built responses disagree with
serializer-built ones.

### Gaps are not zero-filled

A bucket with no readings is omitted from a series rather than reported as 0 kWh:
"consumed nothing" and "the device was offline" are different facts.

## The honesty rule, mechanically

The plan forbids inventing metrics. That is enforced structurally rather than by
good intentions:

| Claim | How it is kept |
| --- | --- |
| No invented metrics | `metrics.json` is written only by evaluation code; `/api/ml/metrics/` serves it verbatim; `docs/ML_EVALUATION.md` is generated from it |
| No fake accuracy | Regression results are MAE/RMSE/MAPE/R² against three naive baselines. The word "accuracy" is not used for a regression |
| Sample tariffs are labelled | `Tariff.is_sample` plus a `source` beginning "ILLUSTRATIVE SAMPLE RATES", returned with every estimate |
| The CO₂ factor names itself | 0.82 kg/kWh is `is_verified=False` with a source pointing at the CEA database; the modelled factor is opt-in via `?emission_model=rf` |
| Fallback models say so | `is_fallback` travels from the manifest through `metrics.json` to the API and the UI |
| Synthetic data says so | Every row carries `is_synthetic`; provenance sidecars sit beside each dataset |
| Self-reported ≠ measured | Activity entries are `is_verified=False`; the leaderboard ranks verified XP only |
| No fabricated extractions | Image/audio extractors **decline** with a 422 rather than return a plausible number |
| NO₂ is not surface air quality | Values are µmol/m² of tropospheric column; no ppb conversion exists in the codebase |
| NILM is unscored | No UK-DALE labels, so metrics are `"not evaluated"` with the reason |

### Detector thresholds are validated, not fixed

The plan warns against `contamination=0.02`, which forces a fixed fraction of
points to be anomalies. An early version of the anomaly detector used the 1st
percentile of the Isolation Forest score distribution — the same defect in
disguise — and its own test caught it by flagging anomalies in a clean week.

Both detectors now require **two independent conditions**: the forest's own
`contamination="auto"` offset *and* a robust magnitude fence
(`median + k × MAD-sigma`) computed per hour-of-day. A clean period therefore
yields no anomalies, and an empty hotspot list is a real answer.

## Fallbacks, and what is currently active

| Missing | Fallback | Active here? |
| --- | --- | --- |
| PostgreSQL | SQLite at `backend/db.sqlite3` | Yes in dev, no under compose |
| TensorFlow | sklearn MLP, labelled `is_fallback` | **Yes** — the download failed |
| UCI dataset | Synthetic generator, labelled | No — the download succeeded |
| UK-DALE | Step-change NILM, metrics "not evaluated" | **Yes** |
| Gemini / Whisper | Declining extractors | **Yes** |
| Earth Engine | Static 20-city CSV | **Yes** |
| Hardware | Simulator posting to the same endpoint | **Yes** |

## Request flow: a bill

1. `/api/billing/estimate/?space=building:3&from=…&to=…`
2. `rollups.resolve_scope` → devices in that scope, filtered to the caller's orgs
3. `rollups.select_devices` → `metering=auto` picks mains over appliances
4. `rollups.time_series` → local-hour buckets of kWh
5. `engines.slab_charge` → cumulative slabs on the monthly total
6. `engines.tou_adjustment` → `units × effective_rate × (multiplier − 1)` per window
7. `engines.estimate_co2` → `kWh × factor`, with the factor's provenance
8. Response: per-slab formulas, the ToD lines, the fixed charge, tax, and both
   the tariff's and the factor's sources

## Request flow: detect → explain → recommend

1. `POST /api/anomalies/detect/` runs five detectors over the hourly series
2. Findings persist as `Anomaly` rows, idempotent on
   `(device, detector, window_start)`; a resolved anomaly is never reopened
3. `GET /api/anomalies/<id>/causes/` ranks causes from the stored evidence by
   deterministic rules — never by a language model
4. `GET /api/anomalies/<id>/recommendations/` prices actions through the Phase 9
   engines at the **marginal** slab rate, returning kWh, ₹, kg CO₂, the formula
   and the assumptions
5. `POST /api/demo/inject-fault/` does all of it in one call for the demo

## Frontend

- React 19 + TypeScript, Vite 8, Tailwind v4 configured in CSS
- `ProtectedRoute` guards everything but `/login` and `/welcome`
- `api/client.ts` attaches the JWT and does **one** refresh-and-retry on a 401,
  with concurrent 401s sharing a single in-flight refresh
- Charts use a validated palette (CVD ΔE 9.2 light / 9.4 dark); every chart ships
  a legend and a table view, because light-mode series-3 is below 3:1 contrast
- `useApi` derives `loading` rather than storing it, avoiding a setState inside
  an effect

The original Vite starter page is preserved at `/welcome`; `App.tsx`, `App.css`,
`src/assets/` and `public/` are byte-for-byte unchanged from before this build.

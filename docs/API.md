# API reference

Base URL: `http://127.0.0.1:8000` in development, same-origin `/api/...` under
Docker Compose.

Two authentication schemes, deliberately separate:

| Scheme | Header | Used by |
| --- | --- | --- |
| User JWT | `Authorization: Bearer <access>` | Everything except reading ingestion |
| Device token | `Authorization: Device <token>` (or `X-Device-Token`) | `POST /api/readings/` only |

A user JWT **cannot** post readings (403), so a stolen user token cannot forge
telemetry. DRF defaults to `IsAuthenticated`, so an endpoint is private unless it
opts out.

---

## Conventions

- **Decimals are JSON strings**, not floats — `"0.82000"`, not
  `0.81999999999999995`.
- **Datetimes are ISO-8601 in the active timezone** (`Asia/Kolkata`), and every
  route agrees.
- **Units are in field names**: `_w` watts, `_wh` watt-hours, `_kwh`
  kilowatt-hours, `_inr` rupees, `kg_co2`, `_sqm`, `umol_per_m2`.
- **Pagination** is page-number with `PAGE_SIZE=100`; pass `?page_size=`.
- **409** means "not ready yet" with a `how_to_fix`, not a failure.
- **422** means "I will not guess" — an extractor that cannot read its input.

---

## Health

### `GET /api/health/` · no auth

```json
{"status": "ok", "service": "ecotrack-backend", "version": "0.1.0",
 "environment": "development", "debug": true, "time": "2026-10-03T13:11:14+05:30",
 "database": {"engine": "sqlite3", "configured_via": "sqlite-fallback", "reachable": true}}
```

`200` when the database answers, `503` with `"status": "degraded"` when not.
`configured_via` makes the SQLite fallback visible rather than silent.

---

## Auth — `/api/auth/`

| Method | Path | Notes |
| --- | --- | --- |
| POST | `login/` | `{username, password}` → `access`, `refresh`, `user` |
| POST | `refresh/` | `{refresh}` → new `access` **and** a rotated `refresh` |
| POST | `verify/` | Token validity |
| GET | `me/` | The caller, read from the database so a role change is live |

The access token carries a `role` claim for UI convenience. **Authorisation never
uses it** — permission classes read the role from the database, and a test
asserts a role change takes effect on an already-issued token.

---

## Spaces — `/api/spaces/`

| Method | Path | Role |
| --- | --- | --- |
| GET/POST | `organisations/` | read: member · write: manager |
| GET | `organisations/tree/` | Whole hierarchy, prefetched, in one call |
| GET/POST | `buildings/` `?organisation=` | manager to write |
| GET/POST | `floors/` `?building=` | manager to write |
| GET/POST | `rooms/` `?floor=` `?building=` | manager to write |
| GET/POST | `memberships/` | **admin** to write |

Creating an organisation makes the creator a member, or it would be invisible
immediately. `total_area_sqm` and `total_occupancy` resolve upwards from children
and are `null` — never `0` — when unknown, so Phase 16 can skip a space rather
than divide by zero.

---

## Telemetry

### `POST /api/readings/` · **device token**

Accepts three shapes: a single object, a bare list, or
`{"readings": [...], "buffer_count": 12, "firmware_version": "1.2.0"}`.

```json
{"timestamp": "2026-10-03T07:00:00Z", "active_power_w": "1430.50",
 "voltage_v": "231.20", "current_a": "6.400", "power_factor": "0.965"}
```

`energy_wh` is optional and derived from power × interval when omitted. It is
energy for **this interval only**, never a cumulative total.

Response reports what was written, so firmware can trim its buffer:

```json
{"received": 6, "created": 6, "duplicates": 0, "device": {...}}
```

Rejected with **400**: negative power or energy, voltage > 500 V, power factor
> 1, a timestamp more than 5 minutes in the future, backfill older than 90 days,
duplicate timestamps within a batch, and **active power exceeding apparent power**
(V × A, +10% tolerance) — which catches a mis-scaled clamp.

Idempotent: `(device, timestamp)` is unique, so replaying a flash buffer creates
nothing. Batches are sorted before insert, so a backfill lands in sample order.

### `POST /api/ingest/chat/` · user JWT

```json
{"device": 3, "modality": "text", "text": "AC ran 4 hours at 1500 W",
 "occurred_on": "2026-10-03"}
```

Stored with `source=import`, so chat data stays distinguishable from metered
telemetry. The reported energy is **spread across intervals**, not stored as one
spike that the anomaly detector would rightly flag.

**422** for an image or audio payload: no vision or speech provider is
configured, and the extractor declines rather than returning a plausible number.
Also 422 for unparseable text (with guidance) or an implausible figure (with the
failed check).

### Devices — `/api/devices/`

| Method | Path | Role |
| --- | --- | --- |
| GET/POST | `/api/devices/` `?room=` `?building=` `?organisation=` | manager to write |
| GET | `/api/devices/<id>/status/` | The digital twin |
| GET | `/api/devices/<id>/readings/` | Newest first, paginated |
| POST | `/api/devices/<id>/rotate-token/` | **admin** |

Creation returns the raw `token` **once**; only its SHA-256 hash is stored, so a
lost token must be rotated, not looked up. `status/` reports `online`/`offline`/
`never-seen`/`disabled`, `offline_after_seconds` (so the threshold explains
itself), and **both** buffer counts — what the device claims it holds and what
the server saw arrive late.

### `GET /api/usage/`

| Parameter | Values |
| --- | --- |
| `space` | `<kind>:<id>` — organisation, building, floor, room |
| `organisation` / `building` / `floor` / `room` / `device` | Explicit alternative |
| `period` | `hour` (default), `day`, `month` — **local** buckets |
| `from` / `to` | ISO date or datetime |
| `group_by` | `time` (default), `device`, `room` |
| `metering` | `auto` (default), `mains`, `appliance`, `all` |

Every response carries `metering.requested`, `metering.applied`, `device_count`
and `device_ids`. Empty buckets are omitted, not zero-filled.

---

## Billing — `/api/billing/`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `estimate/` | Cost + CO₂ for a window; same scope params as `/api/usage/` |
| GET | `projection/` | Month-to-date and a naive month-end projection |
| GET/POST | `tariffs/` `slabs/` `tou-rates/` | manager to write |
| GET/POST | `emission-factors/` | manager to write |
| GET/POST | `settings/` | Per-organisation tariff and factor |

`estimate/` extras: `tariff=<id>`, `emission_factor=<id>`,
`fixed_charge=true|false` (defaults off below 28 days),
`emission_model=rf` (adds `co2_modelled` from the Phase 12 hourly factor; the
static factor stays the default and the response says which applied).

Every bill returns per-slab lines with a `formula` string, the time-of-day
adjustment per window, the fixed charge, tax, the effective rate, and both the
tariff's `is_sample`/`source` and the CO₂ factor's `source`/`is_verified`.

---

## Insights

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/forecast/<device>/` | 24 h recursive forecast + the last 24 h |
| GET | `/api/ml/metrics/` | `metrics.json` verbatim |
| GET | `/api/anomalies/` | `?state=` `?severity=` `?device=` `?open=true` |
| POST | `/api/anomalies/detect/` | `{device, days}` — **manager** |
| POST | `/api/anomalies/<id>/acknowledge/` `resolve/` `dismiss/` | manager |
| GET | `/api/anomalies/<id>/causes/` | Ranked, with evidence; `?llm=1` optional |
| GET | `/api/anomalies/<id>/recommendations/` | kWh / ₹ / kg CO₂ + formulas |
| GET | `/api/compare/spaces/` | `?space=` `?normalise_by=area\|occupancy\|none` |
| GET | `/api/compare/periods/` | `?period=day\|week\|month\|same_weekday_last_week` |
| POST | `/api/demo/inject-fault/` | `{device, fault, days}` — **manager** |

`/api/forecast/` returns **409** when no model is trained or the device has under
24 hours of history, with a `how_to_fix` — never a fabricated curve.

Space comparison **excludes** spaces with no area or occupancy and lists them in
`excluded`, rather than ranking them on raw energy. Period comparison pro-rates
an incomplete current period, so a half-finished month does not look like a
saving.

---

## Activity — `/api/activity/`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `factors/` `?category=` | Read-only; 23 seeded factors, all unverified |
| GET/POST/PATCH/DELETE | `entries/` | **Private to the caller** |
| GET | `report/` `?from=` `?to=` | Category totals, top emitters, budget |
| GET | `report.csv` | Includes the formula and factor source per row |
| GET/PUT | `budget/` | Monthly CO₂e target |

Entries are always `is_verified=false`. The factor is **snapshotted per entry**,
so correcting a factor later cannot rewrite history.

---

## Gamification — `/api/game/`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `profile/` | Verified and unverified XP reported separately |
| GET | `leaderboard/` `?limit=` | Ranks **verified** XP only |
| GET | `badges/` | Definitions and criteria |
| GET | `challenges/` · POST `challenges/<id>/join/` | |
| GET/POST | `claims/` | Proof of saving; private to the caller |
| POST | `claims/<id>/verify/` | Checks telemetry, credits the **measured** saving |
| POST | `claims/<id>/preview/` | Same check, awards nothing |

A claim names a device and two windows. Verification scales the baseline to the
claim window's length before subtracting — otherwise a 14-day baseline against a
7-day claim would show a 50% "saving" from arithmetic alone. Too little telemetry
gives `unverifiable`, not `rejected`: "we cannot tell" and "it did not happen"
are different answers.

---

## Satellite — community

| Method | Path | Notes |
| --- | --- | --- |
| GET/POST | `/api/satellite-hotspots/` | GET previews, POST persists |
| GET | `/api/satellite/cities/` | 20 cities with units and provenance |
| GET | `/api/community/map/` `?days=` | Energy points + NO₂ layer |
| GET | `/api/community/co2-trend/` | Linear trend with prediction interval |

**NO₂ is `umol_per_m2` of tropospheric column**, not a surface concentration.
No ppb conversion exists anywhere in the codebase, and a test asserts no response
field mentions ppb, µg/m³ or "surface". Coordinates are rounded to 3 decimal
places (~100 m) **before storage**.

An empty hotspot list means no city stands out — a real answer, because no fixed
fraction is labelled.

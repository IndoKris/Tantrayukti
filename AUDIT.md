# AUDIT — existing repository state before the EcoTrack build

Audited: 2026-10-03 · Repo: `IndoKris/Tantrayukti` · Branch: `main` · Last commit at audit time: `adfbaf0`

This file records what already existed in the repo **before** Phase 1 of `CLAUDE-plan.md`, so later
phases extend it instead of overwriting it.

---

## 1. What was found

### Root
| File | Notes |
| --- | --- |
| `README.md` | 2 lines: "# Tantrayukti Team 100X" / "YCCE-26 Nagpur~". Title lines must be kept. |
| `.gitattributes` | `* text=auto` LF normalisation only. |
| `.gitignore` | **Absent** — created in Phase 1. |
| `CFT-WORKFLOW.md`, `CLAUDE-plan.md` | The build instructions themselves (untracked plan docs). |

### `backend/`
| File | Notes |
| --- | --- |
| `pyproject.toml` | `uv`-style project, name `backend`, version `0.1.0`, `requires-python = ">=3.13"`, **`dependencies = []`** |
| `.python-version` | `3.13` |
| `main.py` | 5-line `print("Hello from backend!")` stub |
| `README.md` | Empty (0 bytes) |

**Framework found: none.** There is no Django, no FastAPI, no Flask, no Express — the backend is an
empty `uv` scaffold with zero dependencies. No settings module, no URL routing, no models, no
migrations, no tests, no entry point beyond the stub.

### `frontend/`
| File | Notes |
| --- | --- |
| `package.json` | name `frontend`, `type: module`. Scripts: `dev`, `build` (`tsc -b && vite build`), `lint` (`eslint .`), `preview` |
| `vite.config.ts` | `@vitejs/plugin-react` + `@rolldown/plugin-babel` with `reactCompilerPreset()` |
| `src/main.tsx` | `createRoot` → `<StrictMode><App /></StrictMode>` |
| `src/App.tsx` | 122 lines — the default Vite starter page (hero image, counter button, docs/social link cards) |
| `src/App.css`, `src/index.css` | 111-line starter stylesheet, plain CSS with CSS custom properties (`--accent: #aa3bff`), `color-scheme: light dark` |
| `src/assets/` | `hero.png`, `react.svg`, `vite.svg` |
| `public/` | `favicon.svg`, `icons.svg` |
| `tsconfig.json` + `tsconfig.app.json` + `tsconfig.node.json` | TypeScript project references |
| `eslint.config.js` | Flat config, `typescript-eslint` + react-hooks + react-refresh |
| `.gitignore` | Frontend-scoped, already present — left untouched |

**Framework found: React + Vite + TypeScript** — matches the plan's family, but see deviations below.

### Dependency versions present
`react` ^19.2.8 · `react-dom` ^19.2.8 · `vite` ^8.3.0 · `typescript` ~6.0.2 · `eslint` ^10.10.0 ·
`@vitejs/plugin-react` ^6.1.1 · `babel-plugin-react-compiler` ^1.0.0 · `@types/node` ^24.13.3

### Toolchain on this machine
`python 3.12.2` · `node v22.13.1` · `npm 10.9.2` · `uv 0.12.17` · git on branch `main`

---

## 2. How to run each side today

**Backend** — nothing to run; `python backend/main.py` prints `Hello from backend!`.
Dependency management is `uv` (`uv sync` / `uv run`), not `pip` + `requirements.txt`.

**Frontend**
```
cd frontend
npm install
npm run dev      # vite dev server
npm run build    # tsc -b && vite build
npm run lint     # eslint .
```

---

## 3. Existing features and routes

**None.** There is no router, no API client, no pages, no backend endpoints. `src/App.tsx` is the
unmodified Vite template. The repo is a fresh two-folder scaffold, not a partial implementation.

---

## 4. What is reusable

- `frontend/` Vite + TypeScript + ESLint + tsconfig project-reference setup — reuse as-is, add to it.
- `frontend/public/{favicon.svg,icons.svg}` and `src/assets/` — keep; may be replaced by EcoTrack branding later.
- `src/index.css` CSS custom properties — a usable colour seed when Tailwind is layered on.
- `backend/pyproject.toml` + `.python-version` — reuse as the dependency manifest rather than introducing a parallel `requirements.txt` as the source of truth.
- `.gitattributes` — keep.

---

## 5. Conflicts with `CLAUDE-plan.md`

| # | Conflict | Resolution (precedence rule: keep existing code) |
| --- | --- | --- |
| C1 | Plan says **React 18**; repo has **React 19.2** | **Resolved in Phase 3.** Kept React 19; react-router 7.18 installed and building cleanly against it. Recharts / Framer Motion / Leaflet are installed by the phases that need them. |
| C2 | Plan implies **JavaScript** (`.jsx`); repo is **TypeScript** (`.tsx`, `tsc -b` in the build) | **Resolved in Phase 3.** All new frontend files are `.ts`/`.tsx` and pass `tsc -b` under the repo's strict options (`verbatimModuleSyntax`, `erasableSyntaxOnly`, `noUnusedLocals`). |
| C3 | Plan says `requirements.txt`; repo uses **`uv` + `pyproject.toml`** | **Resolved in Phase 2.** `pyproject.toml` is the source of truth; `requirements.txt` is generated from it with `uv export` (command recorded in the file's header and in `backend/README.md`). |
| C4 | `backend/.python-version` pins **3.13**; local interpreter is **3.12.2** | **Resolved in Phase 2.** `.python-version` set to `3.12` and `requires-python` relaxed to `>=3.12`, matching the installed interpreter and keeping TensorFlow wheels available for Phase 11. |
| C5 | Plan's Check commands use bare `python manage.py …`; repo convention is `uv run` | Phase 2 will create a real `manage.py` so the plan's commands work verbatim; `uv run python manage.py …` remains the equivalent. |
| C6 | Plan's Phase 1 (`CFT-WORKFLOW.md` version) says "scaffold from empty repo" | `CLAUDE-plan.md` supersedes it — the repo is not empty. `CFT-WORKFLOW.md` is kept as the original reference only. |
| C7 | Plan names no styling layer in the repo; repo has **plain CSS**, no Tailwind | **Resolved in Phase 3.** Tailwind v4 added via `@tailwindcss/vite` with the theme in `src/styles/tailwind.css` (no `tailwind.config.js`). `App.css` is untouched; `index.css` was rescoped only (see C9). |
| C8 | `backend/main.py` stub has no role once Django exists | Leave the file in place (rule 9: never delete earlier work). Harmless. |
| C9 | `src/index.css` pinned `#root` to a fixed **1126px centred column** with `border-inline`, and styled bare `h1 / h2 / p / code` globally — incompatible with a dashboard shell | **Adapted in Phase 3.** Those rules are now nested under `.starter-shell` instead of `#root`. Every declaration was preserved verbatim; only the scope changed. The starter page keeps its exact appearance at `/welcome`, which applies the class. Justified by precedence rule 1: a fixed centred column contradicts the Mission's dashboard. The `:root` tokens and dark-mode block stay global and are reused by the EcoTrack theme. |

No conflict contradicts the Mission, so no phase is blocked by the above.

---

## 6. Open questions

- **Q1 — Python version. RESOLVED (Phase 2).** Applied the stated default: `.python-version` is now
  `3.12` and `requires-python` is `>=3.12`. `uv sync` built `backend/.venv` on CPython 3.12.2.
- **Q2 — Database.** No Postgres was detected. *Default:* SQLite via the plan's documented fallback;
  `DATABASE_URL` still honoured when present.
- **Q3 — External keys.** No Gemini / Whisper / Earth Engine credentials present. *Default:* mock
  extractors and the static NO2 CSV, flagged in the UI per the Fallbacks section.
- **Q4 — React 19 + React Compiler.** `babel-plugin-react-compiler` is enabled. If a charting or map
  library misbehaves under the compiler, the fallback is to drop the babel plugin from
  `vite.config.ts` rather than downgrade React.
- **Q5 — Two plan files.** `CLAUDE-plan.md` and `CFT-WORKFLOW.md` are near-identical and differ only
  in Phase 1 and the precedence list. Confirm `CLAUDE-plan.md` is authoritative (assumed yes).

---

## 7. Phase 1 changes to the repo

Created: `AUDIT.md`, `PROGRESS.md`, `BACKLOG.md`, root `.gitignore`, and `.gitkeep` placeholders for
the 22 missing layout folders.
Modified: `README.md` only (a "Project plan" section appended below the existing title lines).
Deleted / renamed: **nothing**.

---

## 8. Phase 2 changes to the repo

Created in `backend/`: `manage.py`, `config/{settings,urls,views,wsgi,asgi,tests}.py`,
`config/__init__.py`, `requirements.txt`, `.env.example`.
Modified in `backend/`: `pyproject.toml` (Django/DRF/CORS dependencies, `requires-python >=3.12`,
`[tool.uv] package = false`), `.python-version` (3.13 -> 3.12), `README.md` (was 0 bytes, now the
backend setup guide).
Deleted / renamed: **nothing** — `backend/main.py` is left in place, unused (conflict C8).
Untracked build output: `backend/.venv/`, `backend/db.sqlite3`, `backend/uv.lock` — the first two are
covered by `.gitignore`; `uv.lock` is intentionally committable for reproducible installs.

---

## 9. Phase 3 changes to the repo

Created in `frontend/`: `src/routes.tsx`, `src/vite-env.d.ts`, `src/styles/tailwind.css`,
`src/api/client.ts`, `src/hooks/useHealth.ts`,
`src/components/{AppLayout,ApiStatusBadge,PagePlaceholder}.tsx`,
`src/pages/{Dashboard,Spaces,Insights,Reports,Community,Profile,NotFound,Welcome}.tsx`,
`.env.example`.
Modified in `frontend/`: `package.json` + `package-lock.json` (react-router-dom 7.18.4,
tailwindcss 4.3.3, @tailwindcss/vite 4.3.3), `vite.config.ts` (Tailwind plugin + `/api` dev proxy to
`127.0.0.1:8000`), `src/main.tsx` (renders `RouterProvider`; imports the Tailwind entry stylesheet),
`src/index.css` (rescoped only — conflict C9).
Deleted / renamed: **nothing**. `src/App.tsx`, `src/App.css`, `src/assets/` and `public/` are
byte-for-byte unchanged; `App.tsx` is rendered by `src/pages/Welcome.tsx` at `/welcome`.

Verified beyond the phase's Check: `npm run lint` clean, every module transforms through Vite with
HTTP 200, the dev proxy returns the real health payload from Django, SPA deep links fall back
correctly, and the custom theme tokens appear in the production CSS bundle.

**Environment note.** The Vite dev server binds IPv6-only on this machine (`[::1]:5173`), so
`http://127.0.0.1:5173` will not connect — use `http://localhost:5173`. Port 5173 was already held by
another process during Phase 3, so verification ran on 5199; that process was left alone.

---

## 10. Phase 4 changes to the repo

Created in `backend/accounts/`: `__init__.py`, `apps.py`, `models.py`, `serializers.py`, `views.py`,
`urls.py`, `permissions.py`, `admin.py`, `migrations/{__init__,0001_initial}.py`,
`tests/{__init__,test_models,test_auth,test_permissions}.py`.
Modified in `backend/`: `pyproject.toml` + `requirements.txt` (djangorestframework-simplejwt 5.5.1),
`config/settings.py` (`AUTH_USER_MODEL`, accounts app, JWT as the default authentication class,
`SIMPLE_JWT` block), `config/urls.py` (mounted `/api/auth/`).

Created in `frontend/src/`: `api/tokens.ts`, `api/auth.ts`, `auth/context.ts`,
`auth/AuthContext.tsx`, `components/ProtectedRoute.tsx`, `pages/Login.tsx`.
Modified in `frontend/src/`: `api/client.ts` (attaches the bearer token, single refresh-and-retry on
401), `routes.tsx` (`/login` public, everything else behind `ProtectedRoute`), `main.tsx`
(`AuthProvider`), `components/AppLayout.tsx` (user menu and sign out).

Deleted / renamed: **nothing in version control**. The gitignored dev database `backend/db.sqlite3`
was recreated: swapping `AUTH_USER_MODEL` is incompatible with tables already built against
`auth.User`. It was verified to hold **0 users** first, so no data was lost. Re-create a login with
`uv run python manage.py createsuperuser`.

**Design note — roles are never trusted from the token.** The JWT carries a `role` claim so the UI can
render role-appropriate controls without a second request, but every permission class reads the role
from the database. A test asserts that a role change takes effect on an already-issued token.

---

## 11. Phase 5 changes to the repo

Created in `backend/spaces/`: `__init__.py`, `apps.py`, `models.py`, `serializers.py`, `views.py`,
`urls.py`, `admin.py`, `migrations/{__init__,0001_initial}.py`,
`management/commands/seed_spaces.py` (+ package `__init__` files),
`tests/{__init__,test_models,test_api,test_seed}.py`.
Modified in `backend/`: `config/settings.py` (registered `spaces`), `config/urls.py` (mounted
`/api/spaces/`).
Deleted / renamed: **nothing**.

**Design decisions worth carrying forward**

* *Area and occupancy resolve upwards.* `area_sqm` and `occupancy` are nullable on Building and
  Floor; `total_area_sqm` / `total_occupancy` return the stated value when present and otherwise the
  sum of children. A stated value therefore wins, so shared space such as corridors is not lost by
  summing rooms.
* *Unknown stays `None`, never `0`.* `_sum_area` returns `None` when no descendant states an area.
  Phase 16 normalises per m2, so this keeps "unknown" distinct from "zero" and prevents a
  divide-by-zero producing a fake comparison.
* *Scoping lives in `get_queryset`.* Every viewset filters to the caller's organisations, so a
  foreign object returns **404, not 403** — a forgotten object-level check cannot leak data through a
  detail route, a nested write or a query-param filter. Tests assert this for list, detail, filter
  and PATCH.
* *Creating an organisation grants the creator membership*, otherwise the new organisation would be
  invisible to the person who just made it.
* *`seed_spaces` never invents a password.* It attaches to an existing superuser when one exists; with
  no users at all it creates `seed-admin` with an **unusable** password and prints the
  `changepassword` command. Re-running is idempotent (`update_or_create` throughout).
* Building carries optional `latitude` / `longitude` for the Phase 22 community map; the seed values
  are Nagpur coordinates already rounded to city level.

---

## 12. Phase 6 changes to the repo

Created in `backend/telemetry/`: `__init__.py`, `apps.py`, `models.py`, `authentication.py`,
`serializers.py`, `views.py`, `urls.py`, `admin.py`, `migrations/{__init__,0001_initial}.py`,
`tests/{__init__,test_models,test_ingest,test_devices}.py`.
Modified in `backend/`: `config/settings.py` (registered `telemetry`), `config/urls.py` (mounted
`/api/` for `readings/` and `devices/`).
Deleted / renamed: **nothing**.

**Honesty note on device authentication (plan: "do not claim cryptographic verification").**
A device presents a random 32-byte secret as a bearer token. Only its SHA-256 hash is stored, and
comparison is constant-time. That proves *the caller knows the secret*; it does **not** verify a
signature over the reading, so it does not prove the values came from that hardware or were
unaltered by whoever holds the token. This limitation is written into
`telemetry/authentication.py` rather than glossed over, and payload signing is in `BACKLOG.md`.
Chosen over the plan's "signed device tokens" because a stored-hash random secret is individually
revocable, whereas a `SECRET_KEY`-derived signature is not.

**Units.** `active_power_w` is instantaneous watts; `energy_wh` is energy for *that interval only*,
never a cumulative meter total — Phase 8 sums it into kWh, so a cumulative value would be double
counted. `Reading.energy_kwh` exposes the conversion so no caller divides by 1000 by hand.

**Timezone consistency fix.** The `/status/` route builds its response as a plain dict, which
serialised datetimes as UTC, while DRF serializer fields render in the active timezone
(`Asia/Kolkata`). One API was emitting two offsets for the same instant. `local_iso()` now renders
hand-built responses the same way DRF does, and a test asserts the `/status/` and detail routes
report an identical `last_seen_at`.

**Idempotent ingestion.** `(device, timestamp)` is unique and inserts use `ignore_conflicts`, so a
device replaying its flash buffer after a failed upload cannot duplicate rows. Each batch is sorted
by timestamp before insert, so a backfill is written in sample order. The response returns
`created` / `duplicates` / `received` so firmware can trim its buffer with confidence.

---

## 13. Phase 7 changes to the repo

Created in `simulator/`: `profiles.py` (appliance catalogue and behaviours), `generator.py`
(time loop and fault injection), `api.py` (stdlib API client), `run.py` (CLI), `README.md`.
Modified at root: `.gitignore` (excludes `simulator/.tokens.json`, which holds live device
credentials).
Deleted / renamed: **nothing**.

**Stdlib only.** The simulator imports nothing outside the standard library, including for HTTP
(`urllib.request`). The phase's check runs `python simulator/run.py` from the repo root with the
system interpreter, which has no project dependencies installed, so any third-party import would
have broken it. `run.py` inserts its own directory on `sys.path`, so both
`python simulator/run.py` and `python -m simulator.run` work.

**Reproducibility is a requirement, not a nicety.** Each appliance gets an RNG seeded from
`seed:site:appliance`, so adding an appliance does not shift the numbers generated for the others.
Two runs with identical arguments produce byte-identical CSV, verified with `cmp`. Phase 13
evaluates anomaly detection against faults injected here, so data that moved between runs would
make precision/recall incomparable.

**Faults are labelled per sample.** The `fault` column records which fault was active. Faults start
60% of the way into a run, leaving clean history for a baseline. Verified label counts for a 10-day
office run with two faults: 17472 clean, 2112 `baseload-jump`, 384 `night-load`, 192 both.

**Mains plus appliances.** Each site emits one series per appliance *and* a `mains` series that is
their sum, because Phase 13 needs per-device series while Phase 23 NILM needs the aggregate. The
summary prints both totals so the sum always reconciles (verified identical to 2 dp).

**Electrical consistency.** Current is derived as `I = P / (V x pf)` rather than generated
independently, so every posted reading passes the Phase 6 server-side check that active power
cannot exceed apparent power.

**Two bugs found by verification beyond the phase check, both fixed:**

1. An empty, missing or malformed `--tokens` file raised an uncaught `JSONDecodeError` traceback.
   Now reported as a readable error via `read_token_file`, exit 1.
2. When every upload batch failed, the process still exited 0 — a scripted run would have believed
   the data landed. `post_series` now returns a failure count and the process exits 1.

---

## 14. Phase 8 changes to the repo

Created in `backend/telemetry/`: `rollups.py` (aggregation logic, framework-free enough to unit
test directly), `tests/test_rollups.py`.
Modified in `backend/telemetry/`: `views.py` (added `UsageView`), `urls.py` (mounted
`/api/usage/`).
Deleted / renamed: **nothing**. No migration was needed.

**The double-counting trap, and the guard against it.** A room can hold both a whole-space `mains`
meter and per-appliance meters covering the same load. Summing every device in a space therefore
reports roughly twice the real consumption, which would make Phase 9 cost estimates and Phase 16
comparisons wrong by a factor of two. `select_devices` resolves this explicitly:

* `auto` (default) - use `mains` meters when the scope has any, else sum `appliance` meters;
* `mains` / `appliance` - force one kind;
* `all` - sum everything, double counting included (debugging only).

Measured on the live seeded data: `auto`/`mains` report **13.85 kWh** from 3 devices, `appliance`
**13.69 kWh** from 12, and `all` **27.54 kWh** from 15 — very nearly double. Every response carries
`metering.requested`, `metering.applied`, `device_count` and `device_ids`, so a figure never appears
without saying how it was derived.

**Buckets are local-time.** `TruncHour`/`TruncDay`/`TruncMonth` use the active timezone
(`Asia/Kolkata`), so a "day" is a local day. A dedicated test stores readings at 23:30 and 00:30 IST
either side of midnight and asserts they land in *different* daily buckets — in UTC they would both
fall on the same day, smearing Phase 9 time-of-day tariffs and the Phase 13 night-load rule across
midnight.

**Gaps are not zero-filled.** A bucket with no readings is omitted rather than reported as 0 kWh,
because "consumed nothing" and "device was offline" are different facts and the UI must be able to
distinguish them.

**Bug found by live verification that the unit tests missed.** `?period=fortnight` returned **500**
instead of 400. The period was validated *after* `resolve_window` had already indexed
`DEFAULT_WINDOWS[period]`, which raises `KeyError` — but only on requests that omit `from`, and the
existing test always supplied an explicit window. Fixed by validating the period first and also
inside `resolve_window` (so the module is safe when used directly), plus three regression tests
including one that exercises every valid period with no window supplied. All eight malformed-input
cases now return 400 with an actionable message.

**Tests use real simulator data.** `SimulatorDataTests` imports the Phase 7 generator from the repo
root, stores a day of its output, and asserts the rollups reproduce the simulator's own energy and
peak-power totals, that 24 hourly buckets sum exactly to the daily bucket, and that `auto` metering
picks mains over the simulated appliances. The class skips with a clear reason if the simulator
cannot be imported, so a repo-layout change cannot silently break the suite.

---

## 15. Phase 9 changes to the repo

Created in `backend/billing/`: `models.py`, `engines.py`, `serializers.py`, `views.py`, `urls.py`,
`admin.py`, `apps.py`, `migrations/0001_initial.py`,
`management/commands/seed_tariffs.py`, `tests/{test_cost,test_co2,test_api}.py` (+ package
`__init__` files).
Created in `backend/config/`: `encoders.py`.
Modified in `backend/config/`: `settings.py` (registered `billing`; installed the decimal-safe
renderer), `urls.py` (mounted `/api/billing/`).
Deleted / renamed: **nothing**.

**Precision bug found by the tests and fixed project-wide.** DRF's JSON encoder converts `Decimal`
with `float(obj)`, so the API was emitting the emission factor `0.82` as
`0.81999999999999995115...`, and every rupee and kWh figure in a hand-built response was similarly
lossy. It also made hand-built responses inconsistent with serializer-built ones, since DRF's
`DecimalField` already renders decimals as exact strings. `config/encoders.py` adds
`DecimalStringJSONRenderer`, now the project's default renderer, which emits every `Decimal` as a
string. This is the same class of defect as the Phase 6 timezone inconsistency: one API reporting
the same quantity two different ways depending on which code path built the response. It affects
the Phase 8 rollup output too, which previously returned float energy values.

**How slabs and time-of-use combine.** Indian slab tariffs are cumulative over a billing month, so
the engine applies slabs to the monthly total first, derives the blended effective rate
(`energy charge / total kWh`), then applies time-of-day as
`units_in_window x effective_rate x (multiplier - 1)`. A multiplier of 1.0 therefore contributes
exactly nothing, and the adjustment stays proportional to what the customer actually pays per unit.
Time-of-day windows are multipliers rather than absolute rates because Indian ToD tariffs are
expressed as a percentage surcharge or rebate.

**Windows use local hours and may wrap midnight**, so off-peak 22:00-06:00 is one row.
A regression test stores a reading at 19:30 IST (14:00 UTC) and asserts it attracts the evening
peak surcharge - reading the UTC hour would have placed it in the afternoon window and silently
lost the charge.

**Honesty measures, as the plan requires.**

* Every seeded rate has `is_sample=True` and a `source` beginning "ILLUSTRATIVE SAMPLE RATES - not
  an actual utility tariff", and both travel with every estimate.
* The 0.82 kg CO2/kWh default is `is_verified=False`, and its `source` says it is static, unverified,
  and should be checked against the CEA CO2 Baseline Database. A test asserts the source text names
  the value, names CEA and says "static".
* With no `EmissionFactor` row at all, the engine uses the documented default and sets
  `is_fallback=True` rather than silently substituting a number.
* With no tariff configured, the bill is zero with a note saying why - it never invents a rate.
* Time-of-day rates present but no hourly data supplied produces a note, not a silent omission.
* The month projection is explicitly naive (mean daily rate held flat) and lists four assumptions
  including "No seasonal, weekday or weather adjustment is applied."

**Billing reuses the Phase 8 metering guard**, so a room carrying both a mains meter and appliance
meters is not billed twice. Verified by test: the same fixture bills 2000 INR under `auto` (250 kWh
from mains) and 5500 INR under `metering=all` (500 kWh double counted).

Every bill is returned as auditable lines - per-slab units and a `formula` string, per-window
time-of-day adjustments, fixed charge, tax, effective rate - because Phase 15 must show the formula
behind a claimed saving and Phase 19 the formula behind a bill.

---

## 16. Phase 10 changes to the repo

Created in `backend/ml/`: `__init__.py`, `data/{__init__,sources,clean,synthetic,prepare}.py`,
`data/README.md`, `tests/{__init__,test_data}.py`, plus empty `training/__init__.py` and
`evaluation/__init__.py` for the next phases.
Modified in `backend/`: `pyproject.toml` (new `[ml]` extra: pandas 3.0.6, numpy 2.5.3),
`requirements.txt` (regenerated with the `ml` extra).
Deleted / renamed: **nothing**. No migration, no Django app - `ml/` is a plain package.

**Dependencies are an optional extra.** pandas and numpy live in a `[project.optional-dependencies]`
group named `ml`, so a deployment that only serves the API can install the base set and skip ~100 MB
of numerical libraries. Install with `uv sync --extra ml`.

**The UCI download succeeded, so the processed household series is real measured data.**
120,000 raw 1-minute rows reduced to 1,999 complete hourly rows (8 rows missing active power,
2 incomplete hours dropped). Both the raw and processed directories were already covered by
`.gitignore`, verified with `git check-ignore`.

**Both fallback paths were exercised, not just written.** `--synthetic` and a simulated download
failure (unreachable URL with the cached file hidden) each produced a complete synthetic dataset,
flagged `is_synthetic=1` on every row, with the failure reason recorded in the provenance sidecar
and a `NOTE:` printed to stdout. Neither path retries or blocks.

**The kW/kWh boundary, which is the whole reason this module exists.** The UCI file records
`Global_active_power` in **kilowatts** sampled per minute while `Sub_metering_*` records **watt-hours
per minute** - two different unit families in one file. Averaging kilowatts over an hour yields
kilowatts, not kilowatt-hours. Every processed column is therefore named for its unit
(`energy_kwh`, `mean_power_kw`, `peak_power_kw`), and a test pins that a constant 2 kW draw for one
hour is 2 kWh. Over a one-hour window `energy_kwh` and `mean_power_kw` are numerically equal, which
is exactly why they need distinct names: the equality is an artefact of the window length, not an
identity.

**Decisions that protect every downstream metric:**

* *The target is dropped, never imputed.* Rows with no `Global_active_power` are discarded, because
  filling the forecasting target would fabricate the label the model is scored against.
* *Incomplete hours are dropped, not scaled.* An hour holding 12 of its 60 minutes would contribute
  a fifth of its real energy and bias the model; the threshold is 80% coverage and the number
  dropped is reported.
* *The split is chronological, never random.* `time_ordered_split` is 70/15/15 by time. A random
  split on a time series leaks the future into training and yields scores that cannot be reproduced
  in production.
* *Hour and month are also sine/cosine encoded*, so hour 23 and hour 0 are adjacent rather than 23
  units apart. A test asserts the encoded distance is small.

**The emission-factor series is always synthetic, and says so everywhere.** No public hourly CO2
intensity series for the Indian grid is downloaded by this project, so there is nothing real to fall
back to - which is why the labelling is non-negotiable rather than a nicety. The generator encodes
three real mechanisms (coal baseload overnight, solar dilution at midday, evening peakers) plus a
load-driven term, producing a mean of 0.831 kg CO2/kWh with the cleanest hour at 12:00 and the
dirtiest at 19:00 - straddling the Phase 9 static 0.82 default so the modelled option stays
comparable to it. The provenance says plainly: "A model trained on this learns the generator's
assumptions, not the grid. Phase 12 metrics must say so."

**Provenance sidecars.** Every processed file gets `<file>.provenance.json` recording source,
licence, units, row count, date range, `is_synthetic`, and what cleaning removed. This is the
upstream half of the plan's honesty rule: a metric is only as trustworthy as the provenance of the
data behind it.

---

## 17. Phases 11-20

Run as one batch at the user's request, rather than one phase per run. Every phase's Check was still
executed; the results are in `PROGRESS.md`.

### The TensorFlow fallback, and why metrics.json says "fallback"

`uv sync --extra deep` failed twice. The second attempt failed inside uv after its own 5 retries
with a DNS error on `files.pythonhosted.org` while fetching the 335 MB `tensorflow-2.21.0` wheel - a
genuine network failure, not a timeout of ours. Per the plan's rule 5 (one attempt, then the
fallback) the pipeline took the documented path.

`ml/training/backends.py` therefore ships two backends behind one interface:

* `KerasLstmBackend` - the stacked LSTM the plan specifies (128, 64, dropout 0.2), used whenever
  Keras imports.
* `SklearnMlpBackend` - an MLP over the flattened lookback window, used otherwise.

**The fallback is never silently substituted.** `select_backend` reports which was chosen and why;
the choice is written into the model manifest; `metrics.json` carries `backend` and `is_fallback`
beside every score; the `/api/forecast/` response repeats it; and the dashboard and metrics page
both print "fallback model, not the specified LSTM". Install it later with
`uv sync --extra ml --extra deep` and re-run the two training commands - no code changes needed.

**A note on the forecast numbers.** The trained fallback scores MAE 0.765 kWh, MAPE 158.8% and
**R2 -0.044** one-step (MAE 0.964 / R2 -0.540 over the recursive 24 h horizon). It beats the
seasonal naive baseline on MAE by 16% but is worse than predicting the test mean on R2. That is
reported as-is: the plan forbids re-training to chase a better score, so nothing was tuned. The
likely causes (fallback architecture, 5 epochs, about 2000 hours of a single noisy household) are
recorded in `BACKLOG.md` rather than papered over.

### Bugs found and fixed during these phases

1. **`Dataset.n_features` included the target column**, so `inverse_target` was called with a width
   one greater than the scaler's and crashed the evaluation. Renamed to `n_columns` with
   `n_exogenous_features` alongside, which is what invited the off-by-one in the first place.
2. **The Isolation Forest threshold was a fixed fraction in disguise.** The module docstring claimed
   it avoided the plan's `contamination` trap while using the 1st percentile of the score
   distribution - which is always 1% of the data. Its own test caught it by flagging anomalies in a
   clean week. Now a point must be an outlier by the forest's own `contamination="auto"` offset
   **and** clear a robust magnitude fence.
3. **The magnitude fence was global**, which is wrong for a bimodal load: an office runs about 6 kW
   on weekday afternoons and near zero at weekends, so the whole-series median sat low and every
   normal weekday peak cleared the fence - 19.3% of hours flagged on 14 clean simulated days. The
   fence is now per hour-of-day and day-type.
4. **Mean/standard-deviation baselines let a spike mask itself.** One 12 kWh outlier among ten 1 kWh
   hours raises the standard deviation enough that the spike scores under 3 sigma and goes
   undetected. `robust_stats` now uses the median and a MAD-derived sigma.
5. **"Device left on" fired on every normal evening peak**, because it compared against the global
   median. It now compares each hour against its own hour-of-day baseline.
6. **`ActivityEntry.formula` rendered differently before and after a database reload**
   (`Decimal("100")` vs `Decimal("100.000")`). The quantity is now quantized in the property.
7. **The failed TensorFlow sync left the venv without numpy**, which broke `manage.py check`.
   Restored with `uv sync --extra postgres --extra ml`. Worth knowing: a partially-failed `uv sync`
   can remove packages it had resolved away.

### Anomaly detection, scored against real labels

`insights/tests/test_anomaly.py::SimulatorFaultEvaluationTests` runs the Phase 7 simulator with
faults injected, scores the detectors against the simulator's own per-sample fault labels, and
writes the result into `metrics.json`:

| scenario | precision | recall | F1 |
| --- | --- | --- | --- |
| night_load | 1.000 | 1.000 | 1.000 |
| ac_left_on | 0.984 | 0.741 | 0.846 |
| baseload_jump | 0.984 | 0.448 | 0.615 |

Baseload-jump recall is low **by design** - it reports one finding for a multi-day condition, so
most faulty hours are counted as misses. That is stated in the metrics caveats rather than hidden by
changing the scoring.

### Chart work (Phases 17-19)

The `dataviz` skill was loaded before any chart code was written, and its palette validator was run
against this project's own surfaces rather than the skill's defaults:

* light `#ffffff`: CVD dE 9.2, normal-vision dE 24.0 - all checks pass
* dark `#1e293b`: CVD dE 9.4, normal-vision dE 20.9 - all checks pass

Light-mode series-3 sits at 2.82:1 contrast, below the 3:1 gate, so the palette's **relief rule**
applies: `ChartFrame` always renders a legend for two or more series and always offers a table view
of the same numbers. Three categorical slots is the documented cap for all-pairs forms, so a fourth
series would fold into `other` rather than inventing a hue. Power (W) and energy (kWh) are never put
on one axis - that is both the dual-axis anti-pattern and the kW/kWh confusion this project forbids.

### Honesty measures added in this batch

* `metrics.json` is the only source of every metric in the UI; `/api/ml/metrics/` serves the file
  verbatim and the metrics page narrows it rather than restating it.
* Recommendations return the formula, the assumptions, the assumed capital cost and the caveat that
  the figure is an estimate rather than a measured saving.
* Causes are ranked by deterministic rules over recorded evidence; the optional LLM flag may only
  reword, and the response says whether it was used.
* Space comparison excludes spaces with no area or occupancy and lists them, rather than ranking
  them on raw energy and calling the biggest space a finding.
* Activity entries are always `is_verified=False`, with the factor snapshotted per entry so a later
  correction cannot rewrite history, and all 23 seeded factors are flagged UNVERIFIED with a source.
* The demo fault injector tags every reading it writes `source=simulator`.

---

## 18. Phases 21-25

Run as one batch at the user's request. Every phase's Check was executed.

### Phase 21: the verified/unverified split is structural

`Profile` keeps two parallel tallies - `verified_xp` / `verified_kwh_saved` and
`unverified_xp` - rather than one column and a filter. The leaderboard orders on
verified XP only, levels derive from verified XP only, and badges carry
`requires_verified`. A test awards 1,000,000 unverified XP and asserts the ranking
does not move.

Proof of saving normalises for window length before subtracting: a 48 h baseline
against a 24 h claim window would otherwise show a 50% saving from arithmetic
alone, and a test pins that case at zero. XP is credited from the **measured**
saving, so over-claiming earns nothing extra. Too little telemetry yields
`unverifiable`, not `rejected` - "we cannot tell" and "it did not happen" are
different answers.

### Phase 22: units and privacy

NO2 is stored and served as **umol/m2 of tropospheric column**. No ppb or ug/m3
conversion exists anywhere in the codebase, and a test asserts no response field
name contains "ppb", "ug_per_m3" or "surface". Converting a column to a surface
concentration needs a vertical profile and boundary-layer height that this project
does not model.

Coordinates are rounded to 3 decimal places (~100 m) **in `save()`**, so the
precise value is never persisted rather than merely never rendered.

Hotspot detection repeats the Phase 13 lesson: with only 20 cities, a fixed
`contamination` or a percentile cutoff would label a fixed number of them
regardless of the data. Detection requires the forest's own `contamination="auto"`
outlier flag **and** a robust fence (`median + 1.5 x MAD-sigma`). A test with 12
similar cities asserts zero hotspots. On the seeded data it flags 3 of 20 (Delhi,
Ghaziabad, Noida) above 163.01 umol/m2.

### Phase 23: declining beats fabricating

The text extractor parses with regular expressions and reports only what it
matched. The image and audio extractors **decline** with a reason and
`confidence=0.0`, and the endpoint returns 422. A mock emitting a plausible
reading for a photo it cannot see would put fabricated data into the database,
which is worse than refusing - and a test asserts the refusal message says so.

Chat energy is **spread across intervals** rather than stored as one reading. A
single large value at one timestamp is exactly the spike the Phase 13 detector
exists to catch, so storing it that way would manufacture an anomaly. Rows are
tagged `source=import`.

NILM is the step-change fallback the plan specifies, with `metrics.status =
"not evaluated"`: UK-DALE is not downloaded, so there are no appliance labels and
no precision or F1 can be computed. The run also revealed **over-attribution** -
events accounted for 114.6% of metered energy, because overlapping appliances
produce combined steps - so `over_attribution_caveats` now states that in the
manifest rather than leaving a reader to assume a bug. A CNN+LSTM trainer is
deliberately omitted: with no labels its output could not be checked.

### Phase 24: firmware, unbuilt and said so

PlatformIO is not installed here, so `pio run` was **not** executed; the phase
instructions permit skipping the build and saying so, and both `firmware/README.md`
and the README state it.

The firmware uses EmonLib's `realPower` rather than `Vrms * Irms`, because
apparent power overstates a reactive load. The server's "active power cannot
exceed apparent power" check then catches a mis-wired clamp. `energy_wh` is
interval energy, never a running total.

It reports `"calibrated": false` and tags uploads `1.0.0-uncalibrated` until
`CALIBRATION_CONFIRMED` is set, because an uncalibrated meter produces confident
wrong numbers. Readings are queued to NVS **first** and only dropped once the
server acknowledges them, so a POST that hangs past the next interval loses
nothing. A 400/422 drops the batch rather than wedging the queue forever.

### Phase 25: the generated document

`docs/ML_EVALUATION.md` is written by `ml/evaluation/report.py` from
`metrics.json`. That is the mechanism behind the honesty rule: a figure in the
docs came out of evaluation code, and a model marked "not evaluated" appears as
such rather than being quietly omitted. CI regenerates it and uploads it as an
artifact.

CI also fails on a missing migration (`makemigrations --check`), because a model
change without a migration passes the tests and then breaks a deploy. The
`[deep]` extra is deliberately omitted from CI - it is a 335 MB download and the
code falls back to a labelled model without it.

Compose publishes only the frontend; the database and backend are reachable only
on the internal network, and nginx proxies `/api` so the browser sees one origin
and CORS never applies. The `ml-artifacts` volume persists `metrics.json` across
rebuilds, since losing it would blank the metrics page.

### Final check

* `docker compose config` - **valid**
* `python manage.py check` - 0 issues
* `python manage.py test` - **597 tests, OK**
* `npm run lint` - clean
* `npm run build` - clean
* `python simulator/run.py --days 7 --dry-run` - passes

All 25 rows in `PROGRESS.md` are `DONE`. Nothing in version control was deleted
or renamed across the whole build, and the pre-existing starter files
(`frontend/src/App.tsx`, `App.css`, `src/assets/`, `public/`) remain
byte-for-byte unchanged.

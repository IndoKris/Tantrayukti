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

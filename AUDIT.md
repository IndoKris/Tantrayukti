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
| C1 | Plan says **React 18**; repo has **React 19.2** | **Keep React 19.** Newer, working, and not a different framework. Recharts / Framer Motion / Leaflet / react-router all support React 19. |
| C2 | Plan implies **JavaScript** (`.jsx`); repo is **TypeScript** (`.tsx`, `tsc -b` in the build) | **Keep TypeScript.** All new frontend files will be `.ts`/`.tsx`. |
| C3 | Plan says `requirements.txt`; repo uses **`uv` + `pyproject.toml`** | **Resolved in Phase 2.** `pyproject.toml` is the source of truth; `requirements.txt` is generated from it with `uv export` (command recorded in the file's header and in `backend/README.md`). |
| C4 | `backend/.python-version` pins **3.13**; local interpreter is **3.12.2** | **Resolved in Phase 2.** `.python-version` set to `3.12` and `requires-python` relaxed to `>=3.12`, matching the installed interpreter and keeping TensorFlow wheels available for Phase 11. |
| C5 | Plan's Check commands use bare `python manage.py …`; repo convention is `uv run` | Phase 2 will create a real `manage.py` so the plan's commands work verbatim; `uv run python manage.py …` remains the equivalent. |
| C6 | Plan's Phase 1 (`CFT-WORKFLOW.md` version) says "scaffold from empty repo" | `CLAUDE-plan.md` supersedes it — the repo is not empty. `CFT-WORKFLOW.md` is kept as the original reference only. |
| C7 | Plan names no styling layer in the repo; repo has **plain CSS**, no Tailwind | Add Tailwind in Phase 3 **alongside** the existing CSS; do not delete `App.css` / `index.css`. |
| C8 | `backend/main.py` stub has no role once Django exists | Leave the file in place (rule 9: never delete earlier work). Harmless. |

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

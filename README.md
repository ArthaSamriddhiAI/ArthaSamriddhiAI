# Samriddhi AI

Portfolio Operating System for Indian wealth advisors — Evidence,
Governance, Accountability.

> **Convention:** Mac/Linux commands are shown by default. Windows
> equivalents (PowerShell) are inline under each step, marked
> **🪟 Windows**. WSL2 users: stick with the Mac/Linux commands.

---

## ⚡ Quick start (TL;DR)

Already have Python 3.12+ and Node 20+? Copy-paste this and you're
running in two minutes:

### Mac / Linux

```bash
# Terminal 1 — backend
git clone https://github.com/ArthaSamriddhiAI/ArthaSamriddhiAI.git
cd ArthaSamriddhiAI
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cat > .env <<'EOF'
JWT_SECRET=local-dev-jwt-secret-must-be-at-least-32-bytes-long
SAMRIDDHI_FIXTURE_AUTO_LOAD=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true
EOF
alembic upgrade head
uvicorn artha.app:app --reload
```

```bash
# Terminal 2 — frontend
cd ArthaSamriddhiAI/web
npm install
npm run dev
```

### 🪟 Windows (PowerShell)

```powershell
# Terminal 1 — backend
git clone https://github.com/ArthaSamriddhiAI/ArthaSamriddhiAI.git
cd ArthaSamriddhiAI
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
@"
JWT_SECRET=local-dev-jwt-secret-must-be-at-least-32-bytes-long
SAMRIDDHI_FIXTURE_AUTO_LOAD=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true
"@ | Out-File -FilePath .env -Encoding utf8
alembic upgrade head
uvicorn artha.app:app --reload
```

```powershell
# Terminal 2 — frontend
cd ArthaSamriddhiAI\web
npm install
npm run dev
```

> **PowerShell first-time:** if `Activate.ps1` is blocked, run once
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
> and try again.

Open <http://127.0.0.1:5173/app> → log in as `cio1` (no password) → done.

The first backend boot takes ~10–15 seconds while the JSONFixtureAdapter
ingests the 12 MB fixture (3024 instruments + 1 macro snapshot + 14
industry reports + ~70 default model portfolio entries). Subsequent
restarts are fast.

---

## Prerequisites

- **Python 3.12+** — `python3 --version` (Mac/Linux) /
  `python --version` (Windows)
- **Node.js 20+** + npm — `node --version`
- **Git** — `git --version`

If you're missing any:

| | Mac (Homebrew) | Windows |
|---|---|---|
| Python | `brew install python@3.12` | <https://www.python.org/downloads/> (check "Add Python to PATH") |
| Node | `brew install node` | <https://nodejs.org/> (LTS installer) |
| Git | comes with Xcode CLT | <https://git-scm.com/download/win> |

---

## Step-by-step walkthrough

If the quick-start above didn't work for you, here's the same setup with
explanations.

### 1. Clone + venv

```bash
# Mac / Linux
git clone https://github.com/ArthaSamriddhiAI/ArthaSamriddhiAI.git
cd ArthaSamriddhiAI

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

```powershell
# 🪟 Windows (PowerShell)
git clone https://github.com/ArthaSamriddhiAI/ArthaSamriddhiAI.git
cd ArthaSamriddhiAI

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

The `pip install -e .` reads `pyproject.toml` and installs Samriddhi in
editable mode along with FastAPI, SQLAlchemy, Pydantic, etc.

> **🪟 Windows note:** every new terminal needs the venv re-activated
> via `.venv\Scripts\Activate.ps1`. If you're using `cmd.exe` instead
> of PowerShell, use `.venv\Scripts\activate.bat`.

### 2. Apply DB migrations

The default DB is SQLite at `./artha.db` — no Postgres required for dev.

```bash
# both platforms (venv must be active)
alembic upgrade head
```

You'll see ~10 migrations chain through (cluster 0 → cluster 4). The
`artha.db` file appears in the repo root.

### 3. Configure env vars

Create a `.env` in the repo root with these values:

```ini
# JWT signing key — required (any random string ≥32 bytes)
JWT_SECRET=local-dev-jwt-secret-must-be-at-least-32-bytes-long

# Cluster 3 addendum: auto-load the master data fixture on startup
SAMRIDDHI_FIXTURE_AUTO_LOAD=true

# Cluster 4: auto-tag instruments + load the default model portfolio
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true

# Optional — bumps log verbosity
LOG_LEVEL=INFO
```

**Mac/Linux** — heredoc copy-paste:

```bash
cat > .env <<'EOF'
JWT_SECRET=local-dev-jwt-secret-must-be-at-least-32-bytes-long
SAMRIDDHI_FIXTURE_AUTO_LOAD=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true
EOF
```

**🪟 Windows** — PowerShell here-string:

```powershell
@"
JWT_SECRET=local-dev-jwt-secret-must-be-at-least-32-bytes-long
SAMRIDDHI_FIXTURE_AUTO_LOAD=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true
"@ | Out-File -FilePath .env -Encoding utf8
```

The first run with auto-load on takes ~10–15 seconds while the
JSONFixtureAdapter ingests the 12 MB fixture. Subsequent restarts are
fast (idempotent re-runs are mostly UPDATEs).

### 4. Run the backend

```bash
# Terminal 1, from repo root, venv active — same on both platforms
uvicorn artha.app:app --reload --host 127.0.0.1 --port 8000
```

You should see logs like:

```
INFO  Cluster 3 addendum auto-load: status=success, instruments=3024,
      macro=1, industry=14, errors=0
INFO  Application startup complete.
```

Check it works:

- API health: <http://127.0.0.1:8000/api/v1/health>
- OpenAPI docs: <http://127.0.0.1:8000/docs>

### 5. Run the frontend

```bash
# Terminal 2, separate shell — same on both platforms
cd web
npm install
npm run dev
```

Vite serves on <http://127.0.0.1:5173/app>. The dev server proxies
`/api/*` to the backend on port 8000, so both must be running.

### 6. Log in (dev mode)

Open <http://127.0.0.1:5173/app> in your browser. You'll be redirected
to `/app/dev-login`. Pick any of the 4 demo users:

| `user_id` | Role | What they see |
|---|---|---|
| `advisor1` | advisor | Investor list, mandates, conversational onboarding, model portfolio (read-only) |
| `cio1` | cio | LLM router settings, mandate amendments queue, model portfolio editing |
| `compliance1` | compliance | Read access to admin surfaces (no writes) |
| `audit1` | audit | Full audit console: adapters, snapshots, freshness, all browsers (read + write) |

No password — dev-mode auth is keyed only on `user_id`. (See
`dev/test_users.yaml` for the catalogue.)

---

## Common ops

### Mac / Linux

```bash
# Run the api_v2 test suite
.venv/bin/python -m pytest tests/test_unit/ -k api_v2 -q

# Lint backend
.venv/bin/ruff check src/artha tests

# Build frontend for production-style preview
cd web && npm run build && npm run preview

# Reset the database (wipe all state)
rm artha.db && alembic upgrade head
# Then restart the backend — auto-load reseeds the fixture.

# Peek at the catalogue without the UI
sqlite3 artha.db "SELECT vehicle_type, COUNT(*) FROM v2_instruments GROUP BY vehicle_type;"
```

### 🪟 Windows (PowerShell)

```powershell
# Run the api_v2 test suite
.venv\Scripts\python -m pytest tests\test_unit\ -k api_v2 -q

# Lint backend
.venv\Scripts\ruff check src\artha tests

# Build frontend for production-style preview
cd web; npm run build; npm run preview

# Reset the database (wipe all state)
Remove-Item artha.db; alembic upgrade head
# Then restart the backend — auto-load reseeds the fixture.

# Peek at the catalogue without the UI (requires sqlite3.exe on PATH;
# install via `winget install SQLite.SQLite` or skip this one)
sqlite3 artha.db "SELECT vehicle_type, COUNT(*) FROM v2_instruments GROUP BY vehicle_type;"
```

---

## Troubleshooting

**Backend startup hangs on first run.** That's the JSONFixtureAdapter
ingesting 3000+ instruments. Watch the log; it usually completes in
10–15 seconds. If it stays silent for >60 seconds, kill + restart with
`SAMRIDDHI_FIXTURE_AUTO_LOAD=false` and run the adapter manually from
`/app/audit/adapters` after you log in.

**Frontend shows "Auth required" on every page.** The JWT secret got
rotated between runs (this happens if `JWT_SECRET` isn't set — a random
secret is generated at startup). Set `JWT_SECRET` in `.env` to a stable
value and the cookie persists across restarts.

**`alembic upgrade head` fails with import error.** You're not in the
venv.

- Mac/Linux: `source .venv/bin/activate`
- Windows: `.venv\Scripts\Activate.ps1`

…and try again.

**`pip install -e .` complains about Python version.** Samriddhi
requires Python 3.12+. Check `python3 --version` (Mac) /
`python --version` (Windows). If it's older:

- Mac (pyenv): `brew install pyenv && pyenv install 3.12 && pyenv local 3.12`
- Windows: install from <https://www.python.org/downloads/> and re-open
  the terminal so the new `python` is on PATH.

**🪟 PowerShell: `Activate.ps1 cannot be loaded because running scripts
is disabled`.** Run once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then `.venv\Scripts\Activate.ps1` works in every future shell.

**Port 8000 / 5173 already in use.** Pick a different port:

```bash
uvicorn artha.app:app --port 8001
# and
cd web && npm run dev -- --port 5174
```

If you change the backend port, update the proxy target in
`web/vite.config.ts` to match.

**Want to skip the fixture load entirely.** Set
`SAMRIDDHI_FIXTURE_AUTO_LOAD=false` in `.env`. The backend starts in
under a second with empty canonical-entity tables; advisor + CIO
surfaces will show "no data" but mandate / investor flows still work.

**🪟 Windows: line endings on `.env` cause weird parsing.** If env vars
read as garbage (e.g. `JWT_SECRET=...\r`), make sure the file is saved
LF, not CRLF. The `Out-File -Encoding utf8` step in §3 emits UTF-8 with
BOM which works; if you hand-edit the file in Notepad, switch to
"Save as → UTF-8 (no BOM)" or use VS Code's CRLF→LF toggle.

---

## Indicative master data fixture

The repo ships with a 12 MB indicative master data fixture at
`data/fixtures/SamriddhiAI_data_merged.json`. The JSONFixtureAdapter
loads this on startup (when `SAMRIDDHI_FIXTURE_AUTO_LOAD=true`),
populating the canonical entity tables with 500 listed equities + 1773
SEBI-categorised mutual fund schemes + 513 PMS funds + 162 AIF
profiles + 100 unlisted equity companies + 1 macro snapshot + 14 RBI /
industry reports.

Cluster 4 layers a hand-curated default model portfolio over this
universe (~70 entries across the 9-cell client-profile matrix), loaded
from `data/fixtures/default_model_portfolio.json`.

Both fixtures are stand-ins for actual data feeds; live adapters arrive
in cluster 17. See `data/fixtures/README.md` for fixture-specific
details (contents, effective dates, refresh procedure, known
limitations).

---

## Documentation

- `data/fixtures/README.md` — fixture-specific details
- `docs/doc1_v2/` — foundation reference + chunk plans
- `DEMO_GUIDE.md` — operating the deployed (production) system for demos

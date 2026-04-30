# Samriddhi AI — Local Quickstart

Everything you need to run, test, and debug the system without asking Claude.

---

## TL;DR (5 lines)

```bash
cd "<repo-root>"            # this directory
source .venv/bin/activate   # activate the virtualenv (Mac/Linux)
.venv\Scripts\activate      # Windows PowerShell
uvicorn artha.app:create_app --factory --reload --port 8000
# → http://127.0.0.1:8000/docs
```

---

## 1. One-time setup

You only do this once per fresh clone (or after deleting `.venv/`).

### Mac / Linux

```bash
cd "<repo-root>"
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"      # installs runtime + dev deps from pyproject.toml
```

### Windows (PowerShell)

```powershell
cd "<repo-root>"
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[dev]"
```

If PowerShell blocks the activate script:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
(say yes, then re-run `Activate.ps1`)

### Optional: create a `.env` file

Default config is `MOCK` LLM provider + local SQLite — works out of the box. Only create `.env` if you want to override defaults. Example:

```bash
# .env (place in repo root, never commit)
DATABASE_URL=sqlite+aiosqlite:///./artha.db
DEFAULT_LLM_PROVIDER=mock
LOG_LEVEL=INFO
ENVIRONMENT=development

# Only needed if you swap providers:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# MISTRAL_API_KEY=...
```

`.env` is already in `.gitignore` — safe to keep secrets here.

---

## 2. Start the API server

### Foreground (you watch the logs)

```bash
source .venv/bin/activate              # or: .venv\Scripts\activate on Windows
uvicorn artha.app:create_app --factory --reload --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive Swagger UI. Hit `Ctrl+C` to stop.

`--reload` auto-restarts the server when you save a `.py` file. Drop it in production.

### Background (for long-running sessions)

```bash
nohup uvicorn artha.app:create_app --factory --port 8000 > /tmp/samriddhi.log 2>&1 &
echo $! > /tmp/samriddhi.pid
```

Stop it later:
```bash
kill $(cat /tmp/samriddhi.pid)
```

### Different port

```bash
uvicorn artha.app:create_app --factory --port 9000
```

---

## 3. Run the tests

```bash
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_unit/ -q              # quiet, ~1 second
.venv/bin/python -m pytest tests/test_unit/ -v              # verbose
.venv/bin/python -m pytest tests/test_unit/test_t1_ledger.py # one file
.venv/bin/python -m pytest -k "test_test_5" -v              # by name pattern
```

Expected: **808 passed** (as of Pass 20).

### Run lint

```bash
.venv/bin/python -m ruff check src/artha/ tests/test_unit/   # report only
.venv/bin/python -m ruff check --fix src/artha/ tests/test_unit/  # auto-fix
```

---

## 4. Database

Default is local SQLite at `./artha.db` — created automatically on first run, gitignored. To wipe and start fresh:

```bash
rm artha.db                  # Mac/Linux
del artha.db                 # Windows
```

The schema is created from `Base.metadata` at app startup (no migration needed for local dev).

### Production-style migrations (Alembic)

Only relevant if you point at a real Postgres:

```bash
ARTHA_DATABASE_URL="postgresql+asyncpg://user:pass@host/db" \
  alembic upgrade head
```

For local SQLite dev you can ignore Alembic entirely.

---

## 5. Common problems

### "command not found: uvicorn" / "command not found: pytest"
You forgot to activate the venv. Run `source .venv/bin/activate` (Mac/Linux) or `.venv\Scripts\activate` (Windows). Confirm with `which python` — it should point to `.venv/bin/python`.

### "ModuleNotFoundError: No module named 'artha'"
Either:
- venv not activated (see above), OR
- you didn't run `pip install -e ".[dev]"` (the `-e` is what makes `artha` importable)

Fix:
```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

### "Address already in use" / port 8000 busy
Either kill the existing process or use a different port:
```bash
lsof -i :8000               # Mac/Linux: find the PID
kill <PID>
# OR
uvicorn artha.app:create_app --factory --port 8001
```

Windows:
```powershell
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
Stop-Process -Id <PID>
```

### "sqlite3.OperationalError: no such table"
The DB file got out of sync with the schema. Easiest fix in dev:
```bash
rm artha.db                 # Mac/Linux
del artha.db                # Windows
# restart the server — schema rebuilds on startup
```

### Tests fail with "RuntimeError: There is no current event loop"
You're on an old pytest-asyncio. Reinstall dev deps:
```bash
pip install -e ".[dev]" --upgrade
```

### Tests show DeprecationWarnings everywhere
Expected — Pass 20 marks the legacy `artha.investor.service` / `artha.portfolio.service` / `artha.decision` modules as deprecated. To silence in your terminal:
```bash
.venv/bin/python -m pytest tests/test_unit/ -q -W ignore::DeprecationWarning
```

### LLM calls fail / 401 unauthorized
Default provider is `MOCK` (no API key needed). If you switched providers via `.env`, double-check the key:
```bash
echo $ANTHROPIC_API_KEY      # Mac/Linux
$env:ANTHROPIC_API_KEY       # Windows PowerShell
```

### Reload loop / server keeps restarting
`--reload` watches the working tree. If you have a process writing to `artha.db` continuously (e.g. a stuck test), uvicorn restarts on every write. Either drop `--reload` or stop the writer.

### Permission denied on `Activate.ps1` (Windows)
PowerShell blocks unsigned scripts by default:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
Re-run activation.

### `pip install -e ".[dev]"` fails on `langgraph` or similar
Some optional deps need build tools. On Mac install Xcode CLI tools (`xcode-select --install`); on Windows install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/). Then retry.

---

## 6. Useful URLs once the server is up

| URL | What |
|-----|------|
| <http://127.0.0.1:8000/docs> | Interactive Swagger UI |
| <http://127.0.0.1:8000/redoc> | ReDoc (cleaner, read-only) |
| <http://127.0.0.1:8000/openapi.json> | Raw OpenAPI schema |
| <http://127.0.0.1:8000/health> | Health check (if wired) |

---

## 7. FAQ

**Q: Do I need Docker / Postgres / Redis to run locally?**
No. Default is in-process SQLite, MockProvider for LLM. Zero external services.

**Q: Where does data live?**
`./artha.db` (gitignored). Wipe it freely in dev.

**Q: How do I see what a canonical schema looks like?**
```bash
.venv/bin/python -c "from artha.canonical import T1Event; print(T1Event.model_json_schema())"
```

**Q: How do I run just the Pass 20 tests?**
```bash
.venv/bin/python -m pytest tests/test_unit/test_legacy_migration.py -v
```

**Q: How do I get a list of every canonical schema in the registry?**
```bash
.venv/bin/python -c "
from artha.registry import populate_default_registry
reg = populate_default_registry()
for name in reg.names(): print(name)
"
```

**Q: How do I stop everything cleanly?**
- `Ctrl+C` in the terminal running uvicorn — stops the server
- Background process: `kill $(cat /tmp/samriddhi.pid)` (Mac/Linux)

**Q: What Python version?**
3.12 — pinned in `pyproject.toml`. `python --version` to check.

**Q: How do I update dependencies?**
```bash
pip install -e ".[dev]" --upgrade
```

**Q: Can I run this without internet?**
Yes, after the initial `pip install`. The MockProvider uses canned responses — no API calls.

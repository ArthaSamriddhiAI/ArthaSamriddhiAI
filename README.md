# Samriddhi AI

Portfolio Operating System for Indian wealth advisors — Evidence,
Governance, Accountability.

## Quick start

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
alembic upgrade head
uvicorn artha.app:app --reload

# Frontend
cd web
npm install
npm run dev
```

## Indicative master data fixture

The repo includes an indicative master data fixture in `data/fixtures/`.
This fixture is what the JSONFixtureAdapter loads by default in demo
deployments — anyone cloning the repo can run the system end-to-end
without out-of-band file management.

The fixture is a stand-in for actual data feeds; live adapters arrive in
cluster 17. See `data/fixtures/README.md` for fixture details (contents,
effective date, refresh procedure, known limitations).

## Documentation

- `DEMO_GUIDE.md` — operating the running system for demos
- `docs/doc1_v2/` — foundation reference + chunk plans
- `data/fixtures/README.md` — fixture contents

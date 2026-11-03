# PayTrace

Order-level payment reconciliation for a D2C brand. Finance uploads every partner's settlement,
COD remittance and freight reports; PayTrace shows, per order, whether the right amount was paid,
and lists anything short, late or overcharged as a claim with evidence.

- Spec: [CLAUDE.md](CLAUDE.md) · Assumptions: [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) · Decisions: [docs/DECISIONS.md](docs/DECISIONS.md)

## Stack

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Polars · Next.js 16 · Tailwind 4 · shadcn/ui · TanStack Query

## Run locally

Requirements: Docker, Python 3.11+, Node 20+.

```bash
# 1. Configuration
cp .env.example .env                 # fill in values (JWT_SECRET: any random 32+ chars)
#    Frontend variables go in frontend/.env.local:
#    NEXT_PUBLIC_API_URL=http://localhost:8000
#    NEXT_PUBLIC_DEMO_MODE=true

# 2. Database (also creates the paytrace_test database used by pytest)
docker compose up -d

# 3. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate               # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
alembic upgrade head
python ../scripts/seed.py            # demo users; passwords from DEMO_*_PASSWORD
uvicorn app.main:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

## Tests

```bash
cd backend
pytest            # needs the docker-compose database running
```

## Roles

| Role | Can |
|---|---|
| Finance executive | Everything: upload, map columns, edit rate cards, change claim status |
| Co-founder | Read and export only. Write controls are hidden in the UI and refused (403) by the API |

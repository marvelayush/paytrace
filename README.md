# PayTrace

**Order-level payment reconciliation for a D2C brand.** Finance uploads every partner's reports (marketplace and quick-commerce settlements, payment-gateway settlements, courier COD remittances and freight invoices, warehouse return scans). PayTrace works out, per order, what each partner *should* have paid under its rate card, compares it with what was actually paid, and puts anything short, unpaid, overcharged or lost into a claims list with evidence.

| | |
|---|---|
| Live demo | see [deployment.md](deployment.md) (demo accounts listed there) |
| Spec | [docs/SPEC.md](docs/SPEC.md) |
| Assumptions (A1–A39) | [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) |
| Design decisions | [docs/DECISIONS.md](docs/DECISIONS.md) |
| Benchmark | [docs/BENCHMARK.md](docs/BENCHMARK.md): **1 lakh orders end to end in 18 s** |
| Milestone log | [docs/PROGRESS.md](docs/PROGRESS.md) |

## What it does

- **Upload any partner's report** (CSV or Excel). The file's header fingerprint picks the saved column mapping. If a partner changed its format, **AI (Gemini) proposes a mapping** from the headers plus five PII-masked rows; a fuzzy matcher takes over if the AI is unavailable. The user checks it on a 20-row preview with per-cell validation, approves it as a new version, and can roll back. Rejected rows are kept with reasons and exportable.
- **Expected amounts by rule, not AI**: commission, fixed fee, gateway or COD fee, slab freight on the higher of dead and volumetric weight, returns reversing channel fees. GST TCS and income-tax TDS are computed separately and **never counted as leakage**.
- **Order-level matching** of every settlement, COD and freight line (by order ID, or by AWB when a courier reports only that), with statuses `settled`, `short_paid`, `unpaid_past_due`, `freight_overcharged`, `return_not_received` (plus `pending` for not-yet-due, A11) and the brief's ₹10 tolerance.
- **Claims** open automatically per owing partner, move open → filed → recovered / rejected (audited), and export as **evidence CSV** (every figure traced to its file and row) and a **PDF summary**.
- **Money-at-risk dashboard**: partner × age matrix that drills into the orders, auto-match rate against the 98% target, and the claims pipeline.
- **Two roles**: finance executive (everything) and co-founder (read and export only). Controls are hidden in the UI and refused by the API (403). A test sweeps every write route.
- **Personal data** (DPDP Act 2023): names and phones are masked at ingestion, addresses are never stored, and nothing unmasked is sent to the AI.

The brief's three sample orders reproduce exactly: ORD-W-204118 expected ₹1,409 / received ₹0; ORD-M-88120 ₹899 / ₹862; ORD-W-204377 −₹96 / −₹142.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · **Polars** (parsing and matching) · psycopg 3 `COPY` · rapidfuzz · Gemini (optional) · fpdf2 · Next.js 16 · TypeScript · Tailwind 4 · shadcn/ui · TanStack Query / Table / Virtual

```
backend/app/services/
  expected.py         rate-card engine (readable reference, pure functions)
  matching.py         vectorised Polars reconciliation (must agree with expected.py: tested)
  parsing.py          CSV/Excel -> typed canonical columns, rejection reasons
  mapping_ai.py       MappingSuggester: Gemini (LLMSuggester) + FuzzySuggester fallback
  ingest.py           COPY into Postgres, upserts, duplicate-safe line hashes
  claims.py           claim upkeep (set-based SQL), status flow
  evidence_export.py  claim CSV + PDF
  pii.py              masking
frontend/components/  dashboard, orders (virtualised table + drawer), claims, uploads (mapping review), rate cards
scripts/              generate_sample_data.py, seed.py, benchmark_matching.py
sample_data/          one realistic month: 15 partner reports in their own layouts + a "format changed" file
```

## Run it locally

Requirements: Docker, Python 3.11+ (developed on 3.13), Node 20+.

```bash
# 1. Configuration
cp .env.example .env
#    Fill in at least: JWT_SECRET (any random 32+ characters), DEMO_FINANCE_PASSWORD, DEMO_FOUNDER_PASSWORD.
#    DATABASE_URL can stay empty for the local default (postgresql+psycopg://paytrace:paytrace@localhost:5432/paytrace).
#    Frontend settings go in frontend/.env.local:
#      NEXT_PUBLIC_API_URL=http://localhost:8000
#      NEXT_PUBLIC_DEMO_MODE=true

# 2. Database (also creates paytrace_test for pytest)
docker compose up -d

# 3. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python ../scripts/seed.py --reset      # users, partners, rate cards, mappings, 15 sample reports, reconciliation, claims
uvicorn app.main:app --reload --port 8000

# 4. Frontend (second terminal)
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

Sign in as `finance@paytrace.demo` or `founder@paytrace.demo` with the passwords you put in `.env`.

**Try the AI mapping:** Uploads → *Marketplace 1 · Settlement* → drop `sample_data/format_changed/marketplace1_settlement_NEW_FORMAT.csv`. The partner renamed and reordered its columns, so the review screen opens with suggested mappings, confidence, reasons and a 20-row preview. Set `GEMINI_API_KEY` in `.env` to use Gemini; without it you get the fuzzy fallback and a notice saying so.

## Tests

```bash
cd backend
pytest              # 287 tests, about 5 minutes (needs the docker-compose database)
pytest -m slow      # the 1-lakh-row benchmark as a test: under 60 s required
```

The tests cover the three brief samples; every status rule and the ₹10 boundary; TCS/TDS never counted as difference; multiple and duplicate lines; vectorised and reference engines agreeing on 6,000 orders; every injected leak caught with zero false alarms; mapping fingerprint reuse, invalid AI JSON → fuzzy fallback, validation, approve and rollback; no raw PII sent to the AI; PII masking; co-founder blocked on every write route; claims upkeep and exports; dashboard totals.

```bash
cd frontend && npm run lint && npm run build
```

## Benchmark

```bash
backend/.venv/Scripts/python scripts/benchmark_matching.py     # writes docs/BENCHMARK.md
```

100,000 orders and 2,55,199 partner rows, every file in its partner's format, through the real pipeline (parse → normalise → COPY → match → COPY results): **18.2 s** on a laptop (target < 60 s). All 4,262 due leaks were flagged with no false alarms. Details and per-stage timings are in [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Regenerate the sample data

```bash
backend/.venv/Scripts/python scripts/generate_sample_data.py --orders 30000
```

## Deploying

Neon + Render + Vercel, with a `render.yaml` blueprint. Step-by-step in [deployment.md](deployment.md).

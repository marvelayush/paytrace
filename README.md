# PayTrace

**Order-level payment reconciliation for a D2C brand: upload every partner's reports and see, per order, whether you were paid the right amount.**

**Live app:** https://paytrace-two.vercel.app · **Backend:** https://paytrace-api.onrender.com ([`/health`](https://paytrace-api.onrender.com/health)) · **Code:** https://github.com/marvelayush/paytrace

> The backend runs on Render's free plan and sleeps after 15 idle minutes. If the app says it is not responding, open the backend `/health` link first, wait up to a minute for `{"status":"ok","database":"ok"}`, then reload. Demo logins are in [deployment.md](deployment.md#demo-accounts).

A D2C home-textiles brand sells on its own website, three marketplaces and two quick-commerce apps, and ships through two courier aggregators. About 30,000 orders a month at ₹1,200 each pass through partners that deduct commissions, fees and freight before paying out. Roughly **1.5% of order value leaks** through unremitted cash on delivery (COD), wrong fees, wrong weight slabs and returns that never reach the warehouse: about ₹64.8 lakh a year. Finance finds it by matching spreadsheets with lookups, and month-end close takes 12 days.

PayTrace takes each partner's settlement, COD remittance, freight invoice and warehouse return files, in whatever layout the partner uses. It works out what each order *should* have paid under the rate card and compares that with what actually arrived. Anything short, unpaid, overcharged or lost goes into a claims list, with evidence traced to the file and row it came from.

| | |
|---|---|
| Live demo | https://paytrace-two.vercel.app |
| Demo logins | [deployment.md → Demo accounts](deployment.md#demo-accounts) |
| Spec | [docs/SPEC.md](docs/SPEC.md) |
| Assumptions (A1–A47) | [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) |
| Design decisions | [docs/DECISIONS.md](docs/DECISIONS.md) |
| Benchmark | [docs/BENCHMARK.md](docs/BENCHMARK.md) |
| Tools used | [docs/TOOLS.md](docs/TOOLS.md) |
| How I used AI | [docs/AI_USAGE.md](docs/AI_USAGE.md) |
| Milestone log | [docs/PROGRESS.md](docs/PROGRESS.md) |

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Tests: 337 passing](https://img.shields.io/badge/tests-337%20passing-2E7D32)

## Contents

1. [Screenshots](#screenshots)
2. [Key features](#key-features)
3. [Architecture](#architecture)
4. [How it works](#how-it-works)
5. [Roles and permissions](#roles-and-permissions)
6. [Tech stack](#tech-stack)
7. [Project structure](#project-structure)
8. [Getting started](#getting-started)
9. [Tests, checks and scripts](#tests-checks-and-scripts)
10. [Performance](#performance)
11. [Security and privacy](#security-and-privacy)
12. [Troubleshooting](#troubleshooting)
13. [Known limitations and what's next](#known-limitations-and-whats-next)
14. [Deployment](#deployment)
15. [Author](#author)

## Screenshots

Captured with headless Chrome from the running app on the seeded demo data (light theme, 1440 px wide unless noted).

**Money at risk:** headline numbers, then who owes what and for how long. Every cell opens its orders.

![Money-at-risk dashboard](docs/screenshots/dashboard.webp)

**Order detail:** the brief's sample order ORD-M-88120. Expected ₹899, received ₹862, ₹37 short, with every rupee itemised. TCS and TDS are shown as tax credits, never as leakage.

![Order drawer with the expected-amount breakdown](docs/screenshots/orders-drawer.webp)

**Mapping review:** Marketplace 1 renamed and reordered its columns. Gemini proposed the mapping with a confidence and reason per field; the first 20 rows are parsed and checked before anything is saved.

![Column mapping review with AI suggestions](docs/screenshots/mapping-review.webp)

**Review queue:** partner lines that arrived without an order ID, each with suggested orders and a side-by-side comparison.

![Review queue](docs/screenshots/review-queue.webp)

**Returns tracker:** every returned or RTO order against warehouse receipt scans. Overdue returns are claimed.

![Returns tracker](docs/screenshots/returns.webp)

**Claims:** grouped by the partner who owes the money, ready to export as CSV evidence and a PDF summary.

![Claims list](docs/screenshots/claims.webp)

**On a phone (375 px):** the same screens as cards, with a bottom navigation bar.

<img src="docs/screenshots/mobile-review.webp" alt="Review queue on a 375 px phone screen" width="300">

## Key features

### Upload and AI column mapping
- Upload CSV or Excel (`.csv`, `.xlsx`) for any partner and report type. The file's header fingerprint picks the saved column mapping for that source.
- When a partner changes its format, **Gemini proposes a mapping** from the headers and five sample rows with personal data masked. If the AI is unavailable, a fuzzy matcher takes over and the screen says so.
- Every proposal is **previewed on 20 rows** with per-cell validation (dates, amounts, order IDs, required fields), plus rule-based plausibility checks: TCS should exceed TDS, and gross minus deductions should equal net.
- Only **Approve** saves a mapping, as a new version. Earlier versions stay available for **rollback**. Both are audited.
- Rejected rows are kept with a reason and can be exported. A second upload of the same report is recognised line by line and never double-counted.

### Reconciliation engine
- **Expected amounts by rule, not AI:** commission, fixed fee, gateway fee, COD fee, and slab freight on the higher of dead and volumetric weight. Returns reverse the channel fees and add return freight. Rate cards are effective-dated.
- **Order-level matching** of every settlement, COD and freight line, by order ID or by AWB when a courier reports only that. Multiple and partial lines per order are summed.
- The brief's five statuses (`settled`, `short_paid`, `unpaid_past_due`, `freight_overcharged`, `return_not_received`), plus `pending` for money not yet due. The brief's **₹10 tolerance** applies.
- Vectorised with Polars and written back with Postgres `COPY`: **1 lakh orders end to end in 13.6–18.2 s** (target under 60 s).

### Claims
- One open claim per owing partner, kept in step with every reconciliation. Status moves open → filed → recovered or rejected, and every change is audited.
- **Evidence CSV** (every figure traced to its file and row) and a **PDF summary** per claim.

### Money-at-risk dashboard
- Money at risk, auto-match rate against the 98% target, open claims, and TCS + TDS withheld, labelled "tax, not leakage".
- A partner × age matrix (0–15, 16–30, 31–60, 60+ days past due). Each cell drills into its orders.
- Cards for returns not received and for review-queue lines.

### Returns tracker
- Every returned or RTO order, shown as **received**, **waiting** (inside the 7-day receipt window) or **not received** (window passed, value claimed).
- Filters by status, courier and age, with counts on each chip. Overdue rows stand out in red and link to their claim.
- A finance executive can **mark a return received** without a scan, with a required note. It is audited and the order is re-matched at once.

### Review queue
- Settlement and COD lines that arrive **without an order ID** are queued, not rejected.
- The rules shortlist up to five orders per line (partner, amount tolerance, date window, AWB). Gemini breaks ties and explains its pick, with its **confidence capped by the rule score**.
- Accept, pick another candidate, or reject. Bulk accept is available only for lines at **90% confidence or more**, and still needs a click. **Nothing is linked automatically.**

### Roles and security
- Two roles: **finance executive** (full access) and **co-founder** (read and export only). Controls are hidden in the UI and refused by the API (403); a test sweeps every write route.
- Email and password sign-in, bcrypt hashes, a JWT in an httpOnly cookie, and a login rate limit.

### Privacy (DPDP Act 2023)
- Customer names and phone numbers are **masked at ingestion**. Addresses are never stored, only the pincode.
- Nothing unmasked is ever sent to the AI. The review-queue ranking sends amounts, dates, AWB and partner only.

## Architecture

```mermaid
flowchart LR
    B["Browser"] -->|"HTTPS, pages and /api/*"| V["Next.js on Vercel<br/>UI + /api proxy"]
    V -->|"forwards /api/*"| R["FastAPI on Render<br/>auth, upload pipeline,<br/>matching engine, claims"]
    R -->|"SQL + COPY"| N[("PostgreSQL 16<br/>on Neon")]
    R -.->|"optional: masked headers,<br/>amounts and dates only"| G["Gemini API"]
```

**Why this shape.** The heavy work is one Python process: parsing 2.5 lakh partner rows with Polars and moving them in and out of Postgres with `COPY`. That suits a long-running FastAPI service better than serverless functions, which have body-size and time limits. The browser talks only to the Vercel site, which forwards `/api/*` to Render. That keeps the session cookie first-party, so sign-in works in Safari and on phones that block third-party cookies (the trade-off is a ~4.5 MB upload limit through the proxy; see [deployment.md](deployment.md)). Gemini is optional. Every AI feature has a rule-based fallback, so the product works without a key.

## How it works

### From upload to claim

```mermaid
flowchart TD
    U["Upload a partner file<br/>(CSV / XLSX)"] --> F{"Header fingerprint<br/>matches the saved mapping?"}
    F -->|yes| P["Parse and validate<br/>with Polars"]
    F -->|no| AI["Gemini proposes a mapping<br/>(fuzzy fallback)"]
    AI --> PV["20-row preview,<br/>validation and plausibility checks"]
    PV -->|"person approves:<br/>new version"| P
    P --> L["Ledger lines via COPY<br/>(duplicates skipped by line hash)"]
    P --> Q["Lines without an order ID<br/>go to the review queue"]
    P --> X["Rejected rows<br/>kept with a reason"]
    L --> M["Reconciliation:<br/>expected vs received per order"]
    Q -->|"person accepts a suggestion"| L
    M --> S["Status per order<br/>(₹10 tolerance)"]
    S --> C["Claims per partner<br/>+ CSV / PDF evidence"]
    S --> D["Money-at-risk dashboard<br/>and returns tracker"]
```

### Expected amount

For each order, from the rate cards in force on the order date:

```text
delivered:  expected = value − commission − fixed fee − gateway fee (prepaid) − COD fee (COD) − forward freight
returned:   expected = − (forward freight + return freight)        channel fees are reversed
freight:    slab price for max(dead weight, volumetric weight)
received:   settlement net + TCS + TDS withheld + COD remitted − courier freight and COD charges invoiced
difference: received − expected                                   TCS and TDS never count as a difference
```

The seed rate cards reproduce the brief's three sample orders exactly (values are assumptions, A17):

| Order | Facts | Expected | Received | Difference | Status |
|---|---|---|---|---|---|
| ORD-W-204118 | Website, ₹1,499 COD, Courier A, 450 g | 1,499 − COD fee 30 − freight 60 = **₹1,409** | ₹0 (COD collected, never remitted) | −₹1,409 | `unpaid_past_due` |
| ORD-M-88120 | Marketplace 1, ₹1,199 prepaid | 1,199 − commission 20% (239.80) − fixed fee 60.20 = **₹899** | net 854.80 + TCS 6.00 + TDS 1.20 = **₹862** | −₹37 | `short_paid` |
| ORD-W-204377 | Website, ₹2,398 prepaid, returned, Courier B, 480 g | −(forward 48 + return 48) = **−₹96** | paid 2,350.04, refunded −2,350.04, freight billed on 900 g: −(71 + 71) = **−₹142** | −₹46 | `freight_overcharged` |

### Status rules (first match wins)

| # | Status | Rule |
|---|---|---|
| 1 | `return_not_received` | Returned or RTO, no warehouse receipt, and the 7-day receipt window has passed |
| 2 | `freight_overcharged` | Courier freight charged − expected freight > ₹10 |
| 3 | `unpaid_past_due` | Delivered, nothing received, and the partner's due date has passed |
| 4 | `pending` | In transit, not yet due, or a return still inside its window: not money at risk (A11) |
| 5 | `short_paid` | Received < expected − ₹10 |
| 6 | `settled` | Everything else: within ₹10, or overpaid (flagged, A12) |

A difference of exactly ₹10.00 is settled; ₹10.01 is flagged (tested). Due dates follow each partner's settlement cycle: T+7 for marketplaces and quick-commerce, T+10 for courier COD, T+3 for the payment gateway (A3).

### How the AI is used, and what happens when it is wrong

The AI never decides money. Matching and expected amounts are rules. The AI does two narrow jobs, each with a safety net:

| Job | When it works | When it is wrong | When it is unavailable |
|---|---|---|---|
| **Column mapping** for a changed partner format | Proposes a source column per field with confidence and reason | 20-row preview with cell validation and plausibility checks; fields under 0.7 confidence or with errors must be confirmed; only Approve saves, as a new version; rollback to any earlier version | Fuzzy matcher (rapidfuzz on header synonyms and value types), with the notice "AI unavailable, showing best guesses" |
| **Ranking suggested orders** for lines without an order ID | Breaks exact ties between rule candidates and writes the reason | Cannot overrule a clear rule winner; confidence capped by the rule evidence; bulk accept only at ≥ 0.9; never linked without a person's click | Rule order and rule confidence, with the reason shown on screen |

Measured against known answers (`scripts/eval_ai_mapping.py`, `scripts/eval_match_suggestions.py`):

- **Column mapping:** Gemini (`gemini-3.1-flash-lite`) mapped **194/194 fields** right across 18 sample layouts and 2 deliberately hard ones, in about 2.6 s per file. The fuzzy fallback got 190/194.
- **Matching suggestions:** for 82 lines without an order ID, the rules shortlisted the right order **82/82** times and suggested it **61/82** times. The other 21 are exact ties: orders with the same partner, value and due date that no data can separate, so they wait for a person at 50%. Gemini choosing freely got only **47–51/82**, and was confident and wrong on 5 lines. That measurement is why it now only breaks ties, with confidence capped. Result: **61/82 right, 0 wrong at bulk-accept confidence.**
- The real-key test caught two problems mocks would have missed. `gemini-2.5-flash` returns 404 to new API keys, which made every mapping silently fall back to fuzzy. And the model once swapped TCS and TDS, which led to the plausibility checks.

## Roles and permissions

| Action | Finance executive | Co-founder |
|---|:---:|:---:|
| View dashboard, orders, order detail, claims, returns, review queue, rate cards | ✓ | ✓ |
| Export claim evidence (CSV, PDF) and rejected rows | ✓ | ✓ |
| Upload partner files | ✓ | — |
| Approve or roll back column mappings | ✓ | — |
| Edit rate cards or add a new version | ✓ | — |
| Run reconciliation | ✓ | — |
| Change claim status | ✓ | — |
| Accept, reject or bulk-accept review-queue lines | ✓ | — |
| Mark a return received by hand | ✓ | — |

Co-founders never see a control they cannot use, and the API returns 403 if one is called anyway (A2).

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| API | FastAPI, Pydantic v2, Uvicorn | Typed request validation and a dependency-based role check on every route |
| Data processing | Polars | Vectorised parsing and matching: no Python loop per row |
| Database access | SQLAlchemy 2, Alembic, psycopg 3 `COPY` | Models and migrations; bulk loads and result writes in seconds |
| Database | PostgreSQL 16 (Docker locally, Neon in production) | One store; money as integer paise |
| Excel | fastexcel (calamine), openpyxl | Fast `.xlsx` reading; the Excel sample file is written in its partner's layout |
| AI | Gemini API (REST via httpx), rapidfuzz | Mapping and ranking suggestions; fuzzy fallback without a key |
| Auth | bcrypt, PyJWT | Password hashing; session token in an httpOnly cookie |
| Exports | fpdf2 | Claim PDF summary |
| Frontend | Next.js 16 (App Router), React 19, TypeScript | The app and the `/api` proxy |
| UI | Tailwind CSS 4, shadcn/ui on Radix, lucide-react, motion, sonner, cmdk | Accessible components, one accent colour, Ctrl/Cmd+K palette |
| Data in the UI | TanStack Query, Table, Virtual | Caching, optimistic updates, a virtualised table for 30,000 orders |
| Tests | pytest, ESLint, `next build` | 337 backend tests; lint and type checks |
| Deploy | Render, Vercel, Neon | Free tiers; `render.yaml` blueprint |

The complete list, with what each tool does, is in [docs/TOOLS.md](docs/TOOLS.md).

## Project structure

```text
paytrace/
├── backend/
│   ├── app/
│   │   ├── main.py              app factory, CORS, security headers, routers
│   │   ├── config.py            settings from environment variables
│   │   ├── auth.py              password hashing, session cookie, role guards, login rate limit
│   │   ├── models/              SQLAlchemy models (ledger, recon, claims, review queue, ...)
│   │   ├── routers/             auth, sources, uploads, rate_cards, recon, claims, dashboard, returns, review
│   │   ├── schemas/             Pydantic request/response models
│   │   ├── sample_data/         synthetic data generator and each partner's file layout
│   │   └── services/
│   │       ├── parsing.py       CSV/Excel → typed canonical columns, rejection reasons
│   │       ├── mapping_ai.py    Gemini column mapping + fuzzy fallback
│   │       ├── mapping_checks.py  plausibility checks on the 20-row preview
│   │       ├── ingest.py        COPY into Postgres, duplicate-safe line hashes
│   │       ├── expected.py      rate-card engine (readable reference, pure functions)
│   │       ├── matching.py      vectorised Polars reconciliation
│   │       ├── claims.py        claim upkeep and status flow
│   │       ├── evidence_export.py  claim CSV and PDF
│   │       ├── returns.py       returns tracker
│   │       ├── review_queue.py  rule shortlist and decisions for lines without an order ID
│   │       ├── match_ai.py      Gemini ranking of the shortlist + rule fallback
│   │       └── pii.py           masking
│   ├── alembic/                 migrations
│   └── tests/                   pytest suite
├── frontend/
│   ├── app/                     Next.js routes (login, dashboard, orders, claims, review, returns, uploads, rate cards)
│   ├── components/              screens and shared UI
│   └── lib/                     API client, data hooks, formatting
├── scripts/
│   ├── seed.py                  demo users, reference data, sample files, reconciliation, queue ranking
│   ├── generate_sample_data.py  one realistic month in every partner's own layout
│   ├── benchmark_matching.py    1 lakh orders end to end, writes docs/BENCHMARK.md
│   ├── eval_ai_mapping.py       AI column-mapping accuracy
│   └── eval_match_suggestions.py  review-queue suggestion accuracy against the sample truth
├── sample_data/                 15 partner reports + a "format changed" file
├── docs/                        spec, assumptions, decisions, benchmark, tools, AI usage, progress, screenshots
├── docker-compose.yml           local Postgres 16 (+ test database)
├── render.yaml                  Render blueprint for the API
└── deployment.md                Neon + Render + Vercel steps, demo accounts
```

## Getting started

### Prerequisites

| Tool | Version |
|---|---|
| Docker Desktop (with Compose) | any recent version |
| Python | 3.11 or newer (developed on 3.13) |
| Node.js | 20 or newer, with npm |
| Git | any |

### 1. Clone and configure

macOS / Linux:

```bash
git clone https://github.com/marvelayush/paytrace.git
cd paytrace
cp .env.example .env
printf "NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_DEMO_MODE=true\n" > frontend/.env.local
```

Windows (PowerShell):

```powershell
git clone https://github.com/marvelayush/paytrace.git
cd paytrace
Copy-Item .env.example .env
"NEXT_PUBLIC_API_URL=http://localhost:8000", "NEXT_PUBLIC_DEMO_MODE=true" | Set-Content frontend\.env.local
```

Then open `.env` and fill in at least `JWT_SECRET`, `DEMO_FINANCE_PASSWORD` and `DEMO_FOUNDER_PASSWORD`. Every variable:

| Name | Required | What it does | Example format |
|---|---|---|---|
| `JWT_SECRET` | **yes** | Signs session tokens; the API refuses to start without it | 32+ random characters |
| `DEMO_FINANCE_PASSWORD` | **yes, to seed** | Password for `finance@paytrace.demo` | any string |
| `DEMO_FOUNDER_PASSWORD` | **yes, to seed** | Password for `founder@paytrace.demo` | any string |
| `DATABASE_URL` | no | Postgres connection; defaults to the local docker-compose database | `postgresql://USER:PASSWORD@HOST:5432/DB` |
| `TEST_DATABASE_URL` | no | Database for pytest; defaults to the local `paytrace_test` | same format |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | no | Local docker-compose database; default `paytrace` | `paytrace` |
| `JWT_EXPIRE_MINUTES` | no | Session length; default 480 | `480` |
| `COOKIE_SECURE` | no | Send the cookie over HTTPS only; `true` in production | `false` |
| `COOKIE_SAMESITE` | no | Cookie SameSite policy; default `lax` | `lax` / `strict` / `none` |
| `FORWARDED_HOPS` | no | Trusted proxies in front of the API, for the login rate limit; default 0 | `0` |
| `FRONTEND_ORIGIN` | no | Allowed CORS origin(s), comma-separated; default `http://localhost:3000` | `https://app.example.com` |
| `ENABLE_DOCS` | no | Interactive API docs at `/docs`; default on | `true` |
| `MAX_UPLOAD_MB` | no | Largest upload the API accepts; default 50 | `50` |
| `UPLOAD_DIR` | no | Where files wait between inspection and processing; default `uploads` | `uploads` |
| `RETURN_RECEIPT_DAYS` | no | Warehouse receipt window for returns (A8); default 7 | `7` |
| `GEMINI_API_KEY` | no | Turns on the AI features; without it, fuzzy and rule fallbacks are used | key from aistudio.google.com |
| `GEMINI_MODEL` | no | Model name; default `gemini-3.1-flash-lite` | `gemini-3.1-flash-lite` |
| `GEMINI_THINKING_LEVEL` | no | `low` / `medium` / `high`; default `low` | `low` |
| `NEXT_PUBLIC_API_URL` | **yes (frontend)** | Where the browser calls the API: the backend URL, or `/api` in proxy mode | `http://localhost:8000` |
| `NEXT_PUBLIC_DEMO_MODE` | no | Shows the demo-account hint on the login screen | `true` |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | no | Largest file the browser sends; default 4 in proxy mode, 50 otherwise | `4` |
| `BACKEND_URL` | proxy mode only | Backend that `/api/*` is forwarded to | `https://api.example.com` |

The `NEXT_PUBLIC_*` and `BACKEND_URL` variables go in `frontend/.env.local`; everything else goes in `.env` at the repository root.

### 2. Start the database

```bash
docker compose up -d
```

This starts Postgres 16 on port 5432 and creates the `paytrace_test` database used by pytest.

### 3. Backend

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/python ../scripts/seed.py --reset
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python ..\scripts\seed.py --reset
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

The seed creates the two demo users, partners, rate cards and v1 column mappings. It processes the 15 sample reports through the real upload pipeline, adds a few recent returns, reconciles about 30,000 orders, opens claims and ranks the review queue. It takes 10 seconds without a Gemini key, or about a minute with one. `--reset` empties every table first.

The API is now at http://localhost:8000. `/health` should return `{"status":"ok","database":"ok"}`, and `/docs` has the interactive API docs.

### 4. Frontend (second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and sign in as `finance@paytrace.demo` (full access) or `founder@paytrace.demo` (read-only), with the passwords you put in `.env`.

### 5. A five-minute tour

1. **Money at risk:** click a red cell, for example *Marketplace 1 · 16–30 days*. The orders screen opens filtered to exactly those orders.
2. **Orders:** press Ctrl/Cmd+K and type `88120`. The drawer shows the brief's order: expected ₹899, received ₹862, ₹37 short, with "where every rupee went" and the evidence lines.
3. **Uploads:** try the AI mapping (next section).
4. **Review queue:** accept a 100%-confidence suggestion and watch its order turn settled. Then look at a 50% line, where two orders genuinely look the same.
5. **Returns and Claims:** filter *Not received*, mark one return received with a note, then open a claim and download the **PDF summary**. Sign in as the co-founder to see the same screens without any controls.

### Try the AI column mapping

1. Uploads → *Which report is this?* → **Marketplace 1 · Settlement**.
2. Drop `sample_data/format_changed/marketplace1_settlement_NEW_FORMAT.csv`. The partner renamed and reordered every column.
3. The review screen shows each field's suggested source column, confidence and reason, and the first 20 rows parsed with any errors inline.
4. **Approve** saves mapping v2 and processes the file. Its lines are already stored, so they are recognised as duplicates, not double-counted. Under *Reports and mappings* you can roll back to v1.

With `GEMINI_API_KEY` set, the notice reads "AI suggested these columns". Without it, you get the fuzzy fallback and "AI unavailable, showing best guesses".

## Tests, checks and scripts

Run from `backend/` with the virtualenv's Python (`.venv/bin/python` on macOS/Linux, `.venv\Scripts\python` on Windows). Docker must be running.

```bash
.venv/bin/python -m pytest              # 336 tests, about 6 minutes
.venv/bin/python -m pytest -m slow      # the 1-lakh benchmark as a test: must finish under 60 s
```

Together, 337 tests. They cover:
- the brief's three sample orders and every status rule, including the ₹10 boundary;
- TCS and TDS never counted as a difference;
- duplicate and multiple lines, and the vectorised engine agreeing with the reference one;
- every injected leak caught with no false alarms;
- mapping fingerprints, invalid AI JSON → fuzzy fallback, validation, approve and rollback;
- no unmasked PII sent to the AI;
- the returns tracker and the review queue (shortlist, AI fallback, no auto-close, decisions);
- co-founder blocked on every write route.

Frontend, from `frontend/`:

```bash
npm run lint      # ESLint
npm run build     # type checks and the production build
```

Scripts, from the repository root (Windows: `backend\.venv\Scripts\python` instead of `backend/.venv/bin/python`):

```bash
backend/.venv/bin/python scripts/benchmark_matching.py          # 1 lakh orders end to end in a separate paytrace_bench database; rewrites docs/BENCHMARK.md
backend/.venv/bin/python scripts/generate_sample_data.py        # regenerates sample_data/ (deterministic: same seed, same files)
backend/.venv/bin/python scripts/eval_ai_mapping.py             # AI column mapping vs the right answer on every layout (--fuzzy for the fallback)
backend/.venv/bin/python scripts/eval_match_suggestions.py      # review-queue suggestions vs the sample truth (--rules-only skips the AI)
```

`eval_match_suggestions.py` re-ranks the open queue lines in the seeded database. It changes suggestions only, never decisions.

## Performance

`scripts/benchmark_matching.py` generates 100,000 orders and 2,55,199 partner rows, every file in its partner's own layout, with about 1.5% injected leakage. It runs the real pipeline against a separate database. Latest run (laptop, Postgres in Docker on the same machine; details in [docs/BENCHMARK.md](docs/BENCHMARK.md)):

| Stage | Time |
|---|---|
| Parse + normalise + `COPY` all 17 partner files (2,55,199 rows) | 9.61 s |
| Reconciliation: load from Postgres (`COPY TO STDOUT`) | 0.54 s |
| Reconciliation: match (Polars joins, expected amounts, status rules) | 0.20 s |
| Reconciliation: write 100,000 results (`COPY`) | 3.16 s |
| **End to end** | **13.57 s** (target < 60 s) |

Earlier runs on the same machine took 18.2 s, and 21.5 s as the slow pytest. Detection: 4,262 of 4,262 due leaks flagged, 0 false alarms, 99.16% auto-matched (target 98%).

In the UI, scrolling all 30,000 orders kept a median frame of 7 ms in headless Chrome. Lighthouse (production build, measured in milestone 11): desktop dashboard 100 / 100 / 100 and orders 99 / 100 / 100 for performance / accessibility / best practices. Throttled mobile performance is 77–79 (see limitations).

## Security and privacy

- **Secrets:** all configuration comes from environment variables. `.env*` files are git-ignored and `.env.example` holds names only. The API refuses to start without a 32+ character `JWT_SECRET`, and the Gemini key travels in a request header and is never logged.
- **Authentication:** bcrypt password hashes, and a JWT in an httpOnly cookie (`Secure` and `SameSite` set by configuration). An unknown email takes the same time as a wrong password. Failed logins are rate-limited per client IP (5 per 60 s), reading `X-Forwarded-For` only for the configured number of trusted proxies.
- **Access control:** the role is read from the database on every request. Every write route requires the finance-executive role, and a test fails if a new write route lacks that guard.
- **Input validation:** Pydantic models on every request body and query. Uploads are limited to `.csv` and `.xlsx` and to 50 MB (4 MB through the proxy).
- **Exports:** CSV cells starting with `=`, `+`, `-` or `@` are prefixed so spreadsheets do not run them as formulas (plain numbers are left alone).
- **CORS and headers:** CORS is restricted to the configured frontend origin(s). Responses carry `nosniff`, `X-Frame-Options: DENY`, a strict referrer policy and `Cache-Control: no-store`. API docs are off in production.
- **Personal data (DPDP Act 2023):**
  - names (first and last letter kept) and phone numbers (first and last two digits) are masked at ingestion;
  - addresses are dropped, keeping only the pincode;
  - the AI receives masked sample rows for mapping, and only amounts, dates, AWB and partner for match ranking.

## Troubleshooting

| Problem | Fix |
|---|---|
| `connection refused` on port 5432, or the seed cannot connect | Start Docker Desktop, then `docker compose up -d`. `docker compose ps` should show `paytrace-db` as healthy. |
| Port 5432, 8000 or 3000 already in use | Stop the other process, or change the port: `DATABASE_URL` for Postgres, `--port` for uvicorn (then update `NEXT_PUBLIC_API_URL`), `npm run dev -- -p 3001` for Next.js (then add that origin to `FRONTEND_ORIGIN`). |
| Proxy-mode build on Windows calls a path like `C:/Program Files/Git/api` | Git Bash rewrites `NEXT_PUBLIC_API_URL=/api` into a Windows path. Build from PowerShell (`$env:NEXT_PUBLIC_API_URL='/api'; npm run build`) or set `MSYS_NO_PATHCONV=1`. Vercel is unaffected. |
| The deployed app takes 30–60 s to answer at first | Render's free plan sleeps after 15 minutes idle. Open the backend `/health` first and wait for `{"status":"ok","database":"ok"}`. |
| Signed in, but the session is lost on reload in Safari or on a phone | The API is being called directly from another site, so the cookie is third-party and blocked. Use proxy mode (`NEXT_PUBLIC_API_URL=/api` + `BACKEND_URL`), or put both apps on one domain. |
| Mapping review says "AI unavailable, showing best guesses" | No key, a 404 (old model name: `gemini-2.5-flash` no longer serves new keys) or a quota error (429). The fuzzy fallback still works. Check `GEMINI_API_KEY` and `GEMINI_MODEL`. The review queue shows "AI unavailable: ranked by the rules" for the same reasons. |
| "The file is too large for this deployment" | Through the Vercel proxy, uploads are capped at about 4.5 MB (the browser refuses files over 4 MB). Split the report by date range, or use one shared domain and direct mode for uploads up to 50 MB. |

## Known limitations and what's next

**Known limitations**
- **Mobile Lighthouse performance is 77–79**, against a target of 90. Every screen renders in the browser after a session check; server-rendering the first screen is the fix.
- **Uploads through the Vercel proxy are limited to about 4.5 MB.** A month of this client's reports fits, but larger files must be split unless both apps share a domain.
- **Look-alike lines need a person.** In the sample data, 21 of the 82 lines without an order ID are exact ties. Pincode is not used as a signal because no partner's settlement or remittance layout carries one.
- **Background AI ranking runs inside the API process.** If the server restarts mid-ranking, those lines keep their rule suggestions and stay marked "AI ranking…" until the next upload or seed.
- **The login rate limiter is in memory**, so it holds for one backend instance only.
- **The demo's "waiting" returns age out** after 7 days; re-run the seed to refresh them.
- **Recovered claims don't lower money at risk** until the partner's payment appears in an uploaded file (A41). The PDF writes "Rs" instead of ₹ because its built-in fonts lack the glyph (A39).
- **Users are seeded;** there is no user-management screen.

**What's next**
- Server-render the first screen now that proxy mode makes the cookie first-party to Next.js.
- Move AI ranking to a persistent job queue, and add the bank UTR as a matching signal.
- A partner-wise TCS/TDS reconciliation against Form 26AS, and per-partner settlement-cycle overrides in the UI.
- Continuous integration running the test suite, lint and build on every push.
- User management and per-user audit views.

## Deployment

Neon (Postgres), Render (FastAPI, from `render.yaml`) and Vercel (Next.js in proxy mode), all on free plans. [deployment.md](deployment.md) has step-by-step instructions, the environment variables for each service, the demo accounts, and a checklist to run after deploying.

## Author

**Ayush Narayan**
- GitHub: [marvelayush](https://github.com/marvelayush)
- LinkedIn: [linkedin.com/in/ayush-narayan-bmsce2004](https://www.linkedin.com/in/ayush-narayan-bmsce2004)

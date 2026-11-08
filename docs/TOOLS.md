# Tools used

Everything listed here is in the repository (requirements files, `package.json`, configs, scripts) or was used to build and check it. Nothing else.

## Languages and runtimes
- **Python 3.13** (3.11+ supported): backend, engines, scripts and tests.
- **TypeScript** (strict): the frontend.
- **Node.js 20+ / npm**: frontend tooling and the Next.js server.
- **SQL (PostgreSQL)**: set-based claim upkeep, `COPY` loads, migrations.

## Backend
- **FastAPI**: the HTTP API, with a role check on every protected route via a dependency.
- **Uvicorn**: the ASGI server, locally and on Render.
- **Pydantic v2 / pydantic-settings / email-validator**: request and response validation, the AI's JSON answer, and settings from environment variables.
- **SQLAlchemy 2**: models and queries.
- **Alembic**: schema migrations, run on every Render start.
- **Polars**: parses CSV and Excel files and runs the vectorised matching engine (no per-row Python loops).
- **psycopg 3 with Postgres `COPY`**: bulk loads of partner lines and reconciliation results.
- **fastexcel (calamine engine)**: reads `.xlsx` uploads through Polars.
- **openpyxl**: writes the Excel sample file in its partner's layout.
- **rapidfuzz**: the fuzzy column-mapping fallback when the AI is unavailable.
- **bcrypt + PyJWT**: password hashing and the session token in an httpOnly cookie.
- **python-multipart**: file uploads.
- **httpx**: calls to the Gemini REST API (and the API client in tests).
- **fpdf2**: the claim evidence PDF summary.

## Frontend
- **Next.js 16 (App Router)**: the app, and the `/api` proxy to the backend (proxy mode).
- **React 19**.
- **Tailwind CSS 4** (+ `tw-animate-css`): styling and design tokens.
- **shadcn/ui on Radix UI** (+ `class-variance-authority`, `cn`): accessible base components (dialog, sheet, select, tooltip, tabs, ...).
- **TanStack Query**: data fetching, caching and optimistic updates with rollback.
- **TanStack Table + TanStack Virtual**: the orders table, virtualised for 30,000 rows.
- **motion**: page, drawer and dialog transitions (respects reduce-motion).
- **sonner**: toasts.
- **cmdk**: the Ctrl/Cmd+K command palette.
- **lucide-react**: icons.
- **Geist** (via `next/font`): typeface.
- Charts (money-at-risk matrix, the "where every rupee went" waterfall) are plain HTML/CSS. No chart library is used.

## Database
- **PostgreSQL 16**: the only data store. Money is held as integer paise.
- **Docker / docker-compose**: local Postgres, plus a separate `paytrace_test` database for pytest.
- **Neon**: managed Postgres in production.

## Testing and quality
- **pytest** (with FastAPI's TestClient): **337 backend tests** (336 regular + the slow one) cover the engines, the ₹10 boundary, mapping, access control, claims, exports, PII, the returns tracker and the review queue.
- **Slow 1-lakh test** (`pytest -m slow`): 100,000 orders and 2,55,199 partner rows end to end in **13.6–18.2 s** across runs, against a 60 s limit.
- **Headless Chrome**: screenshots of every screen as both roles, light and dark, at 375 px and 1440 px; frame timing while scrolling 30,000 orders (median 7.0 ms per frame).
- **Lighthouse**: desktop dashboard 100/100/100 and orders 99/100/100 (performance / accessibility / best practices). Mobile (throttled): 79 and 77 performance, 100 accessibility and best practices.
- **ESLint** (`eslint-config-next`): frontend lint.
- **TypeScript compiler / `next build`**: type checks and the production build.

## Data
- **`scripts/generate_sample_data.py`**: one realistic month (30,000 orders, 15 partner reports in their own layouts, injected leakage, a "format changed" file, the brief's three sample orders).
- **`scripts/benchmark_matching.py`**: generates 1 lakh orders with leakage, runs the full pipeline, and writes `docs/BENCHMARK.md`.
- **`scripts/eval_ai_mapping.py`**: measures AI column mapping against every sample layout. Gemini got **194/194 fields right**; the fuzzy fallback got 190/194.
- **`scripts/eval_match_suggestions.py`**: scores the review-queue suggestions against the sample data's ground truth. The right order was shortlisted for 82/82 lines and suggested for 61/82; the other 21 are exact ties. No wrong suggestion reached bulk-accept confidence.
- **`scripts/seed.py`**: demo users, partners, rate cards and mappings; loads the sample reports through the real pipeline, adds a few recent returns, reconciles, and ranks the review queue.

## Version control and deploy
- **Git**: small commits per working step.
- **GitHub**: public repository for reviewers.
- **Render**: the FastAPI backend (`render.yaml` blueprint).
- **Vercel**: the Next.js frontend and the `/api` proxy.
- **Neon**: production Postgres.

## AI tools
- **Gemini API (Google AI Studio key), `gemini-3.1-flash-lite`**: the in-product column-mapping suggestions and the ranking of suggested orders in the review queue, plus both eval scripts.
- **Claude (chat)** and **Claude Code**: used to build the project. How I used them is described in [AI_USAGE.md](AI_USAGE.md).

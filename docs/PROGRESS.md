# Progress

One entry per milestone: what was built, what works, and assumptions added.

## Milestone 1 — Foundation
- Repo layout, docker-compose Postgres (+ test database), FastAPI with `/health`, models for every table, Alembic migration.
- Auth: bcrypt and a JWT in an httpOnly cookie, roles `finance_exec` / `cofounder`, login rate limit. A route-table sweep test proves every write route returns 403 to a co-founder.
- Next.js 16 + Tailwind 4 + shadcn: design tokens, app shell (desktop sidebar, mobile sheet), login screen with loading and error states.
- Assumptions added: A11–A14.

## Milestone 2 — Expected-amount engine and rate cards
- `services/expected.py`: pure functions over paise. Covers commission, fixed fee, gateway fee (prepaid), COD fee (COD), slab freight on chargeable weight, returns that reverse channel fees, and TCS/TDS computed separately.
- Reference rate cards reproduce the brief's samples exactly: ORD-W-204118 → ₹1,409, ORD-M-88120 → ₹899, ORD-W-204377 → −₹96 (tests).
- API: `GET /partners`, `GET /rate-cards`, `PUT /rate-cards/{id}`, `POST /rate-cards` (new effective-dated version). Edits are finance-only, with before/after entries in `audit_log`.
- Rate cards screen: partner list (dropdown on mobile), fee cards, tax section labelled "Tax, not leakage", weight-slab table, edit / new-version dialog with inline validation, and a recompute hint after saving. Co-founders see no edit controls.
- Migration 2 adds `returned_date`, line hashes and row numbers (duplicate detection and evidence), the COD fee on freight lines, `at_risk_paise` and run stats.
- Fixed along the way: Tailwind's `dark:` variant was following the OS theme and half-darkening inputs. It is now class-based (light theme only).
- Tests: 61 passing.
- Assumptions added: A15–A23 (returns reverse fees, top-slab pricing, seed rates, definition of "received", rounding, TCS/TDS base, channel-shipped marketplace orders, gateway T+3, return window).

## Milestone 3 — Sample data generator and seed
- `scripts/generate_sample_data.py` writes a realistic month (30,000 orders, 21 Sep – 20 Oct 2026) as 15 partner reports, each in its own layout (header names, DD-MM-YYYY / ISO / DD-Mon-YYYY dates, plain / Indian-comma / ₹ amounts, grams vs kg, AWB-only courier files, one Excel), plus a "format changed" Marketplace 1 settlement report for the AI-mapping demo.
- Correct amounts come from the expected-amount engine. Leakage is injected and labelled (≈1.6% of value): unremitted COD, unpaid settlements, excess fees, wrong weight slabs, lost returns. The brief's three orders are included exactly.
- `scripts/seed.py [--reset]` creates the demo users, partners, sources, rate cards and an approved v1 column mapping for every source. Ingesting the sample files and the first reconciliation run are wired into the seed in Milestone 5, once the pipeline exists.
- Tests: generator determinism, brief rows, leakage share, layout coverage. Assumptions added: A24–A25.

## Milestone 4 — Upload, parsing and AI column mapping
- Parsing (Polars, vectorised): CSV/Excel read as text, then typed per canonical field. Covers amounts with ₹/commas/brackets, date format detection per column, kg/g weights, and status / payment / leg wording. Every rejected row gets a reason naming the row, column and value.
- Header fingerprint (normalised, sorted headers). Fingerprint matches the active mapping → processed straight away ("Using saved mapping vN"). Matches an older version → that version is proposed. Anything else → `MappingSuggester`: Gemini with JSON schema output, given headers and 5 PII-masked rows, falling back to fuzzy matching on any failure ("AI unavailable, showing best guesses").
- Review screen: per-field column picker, confidence badge, reason, 20-row preview with failing cells inline. Fields with low confidence or failures are highlighted and must be confirmed. Approve saves the next version; rollback reactivates an earlier one. Both are audited.
- Ingestion: COPY into a temp table, then insert. Orders are upserted; lines are de-duplicated by md5 line hash, so re-uploading a report never double-counts. PII is masked before writing (addresses not stored). Rejected rows are kept, viewable, and exportable as formula-safe CSV.
- Uploads screen: report picker, drop zone, result card, upload history, sources with mapping versions and rollback (finance only; hidden from co-founders).
- Found and fixed: a `.gitignore` rule that hid `frontend/components/uploads` from git and Tailwind.
- Tests: 234 backend tests passing, including every sample file processing with zero rejections, fallback on invalid AI JSON, a payload check that no raw PII reaches the AI, rollback restoring v1, and duplicate re-uploads.
- Assumptions added: A26–A30.

## Milestone 5 — Matching engine and benchmark
- `services/matching.py`: loads with COPY TO STDOUT, then Polars only. Rate card in force by as-of join, courier slab by forward as-of join, lines summed per order and matched by order ID or AWB, status rules in documented order (₹10 tolerance), at-risk amount, paying partner, due date and age. Results go back via COPY in one transaction; one run at a time (advisory lock).
- Runs: `POST /recon/runs`, `GET /recon/runs/latest`. Every processed upload re-runs reconciliation. The seed script now loads all 15 sample reports through the real pipeline and reconciles: 30,000 orders, ₹5.43 L at risk, 99.17% auto-matched.
- Benchmark (`scripts/benchmark_matching.py`, `docs/BENCHMARK.md`): **100,000 orders + 2,55,199 partner rows end to end in 18.2 s** (target < 60 s). 4,262 of 4,262 due leaks flagged, 0 false alarms. Dropping row-by-row foreign keys on bulk tables cut it from 31.4 s. The 15 s stretch is missed by about 3 s, spent maintaining the join-key indexes the spec requires.
- Tests: scalar/vectorised engines agree on 6,000 orders; every status rule and ₹10 boundary; TCS/TDS excluded from the difference; multiple lines summed; AWB-only matching; full DB path; slow test for 1 lakh < 60 s (`pytest -m slow`, passes in 32 s including generation). 259 tests pass by default.
- Assumptions added: A31–A36.

## Milestone 6 — Orders screen and order drawer
- API: `GET /recon/orders` (filters: owing partner, status or "flagged", age bucket, order ID / AWB search; sorts; totals for the filtered set) and `GET /recon/orders/{id}` (order facts with PII masked, itemised expected breakdown, TCS/TDS apart, every settlement / COD / freight / warehouse line with its file name and row number, and whether it matched by order ID or AWB).
- Orders screen: filters synced to the URL (the dashboard links into it), debounced search, clear filters, "N orders · ₹X at risk", virtualised table (TanStack Table + Virtual, infinite loading in pages of 200) with right-aligned tabular money, red shortfalls and status pills. Row click or Enter opens the drawer.
- Drawer: expected / received / difference cards, a one-sentence explanation of what is wrong and who owes it, "Where every rupee went" (rate card side by side with what partners paid), a tax-not-leakage note, evidence lines, and order facts.
- Tests: 7 API tests (filters, sorting, search, totals, breakdown, AWB-matched evidence, masked customer).
- TanStack Table is pinned to v8.21.3, the current stable API (v9 rewrote it).

## Milestone 7 — Claims
- `refresh_claims` (set-based SQL) runs after every reconciliation (API, uploads, seed). Each flagged order joins its owing partner's single open claim with an evidence snapshot. Paid orders leave open claims, and amounts follow the latest run. Filed, recovered and rejected claims are frozen, and an order is claimed at most once (unique index).
- Status flow open → filed (with optional partner reference) → recovered / rejected. Finance only, enforced server-side (409 on illegal transitions), audited.
- Evidence export for both roles: formula-safe CSV with each order's figures and the source file + row of every line, and a PDF summary (headline amount, summary by reason, item table with repeating headers, page numbers, Indian digit grouping).
- Screens: claims list with status tabs showing totals, one row per partner claim with reasons; claim detail with exports, finance-only status actions behind confirmation dialogs, item table that opens the order drawer, and a frozen notice once filed.
- Seeded demo: 7 open claims, 1,356 orders, ₹5.43 L.
- Tests: 10 claim tests (grouping, idempotent refresh, frozen after filing, new claim after filing, transitions and audit, co-founder read/export only, CSV source rows, PDF bytes).
- Assumptions added: A37–A39.

## Milestone 8 — Money-at-risk dashboard
- `GET /dashboard`: last run (as of, finished at, duration, orders, auto-match %, lines with no order), KPIs, partner × age-bucket matrix with bucket totals, breakdown by status, TCS/TDS by partner.
- Screen: four KPIs (money at risk, auto-matched vs the 98% target, open/filed/recovered claims, TCS + TDS labelled "Tax, not leakage"), a heat-tinted matrix (one hue, square-root scale so small amounts stay visible, hover title + accessible label per cell, click → filtered orders), "Why money is at risk" bars linking to each status, and a partner-wise tax table. Finance users get a "Run reconciliation" button.
- The seeded demo shows ₹5.43 L at risk across 1,356 orders, 99.2% auto-matched and ₹1.19 L tax withheld. Matrix, totals, KPI and open claims all agree to the paisa (test).
- Tests: 4 dashboard tests (empty state, matrix sums, tax kept apart, run info).

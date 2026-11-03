# PayTrace — Order-level payment reconciliation for a D2C brand

This file is the single source of truth for this project. Read it fully before doing anything, and re-read the relevant section before each milestone.

## 0. What this is

A take-home assessment for a Software Engineering role. A client brief was given; we must ship a working, deployed product with a polished UI. Reviewers read the code, the commit history and a Technical Design Document (TDD). Quality of work 50%, problem solving 30%, communication 20%.

Golden rule from the assessment: **build a small part really well instead of the whole scope badly.** Only the CORE BUILD must work end to end. Nothing on screen may be fake or dead — no dead buttons, no placeholder pages.

## 1. The client (from the brief — do not invent facts beyond this)

- Company A, Bengaluru. D2C home textiles brand selling on its own website, 3 marketplaces and 2 quick-commerce apps. 45 staff, finance team of 3. Books are in Tally.
- Shipping runs through 2 courier aggregators. 55% of website orders are cash on delivery (COD).
- Every month finance downloads settlement, COD remittance and freight invoice reports into Excel and matches them with lookups. Returns are rarely checked against what reached the warehouse.
- Problem: ~30,000 orders/month at ₹1,200 average. 1.5% of order value leaks through unremitted COD, wrong fees, wrong weight slabs and lost returns (₹64.8 lakh/yr). Month-end close takes 12 days.
- The ask: upload every partner's reports and see, per order, whether we were paid the right amount. Anything short, late or overcharged lands in a claims list with evidence.
- Success metrics: 98% of orders auto-matched; close from 12 days to 3; ₹30 lakh recovered via claims in year one.

### CORE BUILD (must work end to end, ~6–8 screens)
1. File upload (CSV or Excel) with column mapping saved per source
2. Order-level matching
3. Rate-card expected amounts (flag gaps over ₹10)
4. Claims list (by partner, with evidence export)
5. Money-at-risk view (by partner and age)
- Roles: **finance executive** and **co-founder**
- AI: **column mapping suggestions**
- Hard part: **matching 1 lakh (100,000) rows in under a minute**
- Mock payments, messages and outside systems. Seed from sample data.

### Statuses (exact set from the brief)
`settled`, `short_paid`, `unpaid_past_due`, `freight_overcharged`, `return_not_received`

### AI rules (from the brief)
- Matching and expected amounts are **rules, not AI**.
- AI proposes column mappings when a partner changes its format.
- When AI is wrong: mappings are **previewed on 20 rows, approved before saving, and versioned for rollback**.
- (Optional depth) AI suggests matches when an order ID is missing → these go to a **review queue and are never closed automatically**.

### Constraints (from the brief)
- Customer names, phones, addresses are personal data under the DPDP Act 2023 → **mask them wherever not needed**. Never send unmasked PII to the LLM.
- Settlements deduct **GST TCS** and **income-tax TDS** → show them **separately, never as leakage**.
- 1 lakh-row files must process in **under a minute**.
- Partner formats change without notice.

### Out of scope (do NOT build)
Storefront/inventory sync, GST filing, automatic claim filing.

### Optional depth (only after core is fully done, tested and deployed)
Returns tracker against warehouse receipt scans, AI suggested matches + review queue, partner-wise TCS/TDS summary.

### Sample data from the brief (must exist in seed data and compute to exactly these values)
| Order ID | Channel | Value ₹ | Payment | Delivery Status | Expected ₹ | Received ₹ | Difference ₹ |
|---|---|---|---|---|---|---|---|
| ORD-W-204118 | Website | 1499 | COD | Delivered | 1409 | 0 | -1409 |
| ORD-M-88120 | Marketplace 1 | 1199 | Prepaid | Delivered | 899 | 862 | -37 |
| ORD-W-204377 | Website | 2398 | Prepaid | Returned to warehouse | -96 | -142 | -46 |

Design the seed rate cards so these three rows reproduce exactly. Document the rate values used as assumptions.

## 2. Assumptions (every one of these must also appear, labelled, in docs/ASSUMPTIONS.md and later in the TDD)

Keep docs/ASSUMPTIONS.md updated whenever you make a new assumption. Use IDs (A1, A2, ...).

- A1 Partner names are generic: Website, Marketplace 1/2/3, QuickCom 1/2, Courier A, Courier B. No real brand names anywhere.
- A2 Co-founder role is read-only: sees dashboard, orders, claims, can export; cannot upload, edit mappings, edit rate cards or change claim status.
- A3 Settlement cycles per partner (used for "past due"): marketplaces T+7 days after delivery, quick-commerce T+7, COD remittance by courier T+10. Configurable per partner.
- A4 Money-at-risk age buckets: 0–15, 16–30, 31–60, 60+ days since the amount became due.
- A5 Gap threshold ₹10 (from brief) applies per order to the net difference.
- A6 TCS and TDS default rates are configurable per channel on the rate card (default assumption: GST TCS 0.5% and TDS 0.1% of taxable value on marketplace/quick-commerce settlements; none on own website). Mark clearly as an assumption to verify with the client's CA.
- A7 Claims have manual statuses: open → filed → recovered / rejected. Filing itself is done by the user outside the app (automatic filing is out of scope).
- A8 Return not received = order marked returned/RTO by courier, but no warehouse receipt scan within 7 days (configurable).
- A9 Freight is charged by weight slab on the higher of dead weight and volumetric weight; rate card defines slabs per courier.
- A10 All money stored as integer paise in the DB and engine; displayed as ₹ with 2 decimals.

## 3. Tech stack (decided — do not change without asking)

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 (async optional; sync is fine), Alembic migrations, **Polars** for parsing and matching, psycopg 3 with Postgres `COPY` for bulk inserts, `openpyxl`/`fastexcel` for Excel, `rapidfuzz` for fallback mapping, pytest.
- **DB:** PostgreSQL 16 (local via docker-compose; production on Neon).
- **Auth:** email + password, bcrypt hashing, JWT in an httpOnly cookie, role checked on every protected endpoint via a dependency.
- **AI:** Google Gemini API (model name from env var) with JSON-structured output. Wrapped behind an interface `MappingSuggester` with two implementations: `LLMSuggester` and `FuzzySuggester` (fallback when no API key, timeout, error or invalid JSON).
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui + TanStack Table (with row virtualisation for big tables) + TanStack Query + Recharts (only where a chart earns its place) + lucide-react icons.
- **Deploy:** backend on Render (web service), frontend on Vercel, DB on Neon. Uploads go straight to the backend (no serverless body-size limits).
- **Local dev:** `docker compose up` for Postgres; backend with `uvicorn`; frontend with `npm run dev`.

## 4. Repository layout

```
paytrace/
  CLAUDE.md
  README.md
  docker-compose.yml
  .env.example                # names only, no values
  .gitignore                  # must ignore .env*, uploads, node_modules, __pycache__, .venv
  backend/
    app/
      main.py
      config.py               # reads env vars
      db.py
      models/                 # SQLAlchemy models
      schemas/                # Pydantic schemas
      routers/                # auth, sources, mappings, uploads, rate_cards, recon, claims, dashboard
      services/
        parsing.py            # read CSV/Excel with Polars, header fingerprint
        mapping_ai.py         # MappingSuggester, LLM + fuzzy
        pii.py                # masking helpers
        expected.py           # rate-card expected amount engine (pure functions)
        matching.py           # reconciliation engine (Polars)
        claims.py
        evidence_export.py
      auth.py
    alembic/
    tests/
    pyproject.toml or requirements.txt
  frontend/
    app/ ...
    components/ ...
    lib/api.ts
  scripts/
    generate_sample_data.py   # realistic synthetic files
    benchmark_matching.py     # proves 1 lakh rows < 60s
    seed.py
  sample_data/                # generated small demo files committed; big benchmark files gitignored
  docs/
    ASSUMPTIONS.md
    DECISIONS.md              # short log of design decisions and why
    BENCHMARK.md              # benchmark results
```

## 5. Data model (Postgres)

Money in paise (BIGINT). Timestamps in UTC. Add indexes on all join keys (`order_id`, `awb`, `partner_id`, `status`).

- `users` (id, email, password_hash, name, role: finance_exec | cofounder, created_at)
- `partners` (id, name, kind: website | marketplace | quickcom | courier, settlement_days)
- `sources` (id, partner_id, file_kind: orders | settlement | cod_remittance | freight_invoice | warehouse_returns, name)
- `column_mappings` (id, source_id, version, mapping_json, header_fingerprint, created_by, approved_at, is_active, ai_suggested_json, notes)
- `uploads` (id, source_id, mapping_id, filename, row_count, rows_ok, rows_rejected, status: pending | processing | done | failed, error, uploaded_by, created_at, duration_ms)
- `upload_row_errors` (upload_id, row_number, reason) — rejected rows are kept and shown, never silently dropped
- `orders` (order_id PK, channel_partner_id, courier_partner_id, order_date, delivered_date, value_paise, payment_mode: cod | prepaid, delivery_status, dead_weight_g, volumetric_weight_g, customer_name_masked, customer_phone_masked, pincode)
- `settlement_lines` (id, upload_id, partner_id, order_id, settlement_date, gross_paise, commission_paise, fees_paise, tcs_paise, tds_paise, net_paise, raw_ref)
- `cod_remittances` (id, upload_id, courier_partner_id, order_id, awb, remittance_date, amount_paise, utr)
- `freight_lines` (id, upload_id, courier_partner_id, order_id, awb, charged_weight_g, leg: forward | return, freight_paise, invoice_no)
- `warehouse_receipts` (id, upload_id, order_id, received_at) — for return_not_received
- `rate_cards` (id, partner_id, effective_from, commission_pct_bp, fixed_fee_paise, cod_fee_paise, cod_fee_pct_bp, gateway_pct_bp, tcs_pct_bp, tds_pct_bp)
- `weight_slabs` (id, rate_card_id, leg, up_to_g, price_paise)
- `recon_runs` (id, started_by, started_at, finished_at, order_count, duration_ms)
- `recon_results` (run_id, order_id, expected_paise, received_paise, diff_paise, tcs_paise, tds_paise, expected_breakdown_json, evidence_json, status, due_date, age_days, partner_id)
- `claims` (id, partner_id, status: open | filed | recovered | rejected, total_paise, created_at, updated_by)
- `claim_items` (claim_id, order_id, reason_status, amount_paise, evidence_json)
- `audit_log` (id, user_id, action, entity, entity_id, before_json, after_json, at) — mapping approvals/rollbacks, rate card edits, claim status changes

## 6. The engines (the heart of the project — write these as pure, well-tested functions)

### 6.1 Expected amount (services/expected.py)
For each order, compute an itemised expected breakdown from the rate card effective on the order date:
- Channel deductions: commission % of value, fixed fee, payment gateway % (prepaid website), COD fee (fixed and/or %) for COD.
- Freight: forward-leg slab price from the courier's weight slabs using chargeable weight = max(dead, volumetric). Return leg added for returned orders.
- Taxes: TCS and TDS computed separately, stored in their own fields, **never counted as leakage**.
- `expected_net = value − commission − fees − freight − tcs − tds` for delivered orders; for returned orders expected net is the negative of return-leg costs (see sample row ORD-W-204377 → −96).
- Return the full breakdown dict so the UI can show "where every rupee went".

### 6.2 Matching (services/matching.py) — the hard part
- Load normalised data into Polars DataFrames. Aggregate received amounts per order across settlement lines and COD remittances (an order may have multiple lines, adjustments or partial remittances).
- Join on `order_id` with hash joins (left join from orders). Vectorised expressions only — **no Python per-row loops**.
- Status rules (evaluate in this order, first match wins, document the order):
  1. `return_not_received`: delivery_status is returned/RTO and no warehouse receipt within A8 window.
  2. `freight_overcharged`: charged freight − expected freight > ₹10.
  3. `unpaid_past_due`: nothing received and today > due_date (delivered_date + partner settlement_days).
  4. `short_paid`: received < expected − ₹10.
  5. `settled`: |received − expected| ≤ ₹10.
  - Orders received but not yet due and unpaid → `pending` (not money at risk yet) — add this as a documented assumption since it is not in the brief's list.
  - Overpaid by more than ₹10 → keep as `settled` with an `overpaid` flag shown in UI; document it.
- Write results with Postgres `COPY` (not ORM inserts). Wrap a run in a transaction.
- Record `duration_ms` per run. Target: 100,000 orders + their settlement/COD/freight lines end to end (parse → normalise → match → write) in well under 60 s on a laptop; aim for under 15 s.
- `scripts/benchmark_matching.py` generates 100k orders with ~1.5% injected leakage across all leak types, runs the full pipeline, prints timings per stage, and writes docs/BENCHMARK.md.

### 6.3 Column mapping with AI (services/mapping_ai.py)
- Target canonical fields per file_kind (e.g. settlement: order_id, settlement_date, gross, commission, fees, tcs, tds, net).
- On upload: read headers + first rows; compute `header_fingerprint` (hash of normalised sorted headers).
  - Fingerprint matches active mapping → reuse silently, show "Using saved mapping vN".
  - Otherwise → ask the suggester. Send **only headers and 5 sample rows with PII columns masked** (detect name/phone/address-like columns and mask before sending).
- LLM returns JSON: `{field: {source_column, confidence (0–1), reason}}`. Validate with Pydantic; on any failure fall back to FuzzySuggester and tell the user "AI unavailable, showing best guesses".
- Preview screen applies the proposed mapping to **20 rows**, runs validations per column (date parses, amount is numeric, order_id format, required fields present) and shows failures inline. Fields with confidence < 0.7 or validation failures are highlighted and must be confirmed by the user.
- Only **Approve** saves a new version (versioned, old versions kept). **Rollback** makes an earlier version active again. Both write to audit_log.

### 6.4 PII masking (services/pii.py)
Names → first letter + *** + last letter. Phones → first 2 + ****** + last 2. Addresses → city/pincode only. Masked at ingestion; raw PII is never stored.

## 7. Screens (frontend) — every one must have loading, empty and error states and work at 375px width

1. **Login** — clean, centred, shows demo credentials hint only in demo mode (env flag).
2. **Dashboard / Money at risk** — top: 3–4 KPI numbers (money at risk, auto-match %, open claims value, TCS+TDS deducted shown separately and labelled "tax, not leakage"). Main: partner × age-bucket matrix (heat-tinted cells, click a cell → orders filtered). Last run time and duration.
3. **Uploads** — drop zone, choose source, upload history table with row counts, rejected rows, status, duration.
4. **Mapping review** — side by side: source column → canonical field dropdown, confidence badge, AI reason; 20-row preview with validation errors inline; Approve / Cancel. Mapping versions list per source with Rollback.
5. **Orders (reconciliation)** — virtualised table, filters: partner, status, age bucket, search order ID. Difference column right-aligned, tabular numerals, red for negative. Row click → side drawer with expected breakdown vs received, evidence lines (file, row, values), TCS/TDS shown separately.
6. **Rate cards** — per partner, effective date, fees, slabs table; edit (finance exec only), audit logged; recompute hint after edit.
7. **Claims** — grouped by partner with totals; claim detail with items; status change (finance exec only); **Export evidence** as CSV and as a clean PDF summary.

Navigation: left sidebar on desktop, bottom sheet / hamburger on mobile. Co-founder never sees controls they cannot use (hide, don't disable) and the API also enforces it.

## 8. Design system (client values minimal, purposeful design — design counts as much as features)

- Restrained palette: near-white background, slate/zinc neutrals, ONE accent colour (deep indigo or teal) for primary actions. Semantic colours used only for meaning: red = money lost/at risk, amber = needs attention, green = settled. Never decorative colour.
- Type: Inter (or Geist), clear hierarchy, `tabular-nums` for all money columns, ₹ formatted in Indian grouping (₹1,23,456.00).
- Generous white space, 8px spacing grid, subtle borders instead of heavy shadows, rounded-lg.
- Tables are the main workspace: sticky header, compact but readable rows, differences and at-risk amounts stand out, everything else is calm.
- Filters simple: a few dropdowns/chips at the top, plus "clear filters". No complex query builders.
- Nothing on screen without a purpose. No lorem ipsum, no stock images, no fake charts.
- Support light mode well; dark mode optional.

## 9. Security and quality rules

- **No secrets in the repo.** All config from env vars; commit `.env.example` with names only. Never print secrets in logs.
- Validate every input with Pydantic; limit upload size (e.g. 50 MB) and types (.csv, .xlsx); reject formula-injection in exports (prefix cells starting with = + - @).
- Role enforced server-side on every endpoint; tests prove a co-founder gets 403 on write endpoints.
- CORS restricted to the frontend origin. Basic rate limiting on login.
- Code style: simple, readable names (`expected_amount`, `received_amount`, `difference`), small functions, short helpful comments, no clever one-liners. Type hints in Python, strict TypeScript.

## 10. Tests (pytest; must pass before each milestone commit)

- Expected-amount engine: the three brief sample rows give exactly 1409, 899, −96.
- Each status rule, including ₹10 boundary (diff of ₹10.00 → settled, ₹10.01 → flagged).
- TCS/TDS never counted in difference.
- Multiple settlement lines per order are summed correctly; duplicate rows handled.
- Mapping: fingerprint reuse, LLM invalid JSON → fuzzy fallback, validation catches bad dates/amounts, rollback restores previous version.
- PII masking.
- Access control: co-founder blocked from write endpoints.
- Performance test (marked slow): 100k rows under 60 s.

## 11. Sample data (scripts/generate_sample_data.py)

- Generate a realistic month: partners from A1, ~30,000 orders, 55% COD on website, realistic values around ₹1,200, weights, pincodes, fake masked customers (never real people).
- Generate partner files in **different formats per partner** (different header names, date formats like DD-MM-YYYY vs ISO, amounts with/without commas, one Excel, others CSV) so mapping is genuinely needed.
- Inject leakage of ~1.5% by value across: unremitted COD, short commission, wrong weight slab, lost returns.
- Also produce one "format changed" version of a partner file (renamed/reordered columns) to demo AI mapping.
- Include the 3 brief sample orders exactly.
- `scripts/seed.py` creates partners, rate cards, the two demo users, and runs one full reconciliation so the app is never empty on first login.

## 12. Demo users (seeded; put the same in deployment.md later)
- finance@paytrace.demo / role finance_exec
- founder@paytrace.demo / role cofounder
- Passwords come from env vars `DEMO_FINANCE_PASSWORD` and `DEMO_FOUNDER_PASSWORD` at seed time (document chosen demo passwords in deployment.md only, not in code).

## 13. Git workflow (reviewers read the history)

- `git init` at the start. Small, meaningful commits with clear messages (`feat: rate card expected amount engine`, `test: status boundary cases`, `fix: ...`). Commit after every working step — never one giant commit.
- Never commit `.env`, uploads, large benchmark files or node_modules.

## 14. Milestones — do them in order, stop after each and summarise what was done, what is left, and any new assumptions

1. **Foundation:** repo layout, .gitignore, docker-compose Postgres, FastAPI skeleton with health check, SQLAlchemy models + Alembic migration, auth with two roles, Next.js skeleton with design tokens, layout shell and login screen.
2. **Expected-amount engine + rate cards:** models, seed rate cards reproducing the 3 sample rows, pure engine + tests, rate card API + screen.
3. **Sample data generator + seed script.**
4. **Upload + parsing + AI column mapping:** fingerprinting, LLM + fuzzy suggesters, 20-row preview with validation, approve, versions, rollback, rejected-rows report. Tests.
5. **Matching engine + benchmark:** Polars pipeline, COPY writes, statuses, recon runs, benchmark script and docs/BENCHMARK.md. Tests.
6. **Orders screen + order detail drawer.**
7. **Claims:** auto-creation from flagged results grouped by partner, status changes with audit, CSV + PDF evidence export.
8. **Money-at-risk dashboard.**
9. **Polish pass:** loading/empty/error states everywhere, mobile layouts, accessibility basics (labels, focus, contrast), consistent spacing and typography.
10. **Deploy:** Render + Vercel + Neon, README with local run steps, `.env.example`, draft `deployment.md`.
11. **Optional depth (only if everything above is solid):** returns tracker screen, AI suggested-match review queue, partner-wise TCS/TDS summary.

When unsure about anything the brief does not specify: choose the simplest reasonable option, record it in docs/ASSUMPTIONS.md, and keep going. Ask me only for decisions that cannot be undone or that change scope.

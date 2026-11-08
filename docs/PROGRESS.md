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

## Milestone 9 — Polish pass
- Every screen checked at 375 px (dashboard, orders, claims list and detail, rate cards, uploads, mobile menu) by loading each page in a 375 px same-origin frame. Fixed: order filters now fill their grid cells on phones, age labels shortened, empty matrix totals show "—" instead of ₹0, PDF columns spaced with repeating headers, the drawer widened (the Sheet's own width variant had won on specificity).
- Every screen has loading (skeletons), empty and error (retry) states. Error and empty copy says what to do next.
- Co-founder checked in the browser: no Uploads nav, no rate-card edit, no claim status actions, no Run reconciliation; exports still work. The API enforces the same rules (route sweep test).
- Accessibility basics: labelled inputs and selects, visible focus rings, skip link, `aria-current` navigation, keyboard-operable table rows (Enter/Space opens the drawer), dialog titles, tooltips and aria-labels on heat-map cells, colour never alone (status pills carry text). Light theme tokens chosen for AA contrast; the `dark:` variant is class-based so the OS theme cannot half-darken the UI.
- 280 backend tests pass; frontend lint and production build are clean.

## Milestone 10 — Deployment prep
- `render.yaml` blueprint for the API (Python 3.13, `alembic upgrade head` on start, `/health` check, generated JWT secret, secrets entered in the dashboard only). Vercel needs no config file: root directory `frontend`.
- Backend: accepts Neon/Render `postgres://` URLs (adds the psycopg driver), several frontend origins, API docs switchable off, security headers (`nosniff`, `DENY`, `no-referrer`, `no-store`). Frontend: security headers, no `x-powered-by`, optional `/api` proxy mode (tested locally: login cookie through the proxy).
- `deployment.md`: exact steps for Neon, seeding from your machine, Render, Vercel; demo accounts; the direct vs proxy cookie trade-off; a post-deploy checklist. README rewritten. `.env.example` lists every variable (names only).
- Secret scan: no keys or passwords tracked; `.env` and `frontend/.env.local` are ignored.
- Tests: 287 pass (5 new config/header/CORS tests), plus the slow 1-lakh test.

## Milestone 10b — Real Gemini column mapping (tested with a live API key)
- **First run failed silently:** `gemini-2.5-flash` answers 404 "no longer available to new users", so every suggestion fell back to fuzzy matching. The fallback worked as designed (the user saw "AI unavailable, showing best guesses"), but the AI was never used. Fixed: the model is configurable, defaulting to `gemini-3.1-flash-lite` with a low thinking level. Thought parts in the reply are skipped, and one retry is made on 500/503 overload but not on 429 quota.
- **Evaluation** (`scripts/eval_ai_mapping.py`): every sample layout is treated as new (as when a partner changes format) and scored against the known-correct mapping. Two deliberately hard layouts were added: a settlement report with cryptic headers (`Amt1`, `Chg`, `Tax A`, `Tax B`, `Amt2`) and a COD file with decoys (an `Order Value` column beside `Collected`, and a `Batch Date` column holding week codes).

| Model | Files | Fields right | Time per file | Notes |
|---|---|---|---|---|
| gemini-3.1-flash-lite (default) | 18 sample + 2 hard | **194 / 194** | median 2.6 s, min 2.0 s, max 3.5 s (one 18 s outlier: a timeout, then a successful retry) | confidence 0.80–1.00 |
| gemini-3.5-flash | 10 that got through | 108 / 108 | 3.3–11.6 s | free tier: 20 requests/day, then 429 |
| fuzzy fallback | 18 sample + 2 hard | 190 / 194 | 0.1–1.2 s | misses on the cryptic layout |

- **What the AI got wrong, and how it was caught.** Before the prompt fix, flash-lite mapped `Tax A` → TCS and `Tax B` → TDS (swapped) at confidence **0.70**. The review threshold is "below 0.7", and both columns hold valid amounts, so neither the confidence rule nor cell validation flagged it. It would have gone through. Two fixes followed:
  1. Rule-based plausibility checks on the 20 preview rows (`services/mapping_checks.py`, A40): TCS smaller than TDS → both fields flagged with "'Tax A' is about 0.50% of gross, 'Tax B' about 0.10%… may be swapped". Gross − deductions ≠ net in at least half the rows → net flagged. Re-run: the swap was flagged on both fields and could not be approved without confirming. No false alarms on the 6 genuine settlement layouts.
  2. The prompt now states that TCS (~0.5%) is larger than TDS (~0.1%). The model then mapped the cryptic layout correctly (0.80 confidence, reason: "Tax B is larger than Tax A, consistent with TCS being larger than TDS").
- **Fuzzy fallback on the hard layout** mapped Order ID to `Ref`, a partner reference shaped like an order ID, at 0.90 confidence, and left TCS and Reference unmapped. Net was flagged (required field missing). That `Ref` pick is not caught by any check. The user would see the wrong IDs in the preview, and reconciliation would show those lines as unmatched. Accepted: fuzzy is only the fallback, and its notice tells the user to check every field.
- **End to end through the API** (`POST /uploads/inspect` with the format-changed Marketplace 1 file, real key): review screen with `engine=llm`, 9/9 fields at confidence 1.0 with reasons, 0 preview errors, **2.8 s** for the request. Approve saved v2. Processing read 6,476 rows, all recognised as already stored (0 double-counted), in 0.3 s. Then rolled back to v1 to keep the demo state.
- **No PII sent:** unchanged. Only headers and 5 masked rows go out (existing test). The key travels in a header and is never logged.
- Tests: 295 backend tests pass (8 new: overload retry, no retry on quota, thought parts and thinking level, five plausibility-check cases).

## Milestone 10c — Deployment defaults: proxy mode
- **Proxy mode is now the deployment default.** The browser talks only to Vercel, which forwards `/api/*` to Render. The session cookie is first-party (`SameSite=Lax`), so sign-in works in Safari and on phones. `render.yaml` presets `COOKIE_SAMESITE=lax` and `FORWARDED_HOPS=2`. `deployment.md` gives the Vercel variables (`NEXT_PUBLIC_API_URL=/api`, `BACKEND_URL`), states the about 4.5 MB upload limit through the proxy, and explains how a shared domain removes it. The browser refuses files over 4 MB with a clear message (`NEXT_PUBLIC_MAX_UPLOAD_MB` overrides it).
- `deployment.md`: the repository must be public, and reviewers open the backend `/health` first because Render's free plan sleeps.
- **Fixed: login rate limit behind proxies.** It keyed on the socket address, which behind Render is the load balancer for everyone, so five wrong passwords from anyone would have locked a demo account for every reviewer. It now reads the client IP from `X-Forwarded-For`, counting trusted hops from the right (test added).
- Verified locally with a production build in proxy mode: login sets a first-party `SameSite=lax` cookie, and every screen loads through `/api` with no direct calls to the API origin. (Lesson for Windows: Git Bash rewrites `NEXT_PUBLIC_API_URL=/api` into a Windows path at build time. Build from PowerShell or set `MSYS_NO_PATHCONV=1`. Vercel is unaffected.)

## Milestone 11 — Premium frontend polish
- **Motion** (`motion`, LazyMotion, OS reduce-motion respected): pages fade in on navigation; the drawer slides in, becoming a bottom sheet on phones; dialogs, menus and selects fade and scale in 150 ms; claim rows and the waterfall's bars stagger in once; KPI numbers count up; matrix cells fade in with a slight stagger.
- **Skeletons shaped like each screen** (KPI cards, matrix grid, table columns, drawer waterfall, claim rows) instead of spinners.
- **Optimistic updates with rollback:** claim status changes, mapping approve and rollback, each with a short toast ("Claim #3 marked filed", "Mapping v3 approved for …", "Mapping v1 is active again") and an error toast that restores the previous state.
- **Command palette (Ctrl/Cmd+K):** jump to any screen, live order search by ID or AWB (opens the order), each partner's claim, run reconciliation (finance only), switch theme, shortcuts, sign out.
- **Orders table:** status chips with live counts (`status_counts`, a new additive API field) and one-click clear; filters and the open order in the URL; breadcrumb back to the dashboard cell; ↑/↓, Home/End, Enter, Esc and `/` shortcuts with a `?` sheet; memoised virtual rows in pages of 500; details prefetched on focus.
- **Order drawer:** "Where every rupee went" as a waterfall: value, then commission, fees and freight, then TCS and TDS shown as credits that are never deducted, then expected vs received and the difference (red only for a shortfall beyond ₹10).
- **Upload:** real upload progress (XHR), then Parsing → Mapping → Matching → Done with the machine time (review time excluded); a smoother drop zone. Mapping review keeps AI reasons in tooltips (as text on phones) and a sticky approve bar above the phone navigation.
- **Visual:** one indigo accent; red, amber and green only for meaning; soft shadows only on floating surfaces; polished focus, hover, cursor and disabled states; an elegant dark mode with a toggle (sidebar, account menu, palette), saved per browser and applied before first paint.
- **Phones (375 px):** bottom navigation; orders, claim items, upload history and reports as card lists; drawers as bottom sheets; controls at least 44 px tall on touch screens.
- **Empty states with one action:** no claims → Run reconciliation; no orders or dashboard → Upload partner reports (finance), explanation only (co-founder).

### Quality checks (production build, proxy mode)
| Page | Preset | Performance | Accessibility | Best practices | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|
| Dashboard | Desktop | **100** | **100** | **100** | 0.8 s | 0 ms | 0 |
| Orders | Desktop | **99** | **100** | **100** | 0.9 s | 10 ms | 0.018 |
| Dashboard | Mobile (4× CPU, slow 4G) | 79 | **100** | **100** | 4.1 s | 330 ms | 0 |
| Orders | Mobile (4× CPU, slow 4G) | 77 | **100** | **100** | 4.4 s | 340 ms | 0.003 |

- **Mobile performance misses the 90 target.** 88% of mobile LCP is render delay: every screen is rendered in the browser after a session check (Decision 11), so on a throttled phone the chain is JS start-up, then `/auth/me`, then the data. Already done: the first screen no longer fades in, overlays load on demand, data loads in parallel with the session check, and about 30 route prefetches were removed (78 → 79 / 75 → 77, run-to-run variance ±3). The real fix is server-rendering the first screen. That is now possible because proxy mode makes the cookie first-party to the Next.js server. It is a larger change, deliberately not taken in a polish pass.
- Accessibility went from 93 to 100. Fixed: `aria-label` on generic elements (loading regions are now `role="status"`); the loss red raised from red-600 to red-700 (4.36:1 → about 6:1 on its pill); grey text on the heat tint; accessible names that did not contain the visible text.
- **Scrolling 30,000 orders** (headless Chrome, unthrottled, 8 s continuous scroll): median frame 7.0 ms, p99 9.5 ms (60 fps needs under 16.7 ms), 1 frame over 33 ms; at most 32 rows in the DOM.
- **Every screen as both roles, light and dark, at 375 px and 1440 px** (52 screenshots, headless Chrome): no sideways scrolling, no console errors. Found and fixed during this check: screen-reader-only labels escaped their scroll containers and widened the page on phones (mobile Chrome zoomed out, hiding the bottom bar); the sticky drawer header covered the close button; "Search or jump to…" wrapped in the sidebar.
- In a real browser: matrix cell → filtered orders with breadcrumb; keyboard ↓↓ Enter opens the third order; Ctrl+K "88120" → the brief's order (₹899 / ₹862 / −₹37); the format-changed upload goes through Parsing → Mapping (matches saved v2) → approve v3 → Done; rollback to v1 is shown at once with its toast.
- Frontend lint and production build clean; 297 backend tests pass (plus the slow 1-lakh test).

## Milestone 12 — Optional depth: returns tracker and review queue

### Returns tracker
- **Screen "Returns"**: every order the courier marked returned or RTO, with partner, courier, return date, days since return, scan status (Received / Waiting, inside the window / Not received, overdue) and value at risk. Overdue rows are tinted red and link to their claim. Summary cards double as status filters, plus courier and age chips with counts and order/AWB search. Phones get a card list.
- **Agrees with matching by construction**: the tracker's "not received" set is exactly the `return_not_received` results (test). New warehouse scans arrive through the existing upload and mapping flow; the reconciliation that follows every upload moves them to Received.
- **Manual receipt** (finance only): "Mark received" with a required note. It is audited, re-matches just that order (`reconcile_orders`), and drops it from its open claim. Co-founders see no button, and the API returns 403.
- **Dashboard card**: not received / waiting / received, linking to the screen.
- **Seed**: about 20 website returns marked in the last few days, so all three states always show (A47).

### Review queue for lines without an order ID
- **Sample data**: 82 of about 33,000 settlement and COD lines arrive without an order ID or AWB, including 3 deliberately look-alike pairs. Their references no longer contain the order number. Off by default in `generate()`, so the benchmark and older tests are unchanged.
- **Ingestion**: those lines go to `unmatched_lines` instead of being rejected (A43). The ledger is untouched until a person decides.
- **Step 1, rules** (vectorised, deterministic, A45): up to five candidates per line by partner, unpaid status, amount tolerance, date window and AWB.
- **Step 2, AI**: Gemini ranks the shortlist with a confidence and a one-line reason. It sees amounts, dates, AWB and partner only, never customer data (test). Any failure, or no key, falls back to the rule order, and the screen says why.
- **Measured, then designed** (`scripts/eval_match_suggestions.py`, A46):

  | | Right order shortlisted | Suggestion right | Wrong at ≥ 0.9 confidence |
  |---|---|---|---|
  | Rules only | 82 / 82 | 61 / 82 | 0 |
  | Gemini choosing freely (two prompt versions) | 82 / 82 | 47–51 / 82 | **5** before the cap, 0 after |
  | Gemini, final (breaks ties, capped by evidence) | 82 / 82 | 61 / 82 | 0 |

  The other 21 lines are exact ties: two or more orders with the same partner, value and due date, which no method can separate. They show at 50% and wait for a person. Gemini was wrong every time it overruled a clear rule winner. So in the final design it breaks exact ties and writes the reason, never overrules the rules, and never raises confidence above what the evidence supports. The measurement also exposed a real bug: candidates' due dates used the sales channel's settlement cycle instead of the courier's for COD lines (fixed).
- **Screen "Review queue"**: each line with its suggested order, confidence, engine (AI + rules / Rules), reason, and a side-by-side comparison (amount, date, AWB, partner) that follows the selected candidate. Actions: Accept, Accept another candidate, Reject (with a note). Bulk accept only for lines at ≥ 0.9 confidence, behind a confirmation. Accepted and Rejected tabs show who decided and when.
- **Accepting** writes the line to the ledger with the hash it would have had with an order ID (so a corrected re-send is a duplicate). It re-matches only that order, refreshes claims, re-shortlists other lines that suggested the same order, and writes the audit log. Nothing is ever linked automatically (test).
- **Counts**: open lines in the sidebar badge, the phone bar and a dashboard card. Uploads write rule suggestions at once; AI ranking runs after the response and the screen polls while it is pending.
- **Phones**: the bottom bar keeps five targets (At risk, Orders, Review, Claims, More); Returns, Uploads and Rate cards sit in the "More" sheet.

### Checks
- Backend: 337 tests pass (336 regular + the slow 1-lakh test at 21.5 s); 39 are new (returns 15, review queue 24). Older upload and parsing tests now count queued lines next to saved ones.
- Frontend lint and production build (proxy mode) clean.
- Click-through (production build, proxy mode): finance dashboard → Returns card → Waiting filter → Mark received on an overdue return (toast; overdue 149 → 148, claim updated) → Review queue → Accept the top suggestion (order unpaid → settled, queue 82 → 81) → a look-alike pair shown at 50% with both candidates. Co-founder: no checkboxes or action buttons on either screen. At 375 px in light and dark: no sideways scrolling on Review, Returns or the dashboard; no console errors.
- Real Gemini run during seeding: 82 lines ranked in about 45 s (11 requests of up to 8 lines).

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

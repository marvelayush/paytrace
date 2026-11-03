# Design decisions

A short log of choices and why. Newest at the bottom.

1. **Money as integer paise (BIGINT).** No floating-point rounding in matching. Converted to ₹ only for display. (A10)
2. **Surrogate keys where the spec lists none.** `upload_row_errors`, `claim_items` and `audit_log` get an `id`. `recon_results` uses `(run_id, order_id)` as its primary key because a run has exactly one result per order.
3. **Postgres enums as CHECK-constrained text, not native ENUM types.** Adding a status later is then a one-line migration with no `ALTER TYPE` problems.
4. **Auth with a JWT in an httpOnly cookie.** The token is never readable by JavaScript, which removes the XSS token-theft risk. `SameSite` and `Secure` come from env vars because the deployed frontend and backend run on different domains (decided at the deploy milestone).
5. **Role check as a FastAPI dependency (`require_role`).** A test sweeps the whole route table, so any new POST/PUT/PATCH/DELETE route that forgets the finance-only guard fails CI.
6. **bcrypt used directly** (not passlib, which is unmaintained and breaks with bcrypt 4.x).
7. **A separate `paytrace_test` database** is created by docker-compose so pytest never touches dev data.

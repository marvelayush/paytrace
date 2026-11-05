# Deploying PayTrace

Three free-tier services: **Neon** (Postgres), **Render** (FastAPI backend), **Vercel** (Next.js frontend).
Everything below is clicks and copy-paste. Nothing secret is stored in the repository.

## For reviewers: open the backend first

The backend runs on Render's free plan, which **sleeps after 15 minutes without traffic**. The first request then takes 30–60 seconds while it wakes up.

1. Open **`https://<your-service>.onrender.com/health`** and wait until it shows `{"status":"ok","database":"ok"}`.
2. Then open the app at **`https://<your-project>.vercel.app`** and sign in with a demo account below.

(Replace the two URLs above with the live ones once deployed.)

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Finance executive (full access) | `finance@paytrace.demo` | `PayTrace-Finance-2026` |
| Co-founder (read-only) | `founder@paytrace.demo` | `PayTrace-Founder-2026` |

These are set when the database is seeded (step 2). They are demo credentials meant to be shared with reviewers. Change them by re-running the seed with other values.

---

## 0. GitHub: the repository must be public

The assessment requires a **public** repository: reviewers read the code and the commit history.

1. github.com → **New repository** → name `paytrace` → visibility **Public** → do not add a README, .gitignore or licence (the repo has them).
2. From the repository root:
   ```bash
   git remote add origin https://github.com/<your-user>/paytrace.git
   git push -u origin main
   ```
3. Before pushing, confirm nothing secret is tracked: `git ls-files | grep -i env` should list only `.env.example`.

## 1. Database: Neon

1. Sign in at neon.tech → **New project** → name `paytrace`, Postgres 16, region **AWS Asia Pacific (Singapore)** (closest to Render's Singapore region).
2. On the project dashboard open **Connect**, turn **Connection pooling off**, and copy the connection string.
   It looks like `postgresql://USER:PASSWORD@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.
   (The app adds the `psycopg` driver itself. Use the direct connection: the pipeline uses temporary tables and COPY.)

## 2. Create the schema and load the demo data (from your machine)

From the repository root, with the backend virtualenv installed (see README):

```bash
cd backend
DATABASE_URL="<Neon connection string>" .venv/Scripts/alembic upgrade head        # macOS/Linux: .venv/bin/alembic
cd ..
DATABASE_URL="<Neon connection string>" \
DEMO_FINANCE_PASSWORD="PayTrace-Finance-2026" \
DEMO_FOUNDER_PASSWORD="PayTrace-Founder-2026" \
backend/.venv/Scripts/python scripts/seed.py --reset                              # macOS/Linux: backend/.venv/bin/python
```

PowerShell users: set each variable first with `$env:DATABASE_URL = "<…>"` and so on, then run the two commands without the prefixes.

This loads the 15 sample partner reports through the real upload pipeline, reconciles 30,000 orders and opens the claims. Over the internet to Neon it takes about a minute.

## 3. Backend: Render

1. Render dashboard → **New → Blueprint** → pick the GitHub repository. Render reads `render.yaml` and proposes the service `paytrace-api`.
2. Fill in the values Render asks for:
   - `DATABASE_URL`: the Neon string from step 1
   - `FRONTEND_ORIGIN`: leave as `https://example.com` for now; you set the real one after step 4
   - `GEMINI_API_KEY`: create one at aistudio.google.com → *Get API key*. Optional: without it, column mapping falls back to fuzzy matching and says so on screen.
3. Everything else is preset in `render.yaml` for proxy mode: `COOKIE_SAMESITE=lax`, `COOKIE_SECURE=true`, `FORWARDED_HOPS=2`, `GEMINI_MODEL=gemini-3.1-flash-lite`, a generated `JWT_SECRET`, API docs off.
4. **Apply**. The first build takes a few minutes. When it is live, open `https://<your-service>.onrender.com/health`. It should show `{"status":"ok","database":"ok"}`.

## 4. Frontend: Vercel (proxy mode)

1. Vercel dashboard → **Add New → Project** → import the same repository.
2. **Root Directory**: `frontend` (framework preset: Next.js, detected automatically).
3. Environment variables (Production):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `/api` |
   | `BACKEND_URL` | `https://<your-service>.onrender.com` (no trailing slash) |
   | `NEXT_PUBLIC_DEMO_MODE` | `true` (shows the demo-account hint on the login screen) |

4. **Deploy**. Copy the production URL, e.g. `https://paytrace-xyz.vercel.app`.
5. Back in Render → `paytrace-api` → **Environment** → set `FRONTEND_ORIGIN` to that URL (no trailing slash) → **Save, rebuild and deploy**.

Open the Vercel URL and sign in with a demo account. If you change `BACKEND_URL` later, redeploy on Vercel: the forwarding rule is fixed at build time.

## Why proxy mode, and the upload limit

The session lives in an httpOnly cookie set by the API. The frontend (`vercel.app`) and the backend (`onrender.com`) are different sites. If the browser called Render directly, the cookie would be a third-party cookie. **Safari, iPhones and every browser that blocks third-party cookies would drop it, and users could not stay signed in.**

In **proxy mode** the browser only talks to the Vercel site. Vercel forwards `/api/*` to Render, so the cookie is first-party (`SameSite=Lax`) and sign-in works in every browser, on phones too.

**The trade-off, stated plainly: uploads pass through Vercel's proxy, which limits a request body to about 4.5 MB.**
- The app checks this in the browser and refuses files over **4 MB** with a clear message, instead of a confusing server error.
- Every demo sample file is under 2 MB (the largest, `website_orders.csv` with 12,000 orders, is 1.8 MB), so the whole demo works.
- A real month at the client's volume (30,000 orders, 1–2 MB per partner report) also fits. A report over 4 MB must be split by date range.
- The **1 lakh-row benchmark** (about 20 MB of files) is run with `scripts/benchmark_matching.py`, not through the deployed upload screen. Its results are in `docs/BENCHMARK.md`.

**Removing the limit:** put both apps on one domain you own (`app.example.com` on Vercel, `api.example.com` on Render). The cookie is then first-party even when the browser calls the API directly, so use direct mode:
- Vercel: `NEXT_PUBLIC_API_URL=https://api.example.com`, remove `BACKEND_URL`, redeploy.
- Render: `COOKIE_SAMESITE=lax`, `FORWARDED_HOPS=1`.

Uploads then go straight to the backend, up to 50 MB. *Direct mode without a shared domain* (`COOKIE_SAMESITE=none`) works in Chrome, Edge and Firefox only.

## Checklist after deploying

- [ ] The GitHub repository is **public** and opens without signing in
- [ ] `/health` returns ok
- [ ] Sign in as finance on a phone or in Safari: the session survives a page reload
- [ ] The dashboard shows about ₹5.43 L at risk across 7 partners
- [ ] Orders → search `88120` → the drawer shows expected ₹899, received ₹862, −₹37
- [ ] Uploads → Marketplace 1 · Settlement → upload `sample_data/format_changed/marketplace1_settlement_NEW_FORMAT.csv` → the mapping review shows "AI suggested these columns" → approve. If it says "AI unavailable", check `GEMINI_API_KEY` in Render.
- [ ] Claims → a claim → **PDF summary** downloads
- [ ] Sign in as co-founder: no Uploads, no edit buttons; exports still work
- [ ] Replace the two placeholder URLs at the top of this file with the live ones and commit

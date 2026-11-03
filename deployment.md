# Deploying PayTrace (draft)

Three free-tier services: **Neon** (Postgres), **Render** (FastAPI backend), **Vercel** (Next.js frontend).
Everything below is clicks and copy-paste; nothing secret is stored in the repository.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Finance executive (full access) | `finance@paytrace.demo` | `PayTrace-Finance-2026` |
| Co-founder (read-only) | `founder@paytrace.demo` | `PayTrace-Founder-2026` |

These are set when the database is seeded (step 2). They are demo credentials meant to be shared with reviewers. Change them by re-running the seed with other values.

---

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

1. Push this repository to GitHub (private is fine).
2. Render dashboard → **New → Blueprint** → pick the repository. Render reads `render.yaml` and proposes the service `paytrace-api`.
3. Fill in the three values Render asks for:
   - `DATABASE_URL`: the Neon string from step 1
   - `FRONTEND_ORIGIN`: leave as `https://example.com` for now; you set the real one after step 4
   - `GEMINI_API_KEY`: optional. Create one at aistudio.google.com → *Get API key*. Without it, column mapping falls back to fuzzy matching and says so.
4. **Apply**. The first build takes a few minutes. When it is live, open `https://<your-service>.onrender.com/health`; it should show `{"status":"ok","database":"ok"}`.

Note: the free plan sleeps after 15 minutes idle, so the first request after a pause takes about 30–50 s. Open `/health` before a demo.

## 4. Frontend: Vercel

1. Vercel dashboard → **Add New → Project** → import the same repository.
2. **Root Directory**: `frontend` (framework preset: Next.js, detected automatically).
3. Environment variables:
   - `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com`
   - `NEXT_PUBLIC_DEMO_MODE` = `true` (shows the demo-account hint on the login screen)
4. **Deploy**. Copy the production URL, e.g. `https://paytrace-xyz.vercel.app`.
5. Back in Render → `paytrace-api` → **Environment** → set `FRONTEND_ORIGIN` to that URL (no trailing slash) → **Save, rebuild and deploy**.

Open the Vercel URL and sign in with a demo account.

## Cookies and browsers: direct mode vs proxy mode

The session lives in an httpOnly cookie set by the API.

- **Direct mode (the steps above).** The browser calls Render directly, including for uploads, as the spec asks ("uploads go straight to the backend"). The cookie is `SameSite=None; Secure`. This works in Chrome, Edge and Firefox. **Safari and browsers that block third-party cookies will not keep you signed in.**
- **Proxy mode (works everywhere).** Vercel forwards `/api/*` to Render, so the cookie belongs to the Vercel site:
  - Vercel: `NEXT_PUBLIC_API_URL=/api` and `BACKEND_URL=https://<your-service>.onrender.com`, then redeploy.
  - Render: `COOKIE_SAMESITE=lax`.
  - Trade-off: uploads also pass through Vercel's proxy, which limits request bodies to a few MB. All sample files are under 2 MB.
- **Long-term fix:** put both on one domain you own (`app.example.com` on Vercel, `api.example.com` on Render). Then direct mode works with `COOKIE_SAMESITE=lax` in every browser, with no upload limit.

## Checklist after deploying

- [ ] `/health` returns ok
- [ ] Sign in as finance: the dashboard shows about ₹5.43 L at risk across 7 partners
- [ ] Orders → search `88120` → drawer shows expected ₹899, received ₹862, −₹37
- [ ] Uploads → Marketplace 1 · Settlement → upload `sample_data/format_changed/marketplace1_settlement_NEW_FORMAT.csv` → mapping review appears → approve
- [ ] Claims → a claim → **PDF summary** downloads
- [ ] Sign in as co-founder: no Uploads, no edit buttons; exports still work

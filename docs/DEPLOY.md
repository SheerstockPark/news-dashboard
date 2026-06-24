# Deploying the News Dashboard as a live website

Goal: a public URL Neil can open from any browser, backed by a **cloud database** that a
**scheduler keeps fresh 24/7** — a self-updating "living" site.

```
GitHub repo ──deploys──▶ Streamlit Community Cloud  ──reads──▶ Turso (cloud SQLite)
     │                         (the public website)              ▲
     └── GitHub Actions cron ──── every 20 min: fetch news ──────┘  (keeps it fresh)
```

Everything below is **free**. The app falls back to local SQLite automatically when the
Turso variables aren't set, so local development is unchanged.

---

## 1. Turso — the cloud database (~5 min)

1. Sign up at **https://turso.tech** (GitHub login is easiest).
2. Install the CLI and create a database (or use the web dashboard → **Create Database**):
   ```bash
   curl -sSfL https://get.tur.so/install.sh | bash
   turso auth login
   turso db create news-dashboard
   turso db show news-dashboard --url          # -> TURSO_DATABASE_URL (libsql://...)
   turso db tokens create news-dashboard        # -> TURSO_AUTH_TOKEN
   ```
3. Keep both values handy — they're the only secrets the database needs.

**Verify it works** before going further:
```bash
TURSO_DATABASE_URL="libsql://..." TURSO_AUTH_TOKEN="..." .venv/bin/python tools/db_check.py
```
You should see `Backend: turso` and `Connected OK ✅`. (Schema is created on first connect.)

> Tip: seed the cloud DB with your local history once:
> `TURSO_... python tools/fetch_rss.py` — or just let the cron fill it over a few hours.

---

## 2. GitHub — the code home (~3 min)

1. Create a repo at **https://github.com/new** (Private is fine; see the cron note below).
2. Push this project:
   ```bash
   git remote add origin https://github.com/<you>/news-dashboard.git
   git branch -M main
   git push -u origin main
   ```

---

## 3. Streamlit Community Cloud — the public site (~3 min)

1. Go to **https://share.streamlit.io** → sign in with GitHub → **New app**.
2. Pick the repo/branch; set **Main file path** to `dashboard/app.py`.
3. **Advanced settings → Secrets** — paste (TOML):
   ```toml
   TURSO_DATABASE_URL = "libsql://news-dashboard-<you>.turso.io"
   TURSO_AUTH_TOKEN   = "eyJ..."
   # optional, enables the AI features (Brief / Ask / sentiment):
   ANTHROPIC_API_KEY  = "sk-ant-..."
   # optional, EIA inventories:
   EIA_API_KEY        = "..."
   ```
4. **Deploy.** You'll get a public `https://<app>.streamlit.app` URL — that's Neil's link.

The app reads these secrets as environment variables (bridged in `app.py`), so the same
code path runs locally (via `.env`) and in the cloud (via Streamlit secrets).

---

## 4. GitHub Actions — keep it living (~3 min)

1. In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` (+ optionally `ANTHROPIC_API_KEY`,
   `EIA_API_KEY`, and the `SMTP_*` / `DIGEST_*` set for the daily email).
2. The workflow `.github/workflows/ingest.yml` then runs every 20 min, fetching news into
   Turso and pruning rows older than 14 days. Trigger a first run manually:
   **Actions → "Ingest news → Turso" → Run workflow.**

**Free-minutes note:** a public repo gets unlimited Actions minutes. A *private* repo gets
2,000 min/month — `*/20` may exceed that, so widen the cron to `*/30` (edit `ingest.yml`),
or make the repo public.

---

## 5. Switching AI on later

No redeploy needed — just add `ANTHROPIC_API_KEY` to the Streamlit secrets (for the in-app
Brief/Ask buttons) and to the Actions secrets (for scheduled enrichment/digest). The app
picks it up on its next rerun.

---

## What runs where (summary)

| Piece | Where | Needs |
|---|---|---|
| Website (dashboard) | Streamlit Community Cloud | repo + Turso secrets |
| Database | Turso | account + DB token |
| Continuous ingest | GitHub Actions cron | Turso secrets |
| Daily digest email | GitHub Actions cron | SMTP/Turso secrets |
| Local dev | your Mac (SQLite) | nothing — Turso vars unset |

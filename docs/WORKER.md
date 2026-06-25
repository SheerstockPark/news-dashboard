# Always-on alert worker — genuinely instant (~1 min) urgent emails

GitHub Actions can't run faster than ~5 min and isn't punctual. For *true* near-instant
urgent alerts, run a tiny always-on worker that loops every 60 seconds:

```
python tools/run_alerts.py --urgent --fetch --loop --interval 60
```

Every minute it pulls fresh feeds into Turso and emails any **very-big NEW** headline. The
dedupe lives in Turso, so a story still emails at most once. The `Procfile` already declares
this as the `worker` process.

## Recommended host: Railway (simplest, ~$5/mo hobby)

1. Go to **railway.app** → sign in with GitHub.
2. **New Project → Deploy from GitHub repo →** pick `SheerstockPark/news-dashboard`.
3. Railway detects Python + the `Procfile` and starts the `worker` process (no web port needed).
4. Open the service → **Variables** → add the same secrets the dashboard/cron use:
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
   - `DIGEST_TO`  (e.g. `neil@sheerstockpark.com`)
   - **Email backend — one of:**
     - Gmail/SMTP: `SMTP_USER`, `SMTP_PASS`, and optionally `SMTP_HOST`, `SMTP_PORT`, `DIGEST_FROM`
     - or Resend: `RESEND_API_KEY` (+ optional `DIGEST_FROM`)
5. **Deploy.** Watch the logs — first run prints `Baselined N existing articles` (no backlog
   blast), then `Urgent: 0 emailed` each minute until something big breaks.

The worker uses ~256–512 MB and runs 24/7; a tiny service like this fits the Railway hobby
plan (~$5/mo). **Fly.io** and **Koyeb** also work (Koyeb has a free nano instance) — same
command and env vars, via their Dockerfile/buildpack flow.

## After the worker is confirmed running

Disable the GitHub urgent-cron so the two aren't both checking (the Turso dedupe prevents
double-sends, but there's no need to run both): edit `.github/workflows/alerts.yml` and
comment out the `schedule:` block, leaving `workflow_dispatch` for manual runs. Keep
`ingest.yml` (it also prunes old rows) and `briefing.yml` (the 6am/8pm emails) running.

## What stays on GitHub Actions

- **`briefing.yml`** — the 6am/8pm briefings (time-scheduled; instant isn't relevant).
- **`ingest.yml`** — baseline feed pull + prune (the worker also fetches, this is backup).
- **`enrich.yml`** — hourly AI sentiment scoring.

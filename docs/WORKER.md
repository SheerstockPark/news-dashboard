# Always-on worker — punctual briefings + genuinely instant (~1 min) urgent alerts

GitHub Actions `schedule:` is **best-effort**: it openly delays or drops cron events. On this
repo it was silently missing the 06:00/20:00 briefings *and* never firing the urgent-alert cron
at all. The fix is one tiny always-on worker that owns everything time-sensitive, so GitHub is
just backup.

`tools/worker.py` runs a single 60-second loop. Each tick it:

1. Pulls fresh feeds into Turso.
2. Emails any **very-big NEW** headline — instant urgent alerts (~1 min, not 15).
3. At **06:00 UK** sends the Morning briefing; at **20:00 UK** the Evening one — fired by a real
   clock, not GitHub's scheduler.

```
python tools/worker.py --interval 60
```

All dedupe lives in Turso, so a restart never double-sends or re-blasts a backlog:
urgent alerts dedupe per-article (scope `urgent`); briefings dedupe per-day
(scope `briefing-morning` / `briefing-evening`, keyed on the UK date). Briefings use a catch-up
window — Morning fires anytime in [06:00, 12:00) if it hasn't gone yet today, so a 06:00 outage
still delivers when the worker wakes (exactly the miss we just had). The `Procfile` declares this
as the `worker` process.

## Recommended host: Railway (simplest, ~$5/mo hobby)

1. Go to **railway.app** → sign in with GitHub.
2. **New Project → Deploy from GitHub repo →** pick `SheerstockPark/news-dashboard`.
3. Railway detects Python + the `Procfile` and starts the `worker` process (no web port needed).
4. Open the service → **Variables** → add the same secrets the dashboard/cron use:
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
   - `ANTHROPIC_API_KEY`  (the briefings need this)
   - `DIGEST_TO`  (e.g. `neil@sheerstockpark.com,saavan.s98@gmail.com`)
   - `EIA_API_KEY`  (optional — inventory/reserve numbers in the brief)
   - **Email backend — one of:**
     - Gmail/SMTP: `SMTP_USER`, `SMTP_PASS` (+ optional `SMTP_HOST`, `SMTP_PORT`, `DIGEST_FROM`)
     - or Resend: `RESEND_API_KEY` (+ optional `DIGEST_FROM`)
5. **Deploy.** Watch the logs:
   - `Worker up. Email backend: smtp …` on boot.
   - First urgent pass prints `Baselined N existing articles` (no backlog blast).
   - Then `ingest: … new` + `urgent: 0 emailed` each minute until something big breaks.
   - At 06:00/20:00 UK: `Morning briefing due … sent + marked`.

The worker uses ~256–512 MB and runs 24/7 — fits the Railway hobby plan (~$5/mo). **Fly.io** and
**Koyeb** also work (Koyeb has a free nano instance) — same command and env vars via their
buildpack/Dockerfile flow.

## After the worker is confirmed running

The worker is now the single source of truth for sends, so disable the GitHub `schedule:` blocks
(keep `workflow_dispatch` for manual catch-up runs):

- `.github/workflows/alerts.yml` — comment out `schedule:` (worker does urgent now).
- `.github/workflows/briefing.yml` — comment out `schedule:` (worker does briefings now).

Keep these on GitHub Actions:
- `ingest.yml` — baseline feed pull + prune of old rows (the worker also fetches; this is backup).
- `enrich.yml` — hourly AI sentiment scoring.

> Why disable rather than leave as backup: urgent alerts dedupe across both safely (per-article),
> but the GitHub briefing path doesn't check the per-day scope, so if GitHub's scheduler ever
> revived you could get a duplicate briefing. One owner = no doubles.

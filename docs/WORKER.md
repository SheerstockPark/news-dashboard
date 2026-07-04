# Time-sensitive sends — current architecture (and the retired worker)

> **Status July 2026: no always-on host is used — and none is needed.** This file previously
> documented deploying `tools/worker.py` on Railway/Koyeb. Both paths are retired: **Railway
> blocks outbound SMTP** (every send failed with `[Errno 101]`; project deleted) and **Koyeb
> dropped its free tier** ($29/mo paywall at signup). Everything now runs on free GitHub
> infrastructure. Do not follow old copies of this runbook.

## What runs where today

| Job | Mechanism | Latency / schedule |
|---|---|---|
| 🚨 Urgent alerts | `.github/workflows/urgent-loop.yml` — hourly relay, each run polls every 60s for ~58 min (public repo = free unlimited runner minutes) | ~1 min |
| 🚨 Urgent backup | `.github/workflows/alerts.yml` — independent */15 sweep covering relay gaps | ≤15 min |
| 🌅🌆 Briefings | Scheduled Claude routines (subscription, no API credit) write the prose → dispatch `briefing.yml` → GitHub runner emails via SMTP. See `docs/ROUTINES.md` + `docs/routine-prompts/` | 06:00 / 20:00 UK |
| 📄 Weekly Desk Review | Same routine mechanism, `edition=Weekly` | Sat 09:00 UK |
| 🐕 Watchdog | `.github/workflows/watchdog.yml` — fails loudly if no confirmed delivery in 26h | 2×/day |

Safety properties: every sender marks confirmed deliveries in Turso (`alert_state`), so any
combination of senders is double-send-proof, and the watchdog reads the same marks.

## If an always-on host is ever wanted again

`tools/worker.py` still works and does everything in one 60s loop (ingest + instant urgent +
punctual briefings). Requirements for a host: **outbound SMTP not blocked** (or set
`RESEND_API_KEY` — HTTPS — instead), env vars `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`,
`SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`, `DIGEST_FROM` (+ `ANTHROPIC_API_KEY` only if the worker
should also generate briefings, `BRIEFING_EXTRA_TO` for briefing-only recipients). It answers
health checks on `$PORT` for hosts that require a web service. The `Procfile` declares it —
and must stay a single line: Railway parsed comment lines containing colons as extra services.

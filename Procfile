# Always-on worker for genuinely near-instant (~1 min) urgent email alerts.
# Loops every 60s: pull fresh feeds into Turso, then email any very-big NEW headline.
# Deploy on Railway / Fly / Koyeb (see docs/WORKER.md). Dedupe lives in Turso, so this and
# the GitHub urgent-cron never double-send — but disable .github/workflows/alerts.yml once
# this worker is confirmed running to avoid redundant checks.
worker: python tools/run_alerts.py --urgent --fetch --loop --interval 60

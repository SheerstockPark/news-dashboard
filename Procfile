# Always-on worker — owns everything time-sensitive (GitHub's cron is just backup).
# One 60s loop: pull fresh feeds → email any very-big NEW headline (instant urgent alerts) →
# send the 06:00 / 20:00 UK briefings punctually. All dedupe lives in Turso, so a restart never
# double-sends. Deploy on Railway / Fly / Koyeb (see docs/WORKER.md). Once it's confirmed
# running, disable the GitHub `schedule:` blocks in briefing.yml + alerts.yml (keep
# workflow_dispatch) so only the worker drives sends.
worker: python tools/worker.py --interval 60

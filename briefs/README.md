# Briefing prose drop-zone

The scheduled Claude routine commits `pending-morning.md` / `pending-evening.md` here when it
cannot dispatch briefing.yml directly. The push fires the workflow, which renders + emails the
prose (per-day DB dedupe prevents doubles). Files are overwritten each day — history lives in git.

#!/usr/bin/env python3
"""Deadman switch — exit non-zero if no briefing has been DELIVERED recently.

The system has now failed silently twice (GitHub cron silently dropping schedules; Railway
silently blocking SMTP): everything looked green while nothing reached an inbox. This check
watches the one signal that only exists on confirmed delivery — the worker marks
alert_state scope 'briefing-morning'/'briefing-evening' *after* mailer.send_html() succeeds.

Run it from a scheduled GitHub Action: if the newest briefing mark is older than the
threshold (or there has never been one), the run FAILS, and GitHub emails the repo owner —
a notification channel completely independent of our own email pipeline.

Usage:
    python tools/check_heartbeat.py                 # default: fail if > 26h since last briefing
    python tools/check_heartbeat.py --max-hours 30

Needs TURSO_DATABASE_URL + TURSO_AUTH_TOKEN (falls back to the local SQLite DB without them,
which is only useful for testing).
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if no briefing was delivered recently.")
    ap.add_argument("--max-hours", type=float, default=26.0,
                    help="Alarm threshold since the last confirmed briefing send (default 26).")
    args = ap.parse_args()

    db.init_db()
    now = datetime.now(timezone.utc)
    last = db.last_sent("briefing-%")

    if last is None:
        print("HEARTBEAT FAIL: no briefing has EVER been marked as delivered.")
        print("The worker is either down or its email backend is failing — check the Railway "
              "worker logs (docs/WORKER.md) and the email backend config.")
        return 1

    dt = datetime.fromisoformat(last)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (now - dt).total_seconds() / 3600.0
    print("Last confirmed briefing delivery: %s (%.1f h ago)." % (last, age_h))

    if age_h > args.max_hours:
        print("HEARTBEAT FAIL: older than the %.0fh threshold." % args.max_hours)
        print("Briefings should land twice a day — check the Railway worker logs and the "
              "email backend (docs/WORKER.md).")
        return 1

    print("Heartbeat OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

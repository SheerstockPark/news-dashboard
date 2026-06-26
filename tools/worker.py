#!/usr/bin/env python3
"""Always-on worker — owns everything time-sensitive so GitHub's flaky cron is just backup.

One process, one loop (default every 60s). Each tick it:
  1. Pulls fresh feeds into Turso.
  2. Emails any *very-big NEW* headline — genuinely instant urgent alerts (~1 min, not 15).
  3. At 06:00 UK sends the Morning briefing; at 20:00 UK the Evening one — punctually,
     because a real always-on clock fires them, not GitHub's best-effort scheduler.

Why this exists: GitHub Actions `schedule:` is best-effort and was silently dropping this
repo's crons (briefings missed, urgent alerts never ran). An always-on host (Railway/Fly/Koyeb)
running this loop fixes both at once.

Dedupe is DB-backed (db.alert_state) so a restart never double-sends or re-blasts a backlog:
  * urgent alerts  — scope "urgent", per article id (in alerts.run_urgent)
  * briefings      — scope "briefing-morning"/"briefing-evening", id = UK date (here)

Briefings use a catch-up window, not an exact instant: Morning fires if the worker sees UK time
in [06:00, 12:00) and hasn't sent today (so a 06:00 outage still delivers when it wakes at 08:00,
exactly the failure we just hit); Evening fires in [20:00, 24:00). Outside the window it's skipped.

Usage:
    python tools/worker.py                     # 60s loop (the Procfile default)
    python tools/worker.py --interval 90       # custom cadence
    python tools/worker.py --once              # single tick (smoke test)

Needs: TURSO_*, ANTHROPIC_API_KEY, and an email backend (RESEND_API_KEY or SMTP_* + DIGEST_TO).
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python < 3.9
    ZoneInfo = None

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import REPO_ROOT  # noqa: E402
from newsdash import alerts, db, ingest, mailer  # noqa: E402
from send_briefing import send_briefing  # noqa: E402  (sibling tool)

try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

UK = ZoneInfo("Europe/London") if ZoneInfo else timezone.utc

# Briefing schedule (UK local hours) + the catch-up window that follows each.
_EDITIONS = [
    {"edition": "Morning", "scope": "briefing-morning", "start": 6,  "until": 12},
    {"edition": "Evening", "scope": "briefing-evening", "start": 20, "until": 24},
]


def _log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print("[%s] %s" % (stamp, msg), flush=True)


def _due_edition(now_uk: datetime):
    """The briefing edition due now (within its window and not yet sent today), or None."""
    today = now_uk.strftime("%Y-%m-%d")
    db.init_db()
    for e in _EDITIONS:
        if e["start"] <= now_uk.hour < e["until"] and today not in db.alerted_ids(e["scope"]):
            return e, today
    return None, None


def tick() -> None:
    """One pass: ingest → urgent check → maybe a scheduled briefing. Fail-soft throughout."""
    # 1) Fetch once for the whole tick (urgent + briefing both read the fresh rows).
    try:
        s = ingest.run_once()
        _log("ingest: %d new, %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))
    except Exception as exc:  # noqa: BLE001
        _log("ingest FAILED: %s" % exc)

    # 2) Instant urgent alerts (we just fetched, so don't fetch again inside).
    try:
        r = alerts.run_urgent(log=_log)
        if r.get("sent") or r.get("note"):
            _log("urgent: %d emailed%s"
                 % (r.get("sent", 0), (" (%s)" % r["note"]) if r.get("note") else ""))
    except Exception as exc:  # noqa: BLE001
        _log("urgent FAILED: %s" % exc)

    # 3) Scheduled briefing, if one is due in its window and not yet sent today.
    try:
        now_uk = datetime.now(UK)
        e, today = _due_edition(now_uk)
        if e:
            _log("%s briefing due (UK %s) — generating…" % (e["edition"], now_uk.strftime("%H:%M")))
            res = send_briefing(edition=e["edition"], fetch=False, log=_log)
            if res.get("sent"):
                db.mark_alerted([today], e["scope"])  # mark only on confirmed send → retries next tick
                _log("%s briefing sent + marked for %s." % (e["edition"], today))
            else:
                _log("%s briefing NOT sent (%s) — will retry next tick."
                     % (e["edition"], res.get("error") or res.get("note") or "unknown"))
    except Exception as exc:  # noqa: BLE001
        _log("briefing step FAILED: %s" % exc)


def main() -> int:
    ap = argparse.ArgumentParser(description="Always-on worker: urgent alerts + scheduled briefings.")
    ap.add_argument("--interval", type=int, default=60, help="Seconds between ticks (default 60).")
    ap.add_argument("--once", action="store_true", help="Run a single tick and exit (smoke test).")
    args = ap.parse_args()

    if not mailer.configured():
        _log("No email backend (set RESEND_API_KEY or SMTP_* + DIGEST_TO). Worker idling.")
    _log("Worker up. Email backend: %s · recipients: %s"
         % (mailer.backend(), ", ".join(mailer.recipients()) or "(none)"))
    _log("Briefings: Morning 06:00 UK, Evening 20:00 UK · urgent check every %ds." % args.interval)

    if args.once:
        tick()
        return 0

    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 — never let one bad tick kill the worker
            _log("tick FAILED (continuing): %s" % exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Push real-time oil-news alerts to Telegram (or email).

Alerts on newly-ingested articles that are high-relevance, strongly bullish/bearish, or
match a watchlist keyword. The first run baselines silently (no backlog blast).

Usage:
    python tools/run_alerts.py                              # one check
    python tools/run_alerts.py --loop --interval 60        # continuous (pairs with ingest loop)
    python tools/run_alerts.py --keywords hormuz opec spr  # watchlist
    python tools/run_alerts.py --min-relevance 70 --min-impact 60

Channel auto-detects: Telegram if TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID set, else SMTP email.
Exits 0 with a notice if no channel is configured.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import alerts, ingest, mailer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Real-time oil-news alerts.")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--fetch", action="store_true", help="Ingest fresh feeds before each check.")
    ap.add_argument("--urgent", action="store_true",
                    help="Intra-day EMAIL for very big headlines only (cross-asset, high bar).")
    ap.add_argument("--min-relevance", type=int, default=None)
    ap.add_argument("--min-impact", type=int, default=None)
    ap.add_argument("--keywords", nargs="*", default=None)
    args = ap.parse_args()

    if args.urgent and not mailer.configured():
        print("No email backend for urgent alerts. Set RESEND_API_KEY or SMTP_* + DIGEST_TO.")
        return 0
    if not args.urgent and alerts.channel() == "none":
        print("No alert channel configured. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID "
              "(recommended) or SMTP_* in .env. See .env.example.")
        return 0

    def check():
        if args.fetch:
            ingest.run_once()
        if args.urgent:
            kw = {} if args.keywords is None else {"keywords": args.keywords}
            s = alerts.run_urgent(
                min_relevance=args.min_relevance if args.min_relevance is not None else 78,
                min_impact=args.min_impact if args.min_impact is not None else 72,
                log=lambda m: print(m), **kw,
            )
            print("Urgent: %d emailed via %s%s"
                  % (s["sent"], s.get("backend", s["channel"]),
                     (" (%s)" % s["note"]) if s.get("note") else ""))
            return
        s = alerts.run_once(
            args.min_relevance if args.min_relevance is not None else 70,
            args.min_impact if args.min_impact is not None else 60,
            args.keywords or [], log=lambda m: print(m),
        )
        print("Alerts: %d sent via %s%s"
              % (s["sent"], s["channel"], (" (%s)" % s["note"]) if s.get("note") else ""))

    print("Alert channel: %s" % alerts.channel())
    if not args.loop:
        check()
        return 0
    print("Looping every %ds. Ctrl-C to stop." % args.interval)
    try:
        while True:
            check()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

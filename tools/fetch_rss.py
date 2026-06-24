#!/usr/bin/env python3
"""Fetch RSS/Atom feeds from configured sources, normalize, tag, and store.

Thin CLI over newsdash.ingest. One job: pull feeds -> normalize -> score -> upsert to SQLite.

Usage:
    python tools/fetch_rss.py                 # fetch all enabled sources once
    python tools/fetch_rss.py --source bbc-world oilprice   # only these source ids
    python tools/fetch_rss.py --loop          # poll forever at fetch_interval_seconds
    python tools/fetch_rss.py --loop --interval 30
    python tools/fetch_rss.py --quiet

Exit code is 0 if at least one source succeeded, 1 if every source failed.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import config as cfg  # noqa: E402
from newsdash import ingest  # noqa: E402


def _run(source_ids, quiet) -> int:
    log = (lambda *_: None) if quiet else (lambda m: print(m))
    summary = ingest.run_once(source_ids, log=log)
    print(
        "Ingest complete: %d new article(s), %d/%d sources ok%s"
        % (summary["new"], summary["ok"], summary["sources"],
           (", %d failed" % summary["failed"] if summary["failed"] else ""))
    )
    for name, err in summary["errors"]:
        print("  [FAIL] %s: %s" % (name, err), file=sys.stderr)
    return 0 if summary["ok"] > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch and store news RSS feeds.")
    ap.add_argument("--source", nargs="*", dest="sources", help="Only fetch these source ids.")
    ap.add_argument("--loop", action="store_true", help="Poll continuously.")
    ap.add_argument("--interval", type=int, default=None, help="Loop interval seconds (overrides config).")
    ap.add_argument("--quiet", action="store_true", help="Only print summary lines.")
    args = ap.parse_args()

    if not args.loop:
        return _run(args.sources, args.quiet)

    interval = args.interval or cfg.load_config()["defaults"]["fetch_interval_seconds"]
    print("Looping every %ds. Ctrl-C to stop." % interval)
    try:
        while True:
            print("\n[%s] polling..." % ingest.now_iso())
            _run(args.sources, args.quiet)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

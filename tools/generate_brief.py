#!/usr/bin/env python3
"""Generate the AI morning brief (Claude) and store it for the dashboard / digest.

Usage:
    python tools/generate_brief.py            # build from current top oil-relevant news
    python tools/generate_brief.py --fetch    # ingest fresh feeds first
    python tools/generate_brief.py --print     # also print the brief to stdout

Needs ANTHROPIC_API_KEY (env or .env). Exits 0 with a notice if absent.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import brief, db, ingest, prices  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the AI morning brief.")
    ap.add_argument("--fetch", action="store_true", help="Ingest fresh feeds first.")
    ap.add_argument("--print", dest="show", action="store_true", help="Print the brief.")
    ap.add_argument("--min-relevance", type=int, default=20)
    args = ap.parse_args()

    if not brief.available():
        print("ANTHROPIC_API_KEY not set (env or .env) — skipping brief.")
        return 0
    if args.fetch:
        s = ingest.run_once()
        print("Fetched: %d new, %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    db.init_db()
    articles = db.query_articles(limit=40, min_relevance=args.min_relevance)
    out = brief.generate(articles, prices.get_quotes(), prices.get_spreads())
    print("Brief generated (%s) -> %s" % (out["model"], brief.BRIEF_PATH))
    if args.show:
        print("\n" + out["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

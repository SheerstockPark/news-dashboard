#!/usr/bin/env python3
"""Enrich oil-relevant articles with Claude-based crude-impact sentiment (opt-in).

Selects recent oil-relevant headlines that haven't been LLM-scored yet, classifies them
with Claude Haiku 4.5 (structured output), and stores the verdict. Run manually or on a
cron; the dashboard displays the LLM verdict when present, otherwise the keyword tagger.

Usage:
    python tools/enrich_sentiment.py                  # score up to 200 recent oil-relevant
    python tools/enrich_sentiment.py --min-relevance 30 --limit 300
    python tools/enrich_sentiment.py --reclassify      # re-score even if already done

Needs ANTHROPIC_API_KEY (env or .env). Exits 0 with a notice if the key is absent.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import db, llm_sentiment  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM crude-impact enrichment.")
    ap.add_argument("--min-relevance", type=int, default=20)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--reclassify", action="store_true", help="Re-score already-scored rows.")
    args = ap.parse_args()

    if not llm_sentiment.available():
        print("ANTHROPIC_API_KEY not set (env or .env) — skipping LLM enrichment.")
        print("Add it to .env (see .env.example) to enable AI sentiment.")
        return 0

    db.init_db()
    pool = db.query_articles(limit=args.limit, min_relevance=args.min_relevance)
    items = [a for a in pool if args.reclassify or a.get("llm_impact") in (None, "")]
    items = [{"id": a["id"], "title": a["title"], "summary": a.get("summary", "")} for a in items]
    if not items:
        print("Nothing to enrich (all recent oil-relevant articles already scored).")
        return 0

    print("Classifying %d headlines with %s…" % (len(items), llm_sentiment.MODEL))
    verdicts = llm_sentiment.classify(items, log=lambda m: print(m))
    n = db.set_llm_sentiment(verdicts)
    print("Done: %d article(s) updated with AI sentiment." % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

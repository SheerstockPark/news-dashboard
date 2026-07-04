#!/usr/bin/env python3
"""Re-score existing articles with the CURRENT tagging rules (one-shot backfill).

Relevance/impact are computed once at ingest, so tagger improvements only reach NEW rows —
after a rules upgrade the dashboard keeps showing the backlog's stale labels (e.g. World Cup
headlines badged bullish-crude) until those rows age out. This recomputes relevance, tags and
impact for recent articles in place. Deterministic keyword logic only — no API calls, no cost.
LLM sentiment columns (llm_*) are left untouched.

Usage:
    python tools/retag.py               # re-tag the most recent 2000 articles
    python tools/retag.py --limit 500
    python tools/retag.py --dry-run     # report what would change, write nothing
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import db, tagging  # noqa: E402
from newsdash.config import enabled_sources  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score existing articles with current rules.")
    ap.add_argument("--limit", type=int, default=2000, help="Most-recent N articles (default 2000).")
    ap.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
    args = ap.parse_args()

    db.init_db()
    weights = {}
    try:
        weights = {s["id"]: s.get("weight", 1) for s in enabled_sources()}
    except Exception:  # noqa: BLE001 — config shape drift shouldn't block a backfill
        pass

    rows = db.query_articles(limit=args.limit, min_relevance=0)
    changed = []
    for a in rows:
        w = weights.get(a["source_id"], 1)
        relevance, tags = tagging.score(a["title"], a.get("summary") or "", w)
        if relevance >= 25:
            impact_label, impact_score = tagging.impact(a["title"], a.get("summary") or "")
        else:
            impact_label, impact_score = "neutral", 0
        if (relevance != a.get("relevance") or impact_label != a.get("impact")
                or impact_score != a.get("impact_score") or sorted(tags) != sorted(a.get("tags") or [])):
            changed.append((relevance, json.dumps(sorted(tags)), impact_label, impact_score, a["id"]))

    print("Scanned %d articles — %d need re-tagging." % (len(rows), len(changed)))
    if args.dry_run or not changed:
        return 0

    with db._connect() as conn:  # noqa: SLF001 — backfill tool, same module family
        conn.executemany(
            "UPDATE articles SET relevance=?, tags=?, impact=?, impact_score=? WHERE id=?",
            changed,
        )
        conn.commit()
    print("Updated %d articles with current tagging rules." % len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

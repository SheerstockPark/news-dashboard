#!/usr/bin/env python3
"""One-shot audit of the urgent-alert path, for threshold retuning on real data.

Dumps (a) every article the urgent path actually sent (alert_state scope 'urgent') since
--since, and (b) the recent high-scoring article pool (what the qualifier chose FROM), to a
JSON file. Run from GitHub Actions where the Turso credentials live; the workflow commits
the JSON back to the repo so it can be analysed locally. Contains only public article
metadata (titles, scores, sources) — no secrets, no recipients.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import db  # noqa: E402

SENT_COLS = ["sent_at", "id", "source_name", "category", "title", "relevance",
             "impact", "impact_score", "published_at"]
POOL_COLS = ["id", "source_name", "category", "title", "relevance",
             "impact", "impact_score", "published_at"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Dump urgent-alert send history + article pool.")
    ap.add_argument("--since", default="2026-07-05", help="ISO date lower bound.")
    ap.add_argument("--out", default="docs/urgent-audit.json")
    args = ap.parse_args()

    db.init_db()
    with db._connect() as conn:  # noqa: SLF001 — read-only audit, same pattern as tools/retag.py
        sent = conn.execute(
            "SELECT s.sent_at, a.id, a.source_name, a.category, a.title, a.relevance, "
            "a.impact, a.impact_score, a.published_at "
            "FROM alert_state s JOIN articles a ON a.id = s.id "
            "WHERE s.scope = 'urgent' AND s.sent_at >= ? ORDER BY s.sent_at",
            (args.since,),
        ).fetchall()
        pool = conn.execute(
            "SELECT a.id, a.source_name, a.category, a.title, a.relevance, "
            "a.impact, a.impact_score, a.published_at "
            "FROM articles a WHERE (a.published_at >= ? OR a.fetched_at >= ?) "
            "AND (a.relevance >= 50 OR a.impact_score >= 40 OR a.impact_score <= -40) "
            "ORDER BY a.relevance DESC LIMIT 1500",
            (args.since, args.since),
        ).fetchall()

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": args.since,
        "sent": [dict(zip(SENT_COLS, r)) for r in sent],
        "pool": [dict(zip(POOL_COLS, r)) for r in pool],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("sent rows: %d, pool rows: %d -> %s" % (len(sent), len(pool), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

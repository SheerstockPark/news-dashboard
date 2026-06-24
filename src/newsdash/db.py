"""SQLite storage for normalized articles. One table, upsert-on-id for dedup."""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from . import DATA_DIR, DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            TEXT PRIMARY KEY,   -- stable hash of canonical url/guid
    source_id     TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    category      TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT,
    url           TEXT NOT NULL,
    published_at  TEXT,               -- ISO8601 UTC, may be null if feed omits it
    fetched_at    TEXT NOT NULL,      -- ISO8601 UTC
    relevance     INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',  -- JSON array
    impact        TEXT NOT NULL DEFAULT 'neutral',  -- bullish | bearish | neutral (for crude)
    impact_score  INTEGER NOT NULL DEFAULT 0        -- signed -100..100
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source    ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_relevance ON articles(relevance DESC);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """Add columns introduced after the first schema, for pre-existing DBs."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
    for col, ddl in (
        ("impact", "ALTER TABLE articles ADD COLUMN impact TEXT NOT NULL DEFAULT 'neutral'"),
        ("impact_score", "ALTER TABLE articles ADD COLUMN impact_score INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in have:
            conn.execute(ddl)


@contextmanager
def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # concurrent reads (dashboard) + writes (ingest)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_articles(rows: Iterable[Dict[str, Any]]) -> int:
    """Insert articles, ignoring ones already stored (dedup by id). Returns # new rows."""
    rows = list(rows)
    if not rows:
        return 0
    sql = """
        INSERT INTO articles
            (id, source_id, source_name, category, title, summary, url,
             published_at, fetched_at, relevance, tags, impact, impact_score)
        VALUES
            (:id, :source_id, :source_name, :category, :title, :summary, :url,
             :published_at, :fetched_at, :relevance, :tags, :impact, :impact_score)
        ON CONFLICT(id) DO NOTHING;
    """
    with _connect() as conn:
        before = conn.total_changes
        conn.executemany(sql, [_serialize(r) for r in rows])
        return conn.total_changes - before


def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    if isinstance(row.get("tags"), (list, tuple)):
        row["tags"] = json.dumps(list(row["tags"]))
    row.setdefault("impact", "neutral")
    row.setdefault("impact_score", 0)
    return row


def query_articles(
    limit: int = 200,
    sources: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    min_relevance: int = 0,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clauses = ["relevance >= ?"]
    params: List[Any] = [min_relevance]
    if sources:
        clauses.append("source_id IN (%s)" % ",".join("?" * len(sources)))
        params.extend(sources)
    if categories:
        clauses.append("category IN (%s)" % ",".join("?" * len(categories)))
        params.extend(categories)
    if search:
        clauses.append("(title LIKE ? OR summary LIKE ?)")
        params.extend(["%" + search + "%", "%" + search + "%"])

    sql = (
        "SELECT * FROM articles WHERE "
        + " AND ".join(clauses)
        + " ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?"
    )
    params.append(limit)

    with _connect() as conn:
        out = []
        for r in conn.execute(sql, params).fetchall():
            d = dict(r)
            d["tags"] = json.loads(d.get("tags") or "[]")
            out.append(d)
        return out


def stats() -> Dict[str, Any]:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        latest = conn.execute("SELECT MAX(fetched_at) FROM articles").fetchone()[0]
        per_source = {
            r["source_name"]: r["n"]
            for r in conn.execute(
                "SELECT source_name, COUNT(*) AS n FROM articles GROUP BY source_name ORDER BY n DESC"
            ).fetchall()
        }
    return {"total": total, "latest_fetch": latest, "per_source": per_source}

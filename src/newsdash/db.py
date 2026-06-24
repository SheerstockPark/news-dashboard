"""Article storage. Driver-agnostic: local SQLite by default, Turso (cloud libSQL) when
TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set.

The SQL is identical for both backends (Turso speaks SQLite). Row reads are built from
cursor.description rather than sqlite3.Row so the same code works on either driver.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from . import DATA_DIR, DB_PATH

# Full schema — fresh databases (incl. a new Turso DB) get every column up front, so we
# never depend on PRAGMA-based migration in the cloud. _migrate() backfills old local DBs.
_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS articles (
        id            TEXT PRIMARY KEY,
        source_id     TEXT NOT NULL,
        source_name   TEXT NOT NULL,
        category      TEXT NOT NULL,
        title         TEXT NOT NULL,
        summary       TEXT,
        url           TEXT NOT NULL,
        published_at  TEXT,
        fetched_at    TEXT NOT NULL,
        relevance     INTEGER NOT NULL DEFAULT 0,
        tags          TEXT NOT NULL DEFAULT '[]',
        impact        TEXT NOT NULL DEFAULT 'neutral',
        impact_score  INTEGER NOT NULL DEFAULT 0,
        llm_impact        TEXT,
        llm_impact_score  INTEGER,
        llm_rationale     TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_source    ON articles(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_articles_relevance ON articles(relevance DESC)",
]

_INSERT_COLS = ["id", "source_id", "source_name", "category", "title", "summary", "url",
                "published_at", "fetched_at", "relevance", "tags", "impact", "impact_score"]


def using_turso() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN"))


def backend() -> str:
    return "turso" if using_turso() else "sqlite"


@contextmanager
def _connect():
    if using_turso():
        import libsql  # cloud-only dependency (Linux wheel); never imported locally

        conn = libsql.connect(
            database=os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ["TURSO_AUTH_TOKEN"],
        )
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")  # concurrent reads + writes (local only)
        except sqlite3.Error:
            pass
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def init_db() -> None:
    with _connect() as conn:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        _migrate(conn)


def _migrate(conn) -> None:
    """Backfill columns on pre-existing local DBs. Best-effort (no-op on fresh/cloud DBs)."""
    try:
        have = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
    except Exception:
        return
    for col, ddl in (
        ("impact", "ALTER TABLE articles ADD COLUMN impact TEXT NOT NULL DEFAULT 'neutral'"),
        ("impact_score", "ALTER TABLE articles ADD COLUMN impact_score INTEGER NOT NULL DEFAULT 0"),
        ("llm_impact", "ALTER TABLE articles ADD COLUMN llm_impact TEXT"),
        ("llm_impact_score", "ALTER TABLE articles ADD COLUMN llm_impact_score INTEGER"),
        ("llm_rationale", "ALTER TABLE articles ADD COLUMN llm_rationale TEXT"),
    ):
        if col not in have:
            try:
                conn.execute(ddl)
            except Exception:
                pass


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def upsert_articles(rows: Iterable[Dict[str, Any]]) -> int:
    """Insert articles, ignoring already-stored ids. Returns # new rows (count-based)."""
    rows = list(rows)
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_INSERT_COLS))
    sql = ("INSERT INTO articles (%s) VALUES (%s) ON CONFLICT(id) DO NOTHING"
           % (",".join(_INSERT_COLS), placeholders))
    tuples = [tuple(_field(r, c) for c in _INSERT_COLS) for r in rows]
    with _connect() as conn:
        before = _count(conn)
        conn.executemany(sql, tuples)
        conn.commit()
        return _count(conn) - before


def _field(row: Dict[str, Any], col: str) -> Any:
    if col == "tags":
        v = row.get("tags")
        return json.dumps(list(v)) if isinstance(v, (list, tuple)) else (v or "[]")
    if col == "impact":
        return row.get("impact", "neutral")
    if col == "impact_score":
        return row.get("impact_score", 0)
    return row.get(col)


def set_llm_sentiment(updates: Dict[str, Dict]) -> int:
    """Write LLM verdicts: {id: {impact, score, rationale}}. Returns # rows attempted."""
    if not updates:
        return 0
    rows = [(v["impact"], v["score"], v.get("rationale", ""), aid) for aid, v in updates.items()]
    with _connect() as conn:
        conn.executemany(
            "UPDATE articles SET llm_impact=?, llm_impact_score=?, llm_rationale=? WHERE id=?", rows
        )
        return len(rows)


def prune(keep_days: int = 14) -> int:
    """Delete articles we fetched more than keep_days ago. Bounds DB size without dropping
    freshly-surfaced (but old-dated) items. Returns rows removed."""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    with _connect() as conn:
        before = _count(conn)
        conn.execute("DELETE FROM articles WHERE fetched_at < ?", (cutoff,))
        conn.commit()
        return before - _count(conn)


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

    sql = ("SELECT * FROM articles WHERE " + " AND ".join(clauses)
           + " ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?")
    params.append(limit)

    with _connect() as conn:
        out = _dicts(conn.execute(sql, tuple(params)))
    for d in out:
        d["tags"] = json.loads(d.get("tags") or "[]")
    return out


def stats() -> Dict[str, Any]:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        latest = conn.execute("SELECT MAX(fetched_at) FROM articles").fetchone()[0]
        per = _dicts(conn.execute(
            "SELECT source_name, COUNT(*) AS n FROM articles GROUP BY source_name ORDER BY n DESC"))
    return {"total": total, "latest_fetch": latest,
            "per_source": {r["source_name"]: r["n"] for r in per}}

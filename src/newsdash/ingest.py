"""Core ingest logic: fetch feeds -> normalize -> tag -> store.

Importable by both the CLI tool (tools/fetch_rss.py) and the dashboard (which calls
run_once() in-process so it works on hosts with no background worker, e.g. Streamlit Cloud).
"""

import hashlib
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser

from . import config as cfg
from . import db, tagging

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) NewsDashboard/0.1 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso(struct_time) -> Optional[str]:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _clean(text: str, limit: int = 600) -> str:
    if not text:
        return ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    return text[:limit]


def _article_id(entry: Dict[str, Any]) -> str:
    basis = entry.get("id") or entry.get("link") or (entry.get("title", "") + entry.get("published", ""))
    return hashlib.sha1(basis.encode("utf-8", "ignore")).hexdigest()


_JUNK_TITLE = re.compile(r"^\s*(\[no title\]|no title\b|rt @|rt\s|https?://)", re.IGNORECASE)


def _is_junk_title(title: str) -> bool:
    """Drop content-free entries (image-only Truth Social posts, bare reposts, link-only)."""
    t = (title or "").strip()
    return len(t) < 8 or bool(_JUNK_TITLE.match(t))


def normalize_entries(parsed, source: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in parsed.entries:
        title = _clean(entry.get("title", ""), 400)
        if _is_junk_title(title):
            continue
        summary = _clean(entry.get("summary", "") or entry.get("description", ""))
        relevance, tags = tagging.score(title, summary, source["weight"])
        impact_label, impact_score = tagging.impact(title, summary)
        rows.append(
            {
                "id": _article_id(entry),
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "title": title,
                "summary": summary,
                "url": entry.get("link", ""),
                "published_at": _to_iso(entry.get("published_parsed") or entry.get("updated_parsed")),
                "fetched_at": fetched_at,
                "relevance": relevance,
                "tags": tags,
                "impact": impact_label,
                "impact_score": impact_score,
            }
        )
    return rows


def fetch_source(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch + normalize one source. Raises on hard failure (caller logs and continues)."""
    parsed = feedparser.parse(
        source["url"], agent=USER_AGENT, request_headers={"Cache-Control": "no-cache"}
    )
    if parsed.get("bozo") and not parsed.entries:
        raise RuntimeError("feed parse failed: %s" % (parsed.get("bozo_exception") or "unknown error"))
    return normalize_entries(parsed, source, now_iso())


def run_once(source_ids: Optional[List[str]] = None, log=None) -> Dict[str, Any]:
    """Fetch all (or selected) enabled sources once. Returns a summary dict.

    `log` is an optional callable(str) for progress lines; defaults to silent.
    """
    log = log or (lambda *_: None)
    conf = cfg.load_config()
    sources = [s for s in conf["sources"] if s["enabled"]]
    if source_ids:
        wanted = set(source_ids)
        sources = [s for s in sources if s["id"] in wanted]

    db.init_db()
    total_new, ok, failed, errors = 0, 0, 0, []
    for s in sources:
        try:
            rows = fetch_source(s)
            new = db.upsert_articles(rows)
            total_new += new
            ok += 1
            log("  [ok]   %-26s %3d entries, %3d new" % (s["name"], len(rows), new))
        except Exception as exc:  # noqa: BLE001 — fail loud per-source, keep going
            failed += 1
            errors.append((s["name"], str(exc)))
            log("  [FAIL] %-26s %s" % (s["name"], exc))

    return {"new": total_new, "ok": ok, "failed": failed, "sources": len(sources), "errors": errors}

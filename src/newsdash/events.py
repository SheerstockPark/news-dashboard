"""Upcoming market events that move oil — for the dashboard's catalyst calendar.

Recurring weekly releases (EIA inventories, rig count, API) are computed in US Eastern
time. One-off scheduled events (OPEC meetings, FOMC, CPI) live in config/events.yaml so
they can be kept current without code changes. All times normalized to UTC.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import yaml

from . import REPO_ROOT

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback if tz db missing
    _ET = timezone(timedelta(hours=-4))

# (label, weekday Mon=0..Sun=6, hour, minute, category) in US Eastern
_RECURRING = [
    ("EIA Crude Inventories", 2, 10, 30, "energy"),     # Wednesday 10:30 ET
    ("EIA Nat Gas Storage", 3, 10, 30, "energy"),       # Thursday 10:30 ET
    ("Baker Hughes Rig Count", 4, 13, 0, "energy"),     # Friday 13:00 ET
    ("API Inventories", 1, 16, 30, "energy"),           # Tuesday 16:30 ET
]


def _next_weekly(now: datetime, weekday: int, hh: int, mm: int) -> datetime:
    et = now.astimezone(_ET)
    days = (weekday - et.weekday()) % 7
    cand = (et + timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= et:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc)


def _load_oneoffs() -> List[Dict]:
    path = REPO_ROOT / "config" / "events.yaml"
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out = []
    for e in raw.get("events", []):
        try:
            dt = datetime.fromisoformat(str(e["datetime"]).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out.append({"name": e["name"], "when": dt, "category": e.get("category", "macro")})
        except Exception:
            continue
    return out


def upcoming(now: datetime, limit: int = 8) -> List[Dict]:
    """Return the next `limit` events (recurring + scheduled), soonest first."""
    items = [{"name": n, "when": _next_weekly(now, wd, hh, mm), "category": c}
             for (n, wd, hh, mm, c) in _RECURRING]
    items += [e for e in _load_oneoffs() if e["when"] > now]
    items.sort(key=lambda x: x["when"])
    return items[:limit]


def countdown(when: datetime, now: datetime) -> str:
    s = int((when - now).total_seconds())
    if s < 0:
        return "now"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return "in %dd %dh" % (d, h)
    if h:
        return "in %dh %dm" % (h, m)
    return "in %dm" % m

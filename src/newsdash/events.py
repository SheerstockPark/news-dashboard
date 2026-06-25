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

# Weekly releases — (label, weekday Mon=0..Sun=6, hour, minute, category) in US Eastern.
_RECURRING = [
    ("EIA Crude Inventories", 2, 10, 30, "energy"),     # Wednesday 10:30 ET
    ("EIA Nat Gas Storage", 3, 10, 30, "energy"),       # Thursday 10:30 ET
    ("Baker Hughes Rig Count", 4, 13, 0, "energy"),     # Friday 13:00 ET
    ("API Inventories", 1, 16, 30, "energy"),           # Tuesday 16:30 ET
]

# Monthly releases computable by rule — (label, weekday, ordinal-in-month, hh, mm, category) ET.
# Variable-date ones (CPI, FOMC, OPEC/IEA reports) live in config/events.yaml instead.
_MONTHLY = [
    ("US Nonfarm Payrolls", 4, 1, 8, 30, "macro"),      # first Friday 08:30 ET
    ("EIA Short-Term Outlook", 1, 1, 12, 0, "energy"),  # first Tuesday 12:00 ET
]


def _next_weekly(now: datetime, weekday: int, hh: int, mm: int) -> datetime:
    et = now.astimezone(_ET)
    days = (weekday - et.weekday()) % 7
    cand = (et + timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= et:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc)


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> int:
    """Day-of-month for the Nth given weekday (e.g. 1st Friday) of year/month."""
    first = datetime(year, month, 1, tzinfo=_ET)
    offset = (weekday - first.weekday()) % 7
    return 1 + offset + (ordinal - 1) * 7


def _next_monthly(now: datetime, weekday: int, ordinal: int, hh: int, mm: int) -> datetime:
    et = now.astimezone(_ET)
    y, m = et.year, et.month
    cand = None
    for _ in range(2):  # this month, else roll to next
        day = _nth_weekday(y, m, weekday, ordinal)
        cand = datetime(y, m, day, hh, mm, tzinfo=_ET)
        if cand > et:
            break
        m += 1
        if m > 12:
            m, y = 1, y + 1
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
    """Return the next `limit` events (weekly + monthly + scheduled), soonest first.

    When FRED_API_KEY is set, authoritative US release dates (CPI, NFP, PPI, PCE, GDP) come
    from FRED and override the computed/yaml versions of the same release (matched by label).
    """
    items = [{"name": n, "when": _next_weekly(now, wd, hh, mm), "category": c, "cadence": "weekly"}
             for (n, wd, hh, mm, c) in _RECURRING]
    items += [{"name": n, "when": _next_monthly(now, wd, o, hh, mm), "category": c, "cadence": "monthly"}
              for (n, wd, o, hh, mm, c) in _MONTHLY]
    items += [dict(e, cadence=e.get("cadence", "scheduled"))
              for e in _load_oneoffs() if e["when"] > now]

    try:
        from . import econcal

        fred = econcal.upcoming(now, per=1)
    except Exception:
        fred = []
    if fred:
        covered = {f["name"] for f in fred}
        items = [it for it in items if it["name"] not in covered] + fred

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

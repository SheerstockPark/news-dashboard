"""US economic-release calendar via FRED — reliable scheduled dates for the big market
movers (CPI, Nonfarm Payrolls, PPI, PCE, GDP). Authoritative and free.

Fail-soft: returns [] without FRED_API_KEY, and events.py falls back to its computed rules
(first-Friday NFP etc.) + config/events.yaml. Set FRED_API_KEY to get exact dates that never
drift. Free key: https://fred.stlouisfed.org/docs/api/api_key.html
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = timezone(timedelta(hours=-4))

# FRED release_id -> (friendly label, hh, mm ET, category). US macro data drops 08:30 ET.
# Labels match what we use elsewhere so events.py can dedupe computed/yaml duplicates.
_RELEASES = {
    10: ("US CPI (inflation)", 8, 30, "macro"),
    50: ("US Nonfarm Payrolls", 8, 30, "macro"),
    46: ("US PPI", 8, 30, "macro"),
    54: ("US PCE (Fed gauge)", 8, 30, "macro"),
    53: ("US GDP", 8, 30, "macro"),
}


def _key() -> str:
    if not os.environ.get("FRED_API_KEY"):
        try:
            from dotenv import load_dotenv

            from . import REPO_ROOT

            load_dotenv(REPO_ROOT / ".env")
        except Exception:
            pass
    return os.environ.get("FRED_API_KEY", "")


def available() -> bool:
    return bool(_key())


def upcoming(now: datetime, per: int = 1) -> List[Dict]:
    """Next `per` scheduled date(s) for each tracked release. [] if no key / on error."""
    key = _key()
    if not key:
        return []
    today = now.astimezone(_ET).date().isoformat()
    out: List[Dict] = []
    for rid, (label, hh, mm, cat) in _RELEASES.items():
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/release/dates",
                params={"release_id": rid, "api_key": key, "file_type": "json",
                        "include_release_dates_with_no_data": "true", "sort_order": "asc",
                        "realtime_start": today, "realtime_end": "9999-12-31", "limit": 6},
                timeout=12,
            )
            dates = (r.json() or {}).get("release_dates", [])
            future = [d["date"] for d in dates if d.get("date", "") >= today]
            for ds in future[:per]:
                dt = datetime.fromisoformat(ds).replace(hour=hh, minute=mm, tzinfo=_ET)
                out.append({"name": label, "when": dt.astimezone(timezone.utc),
                            "category": cat, "cadence": "monthly", "source": "FRED"})
        except Exception:
            continue
    return out

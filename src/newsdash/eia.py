"""U.S. EIA petroleum data — the weekly inventory/production numbers an oil desk trades.

Uses the free EIA API v2 (https://www.eia.gov/opendata/ — instant key signup). Reads
EIA_API_KEY from env or .env. Import-safe and fail-soft: returns [] without a key or on
any error, so the dashboard degrades gracefully.

Watched series (weekly): crude stocks ex-SPR, SPR, gasoline, distillate, crude production.
A draw (falling stocks) is typically bullish for crude; a build is bearish.
"""

import os
from typing import Dict, List

import requests

# (EIA v2 series id, label, unit, lower_is_bullish)
SERIES = [
    ("PET.WCESTUS1.W", "Crude stocks (ex-SPR)", "kbbl", True),
    ("PET.WCSSTUS1.W", "SPR", "kbbl", True),
    ("PET.WGTSTUS1.W", "Gasoline stocks", "kbbl", True),
    ("PET.WDISTUS1.W", "Distillate stocks", "kbbl", True),
    ("PET.WCRFPUS2.W", "Crude production", "kbbl/d", False),
]


def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY")
    if key:
        return key
    try:
        from dotenv import load_dotenv

        from . import REPO_ROOT

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass
    return os.environ.get("EIA_API_KEY", "")


def available() -> bool:
    return bool(_api_key())


def _fetch_series(sid: str, length: int = 10) -> List:
    """Raw [(period, value), ...] newest-first for one EIA v2 series. [] on error/no key."""
    key = _api_key()
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.eia.gov/v2/seriesid/%s" % sid,
            params={"api_key": key, "length": length, "sort[0][column]": "period",
                    "sort[0][direction]": "desc"},
            timeout=15,
        )
        data = (r.json().get("response", {}) or {}).get("data", [])
        out = []
        for d in data:
            v = d.get("value")
            if v in (None, ""):
                continue
            try:
                out.append((d.get("period", ""), float(v)))
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return []


def get_inventories() -> List[Dict]:
    """Latest value + week-over-week change for each watched series. [] if unavailable."""
    if not _api_key():
        return []
    out: List[Dict] = []
    for sid, label, unit, lower_bullish in SERIES:
        s = _fetch_series(sid, length=2)
        if not s:
            continue
        latest = s[0][1]
        prev = s[1][1] if len(s) > 1 else latest
        change = latest - prev
        bullish = (change < 0) if lower_bullish else (change > 0)
        out.append({
            "label": label, "unit": unit, "period": s[0][0],
            "value": latest, "change": round(change, 1),
            "bias": "bullish" if change != 0 and bullish else "bearish" if change != 0 else "flat",
        })
    return out


# Reserves (stocks). A draw is bullish for crude; a build bearish. With 10-week trend.
RESERVE_SERIES = [
    ("PET.WCSSTUS1.W", "SPR (strategic reserve)", "kbbl"),
    ("PET.WCESTUS1.W", "Commercial crude", "kbbl"),
    ("PET.WGTSTUS1.W", "Gasoline stocks", "kbbl"),
    ("PET.WDISTUS1.W", "Distillate stocks", "kbbl"),
]

# US weekly oil flows — production, trade and refinery throughput (kbbl/d).
FLOW_SERIES = [
    ("PET.WCRFPUS2.W", "US crude production", "kbbl/d"),
    ("PET.WCEIMUS2.W", "Crude imports", "kbbl/d"),
    ("PET.WCREXUS2.W", "Crude exports", "kbbl/d"),
    ("PET.WCRRIUS2.W", "Refinery runs", "kbbl/d"),
]


def get_reserves() -> List[Dict]:
    """US strategic + commercial stocks: level, w/w change, bias, 10-week trend. [] if no key."""
    out = []
    for sid, label, unit in RESERVE_SERIES:
        s = _fetch_series(sid, length=10)
        if not s:
            continue
        latest, prev = s[0][1], (s[1][1] if len(s) > 1 else s[0][1])
        change = latest - prev
        out.append({
            "label": label, "unit": unit, "period": s[0][0], "value": latest,
            "change": round(change, 1),
            "bias": "bullish" if change < 0 else "bearish" if change > 0 else "flat",
            "trend": [v for _, v in reversed(s)],  # oldest -> newest for a sparkline
        })
    return out


def get_us_flows() -> List[Dict]:
    """US weekly oil flows: level, w/w change, 10-week trend (directional, not a price bias)."""
    out = []
    for sid, label, unit in FLOW_SERIES:
        s = _fetch_series(sid, length=10)
        if not s:
            continue
        latest, prev = s[0][1], (s[1][1] if len(s) > 1 else s[0][1])
        out.append({
            "label": label, "unit": unit, "period": s[0][0], "value": latest,
            "change": round(latest - prev, 1), "dir": "up" if latest > prev else "down" if latest < prev else "flat",
            "trend": [v for _, v in reversed(s)],
        })
    return out


# Major producers/consumers for the global view (EIA international ISO-3 country codes).
_GLOBAL_COUNTRIES = ["USA", "SAU", "RUS", "CAN", "IRQ", "CHN", "ARE", "IRN", "KWT", "BRA", "NGA", "MEX"]


def get_global_production(top: int = 12) -> List[Dict]:
    """Top crude producers (EIA International, monthly, kbbl/d). Best-effort; [] if unavailable.

    EIA international facet IDs aren't as stable as the US seriesid feeds, so this fails soft —
    the US reserves/flows above are the reliable core; this is the bonus global view.
    """
    key = _api_key()
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.eia.gov/v2/international/data/",
            params={
                "api_key": key, "frequency": "monthly", "data[0]": "value",
                "facets[activityId][]": "1",   # production
                "facets[productId][]": "55",   # crude oil incl. lease condensate
                "facets[unit][]": "TBPD",      # thousand barrels per day
                "sort[0][column]": "period", "sort[0][direction]": "desc", "length": 600,
            },
            timeout=20,
        )
        rows = (r.json().get("response", {}) or {}).get("data", [])
    except Exception:
        return []

    latest_by_country: Dict[str, Dict] = {}
    for d in rows:
        c = d.get("countryRegionId") or d.get("countryRegionName")
        if c not in _GLOBAL_COUNTRIES:
            continue
        v = d.get("value")
        if v in (None, ""):
            continue
        # rows are newest-first; keep the first (latest) seen per country
        if c not in latest_by_country:
            try:
                latest_by_country[c] = {
                    "country": d.get("countryRegionName", c),
                    "value": float(v), "period": d.get("period", ""),
                }
            except (TypeError, ValueError):
                continue
    out = sorted(latest_by_country.values(), key=lambda x: x["value"], reverse=True)
    return out[:top]

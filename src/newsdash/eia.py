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


def get_inventories() -> List[Dict]:
    """Latest value + week-over-week change for each watched series. [] if unavailable."""
    key = _api_key()
    if not key:
        return []
    out: List[Dict] = []
    for sid, label, unit, lower_bullish in SERIES:
        try:
            r = requests.get(
                "https://api.eia.gov/v2/seriesid/%s" % sid,
                params={"api_key": key, "length": 2, "sort[0][column]": "period",
                        "sort[0][direction]": "desc"},
                timeout=15,
            )
            data = (r.json().get("response", {}) or {}).get("data", [])
            if len(data) < 1:
                continue
            latest = float(data[0]["value"])
            prev = float(data[1]["value"]) if len(data) > 1 else latest
            change = latest - prev
            # Directional read for crude: draw (down) bullish for stocks; up production bearish
            bullish = (change < 0) if lower_bullish else (change > 0)
            out.append({
                "label": label, "unit": unit, "period": data[0].get("period", ""),
                "value": latest, "change": round(change, 1),
                "bias": "bullish" if change != 0 and bullish else "bearish" if change != 0 else "flat",
            })
        except Exception:
            continue
    return out

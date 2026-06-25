"""Tropical-weather risk for the oil desk — active storms from NOAA's National Hurricane
Center, flagged when they threaten US Gulf production / refining.

Free, no key (public NOAA JSON). Atlantic-basin storms in the Gulf box move crude, nat-gas
and refining margins, so we surface them on the dashboard during hurricane season.
"""

from datetime import datetime, timezone
from typing import Dict, List

import requests

_NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

# Gulf of Mexico bounding box (lat 18–31 N, lon −98 to −80 W) — US offshore oil/gas + Gulf
# Coast refining corridor.
_GULF = {"lat": (18.0, 31.0), "lon": (-98.0, -80.0)}

_CLASS = {
    "TD": "Tropical Depression", "TS": "Tropical Storm", "HU": "Hurricane",
    "MH": "Major Hurricane", "STD": "Subtropical Depression", "STS": "Subtropical Storm",
    "PTC": "Potential Tropical Cyclone", "TC": "Tropical Cyclone",
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_storms() -> Dict:
    """Active tropical systems. Returns {storms, atlantic, gulf_risk, ok, as_of}."""
    try:
        r = requests.get(_NHC_URL, timeout=12,
                         headers={"User-Agent": "SheerstockNewsDashboard/1.0"})
        data = r.json() or {}
    except Exception:
        return {"storms": [], "atlantic": [], "gulf_risk": False, "ok": False, "as_of": None}

    storms: List[Dict] = []
    for s in data.get("activeStorms", []) or []:
        lat = _num(s.get("latitudeNumeric"))
        lon = _num(s.get("longitudeNumeric"))
        basin = (s.get("id", "") or "")[:2].upper()  # AL=Atlantic, EP/CP=Pacific
        in_gulf = (basin == "AL" and lat is not None and lon is not None
                   and _GULF["lat"][0] <= lat <= _GULF["lat"][1]
                   and _GULF["lon"][0] <= lon <= _GULF["lon"][1])
        cls = (s.get("classification") or "").upper()
        storms.append({
            "name": s.get("name", "Unnamed"),
            "class": _CLASS.get(cls, cls or "System"),
            "class_code": cls,
            "intensity_mph": s.get("intensity", ""),     # max sustained winds, mph
            "lat": lat, "lon": lon, "basin": basin,
            "movement": ("%s at %s mph" % (s.get("movementDir", "?"), s.get("movementSpeed", "?"))).strip(),
            "gulf": in_gulf,
            "last_update": s.get("lastUpdate", ""),
        })

    atlantic = [s for s in storms if s["basin"] == "AL"]
    return {
        "storms": storms,
        "atlantic": atlantic,
        "gulf_risk": any(s["gulf"] for s in storms),
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }

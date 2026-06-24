"""Oil-trading relevance scoring and tagging.

Deterministic keyword matching — no ML, no API calls. Given an article's title +
summary, returns a relevance score (0-100) and a list of topic tags. The dashboard
uses these to filter/rank what an oil trader actually cares about.
"""

import re
from typing import Dict, List, Tuple

# Topic -> keywords. Word-boundary matched, case-insensitive.
# Order roughly by how directly each topic moves crude prices.
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "crude": [
        "crude", "brent", "wti", "oil price", "oil prices", "barrel", "barrels",
        "petroleum", "shale", "light sweet", "heavy crude",
    ],
    "opec": ["opec", "opec+", "saudi aramco", "aramco", "production cut", "output cut", "quota"],
    "natgas-lng": ["natural gas", "natgas", "lng", "henry hub", "ttf", "gas price"],
    "refining": ["refinery", "refineries", "refining", "crack spread", "distillate", "diesel", "gasoline"],
    "supply-infra": ["pipeline", "tanker", "strait of hormuz", "suez", "storage", "inventories", "stockpile", "spr"],
    "sanctions": ["sanction", "sanctions", "embargo", "price cap", "export ban", "tariff", "tariffs"],
    "geopolitics": [
        "russia", "ukraine", "iran", "iraq", "venezuela", "libya", "nigeria",
        "saudi", "israel", "gaza", "houthi", "red sea", "war", "ceasefire", "attack", "drone strike",
    ],
    "macro": ["federal reserve", "interest rate", "rate cut", "rate hike", "inflation", "cpi", "recession", "gdp", "dollar"],
    "energy-co": ["exxon", "chevron", "bp", "shell", "totalenergies", "conocophillips", "halliburton", "schlumberger"],
    "demand": ["demand forecast", "iea", "eia", "fuel demand", "consumption", "driving season"],
}

# High-signal terms that should push relevance to the top regardless of count.
_PRIORITY = {"crude", "brent", "wti", "opec", "opec+", "barrel", "strait of hormuz", "spr", "lng"}

# Precompile patterns once.
_COMPILED: Dict[str, List[Tuple[str, "re.Pattern"]]] = {
    topic: [(kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)) for kw in kws]
    for topic, kws in TOPIC_KEYWORDS.items()
}


# --- Crude-price impact lexicon -------------------------------------------------
# Phrases that typically push crude UP (supply at risk / demand strong) vs DOWN
# (supply returns / demand weak / risk premium unwinds). Weighted by how hard they move.
_BULLISH = {
    "supply disruption": 3, "supply outage": 3, "production halt": 3, "output cut": 3,
    "production cut": 3, "opec+ cut": 3, "opec cut": 3, "cuts output": 3, "cuts production": 3,
    "refinery outage": 3, "refinery fire": 3, "pipeline attack": 3, "pipeline halt": 2,
    "attack": 2, "strike on": 2, "drone strike": 3, "missile": 2, "explosion": 2,
    "sanction": 2, "sanctions": 2, "embargo": 3, "export ban": 3, "price cap": 2,
    "escalation": 2, "escalate": 2, "invasion": 3, "war": 1, "conflict": 1,
    "close the strait": 4, "close strait": 4, "strait of hormuz": 2, "blockade": 3,
    "hurricane": 2, "shut-in": 3, "shut in": 2, "force majeure": 3,
    "inventory draw": 3, "stockpiles fall": 2, "crude draw": 3, "supply deficit": 3,
    "strong demand": 2, "demand surge": 2, "tighten": 2, "tightening": 2, "undersupply": 3,
}
_BEARISH = {
    "ceasefire": 3, "cease-fire": 3, "truce": 2, "peace deal": 3, "de-escalation": 3,
    "deescalation": 3, "de-escalate": 3, "diplomacy": 1, "talks": 1, "agreement": 1,
    "output increase": 3, "raise output": 3, "boost production": 3, "increase production": 3,
    "production rises": 2, "ramp up": 2, "more supply": 2, "supply glut": 3, "oversupply": 3,
    "sanctions lifted": 3, "sanctions eased": 3, "ease sanctions": 3, "waiver": 2,
    "reopen": 2, "reopening": 2, "resume": 2, "resumes": 2, "restart": 2, "back online": 2,
    # de-escalation phrasings that would otherwise read bullish via "blockade"/"strait"
    "lifts blockade": 4, "blockade lifted": 4, "lifts naval blockade": 4, "ends blockade": 4,
    "ended iran's ability": 4, "unable to close": 3, "kept open": 3, "remains open": 3,
    "inventory build": 3, "crude build": 3, "stockpiles rise": 2, "stockpiles build": 2,
    "demand weakness": 3, "weak demand": 3, "demand destruction": 3, "recession": 2,
    "slowdown": 2, "glut": 3, "surplus": 2, "price falls": 1, "prices fall": 1, "plunge": 2,
}

_BULL_PAT = [(re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE), w) for k, w in _BULLISH.items()]
_BEAR_PAT = [(re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE), w) for k, w in _BEARISH.items()]


def impact(title: str, summary: str = "") -> Tuple[str, int]:
    """Estimate crude-price impact. Returns (label, signed_score -100..100).

    label in {"bullish", "bearish", "neutral"}. Title hits count double. Heuristic and
    deterministic — a directional hint for traders, not a forecast.
    """
    title = title or ""
    body = (title + " " + summary).lower()
    t = title.lower()

    def tally(patterns):
        total = 0
        for pat, w in patterns:
            if pat.search(body):
                total += w * (2 if pat.search(t) else 1)
        return total

    bull = tally(_BULL_PAT)
    bear = tally(_BEAR_PAT)
    net = bull - bear
    if net == 0:
        return "neutral", 0
    magnitude = min(100, int(round(100 * (1 - 0.80 ** abs(net)))))
    return ("bullish", magnitude) if net > 0 else ("bearish", -magnitude)


def score(title: str, summary: str = "", source_weight: int = 1) -> Tuple[int, List[str]]:
    """Return (relevance 0-100, sorted topic tags) for an article.

    Title matches count double (headlines carry the signal). Source weight nudges
    the floor so specialist energy feeds rank above general wires on weak matches.
    """
    title = title or ""
    summary = summary or ""
    hay_title = title.lower()
    hay_all = (title + " " + summary).lower()

    tags: List[str] = []
    raw = 0
    for topic, patterns in _COMPILED.items():
        topic_hit = False
        for kw, pat in patterns:
            in_title = pat.search(hay_title) is not None
            in_body = pat.search(hay_all) is not None
            if not in_body:
                continue
            topic_hit = True
            raw += 2 if in_title else 1
            if kw in _PRIORITY:
                raw += 4 if in_title else 2
        if topic_hit:
            tags.append(topic)

    if not tags:
        return 0, []

    # Map raw hit-count to 0-100 with diminishing returns, then add a small
    # source-weight floor so curated energy feeds aren't buried.
    relevance = min(100, int(round(100 * (1 - 0.78 ** raw))))
    relevance = min(100, relevance + (source_weight - 1) * 5)
    return relevance, sorted(tags)

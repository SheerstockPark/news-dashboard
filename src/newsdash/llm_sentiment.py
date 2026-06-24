"""Claude-based crude-impact classification (opt-in enrichment).

Uses Claude Haiku 4.5 (cost-effective tier) with structured JSON output to classify
news headlines as bullish / bearish / neutral for crude oil, with a 0-100 magnitude and
a one-line rationale. Headlines are batched (~20 per request) to keep cost low.

Pricing (Haiku 4.5): $1 / 1M input tokens, $5 / 1M output tokens. Typical run over a few
hundred oil-relevant headlines costs well under $0.05. The Batch API would halve that
again, but we use synchronous chunked calls here for freshness and simplicity.

Requires ANTHROPIC_API_KEY (env or .env). Import-safe without it — call available().
"""

import json
import os
from typing import Dict, List

MODEL = "claude-haiku-4-5"

_SYSTEM = (
    "You are a commodities desk analyst. For each news headline, judge its near-term "
    "impact on CRUDE OIL prices. Bullish = likely pushes crude up (supply risk, sanctions, "
    "OPEC cuts, demand strength, conflict near oil infrastructure). Bearish = likely pushes "
    "crude down (supply returning, demand weakness, ceasefires/de-escalation, builds, OPEC "
    "increases). Neutral = no clear directional read for crude. Be decisive but honest: most "
    "general news is neutral. Magnitude is 0-100 (how strongly it moves crude)."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "impact": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                    "magnitude": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["i", "impact", "magnitude", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def available() -> bool:
    """True if an API key is configured (env or .env)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from dotenv import load_dotenv

        from . import REPO_ROOT

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic

    return anthropic.Anthropic()


def classify(items: List[Dict], chunk_size: int = 20, log=None) -> Dict[str, Dict]:
    """Classify items [{id, title, summary}] -> {id: {impact, score, rationale}}.

    Score is signed: +magnitude for bullish, -magnitude for bearish, 0 for neutral.
    """
    log = log or (lambda *_: None)
    if not available():
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run LLM sentiment.")
    client = _client()
    out: Dict[str, Dict] = {}

    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        listing = "\n".join(
            "%d. %s" % (n, (it["title"] + (" — " + it["summary"] if it.get("summary") else "")))[:300]
            for n, it in enumerate(chunk)
        )
        prompt = (
            "Classify each headline's impact on crude oil. Return one result per headline, "
            "keyed by its number `i`.\n\n" + listing
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            results = json.loads(text).get("results", [])
        except json.JSONDecodeError:
            log("  [warn] unparseable response for chunk at %d" % start)
            continue
        for r in results:
            idx = r.get("i")
            if idx is None or idx < 0 or idx >= len(chunk):
                continue
            impact = r.get("impact", "neutral")
            mag = max(0, min(100, int(r.get("magnitude", 0))))
            score = mag if impact == "bullish" else -mag if impact == "bearish" else 0
            out[chunk[idx]["id"]] = {
                "impact": impact,
                "score": score,
                "rationale": (r.get("rationale") or "")[:240],
            }
        log("  classified %d/%d" % (min(start + chunk_size, len(items)), len(items)))
    return out

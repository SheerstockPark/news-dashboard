"""Ask-the-news — answer a question from the local news corpus, with citations.

At this corpus size (a few thousand headlines) no vector DB is needed: we retrieve by
keyword overlap with the question, hand the top matches to Claude, and ask for a concise
answer that cites sources by number. Fail-soft and gated on ANTHROPIC_API_KEY.
"""

import re
from typing import Dict, List

from . import db
from .llm_sentiment import MODEL, available

_STOP = {"the", "a", "an", "to", "of", "in", "on", "is", "are", "for", "and", "what",
         "whats", "what's", "how", "why", "when", "where", "latest", "news", "about",
         "any", "tell", "me", "do", "does", "did", "with", "this", "that", "happening"}


def _terms(q: str) -> List[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (q or "").lower()).split()
            if len(w) > 2 and w not in _STOP]


def retrieve(question: str, k: int = 25) -> List[Dict]:
    """Top-k corpus articles most relevant to the question (keyword overlap + relevance)."""
    terms = _terms(question)
    pool = db.query_articles(limit=1500, min_relevance=0)
    if not terms:
        return pool[:k]
    scored = []
    for a in pool:
        hay = (a["title"] + " " + (a.get("summary") or "")).lower()
        hits = sum(hay.count(t) for t in terms)
        if hits:
            scored.append((hits * 10 + a.get("relevance", 0), a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:k]]


def answer(question: str, model: str = None) -> Dict:
    """Return {text, sources:[article,...]}. Raises if no API key."""
    if not available():
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot answer.")
    import anthropic

    arts = retrieve(question)
    if not arts:
        return {"text": "I couldn't find anything in the current news on that.", "sources": []}
    context = "\n".join(
        "[%d] (%s) %s — %s" % (i + 1, a["source_name"], a["title"], (a.get("summary") or "")[:200])
        for i, a in enumerate(arts)
    )
    system = (
        "You answer questions for an oil-trading desk using ONLY the provided news snippets. "
        "Be concise and specific. Cite sources inline as [n] matching the snippet numbers. "
        "If the snippets don't contain the answer, say so plainly. Do not speculate beyond them."
    )
    user = "SNIPPETS:\n%s\n\nQUESTION: %s" % (context, question)
    resp = anthropic.Anthropic().messages.create(
        model=model or MODEL, max_tokens=700, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return {"text": text, "sources": arts}

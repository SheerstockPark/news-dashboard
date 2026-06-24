"""Real-time alerts — push high-impact / watchlist news to Telegram (or email).

Checks recently-ingested articles, picks the ones worth interrupting a trader for
(high oil-relevance, strong crude impact, or a watchlist keyword), and pushes them.
De-dupes via data/alerts_state.json so each story alerts once.

Recommended channel: Telegram (instant, free). Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.
Email fallback reuses the SMTP_* vars from the digest. Fail-soft and gated.
"""

import json
import os
from typing import Dict, List

import requests

from . import DATA_DIR, db

STATE_PATH = DATA_DIR / "alerts_state.json"


def _env(name, default=""):
    if not os.environ.get(name):
        try:
            from dotenv import load_dotenv

            from . import REPO_ROOT

            load_dotenv(REPO_ROOT / ".env")
        except Exception:
            pass
    return os.environ.get(name, default)


def channel() -> str:
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"):
        return "telegram"
    if _env("SMTP_USER") and _env("SMTP_PASS") and _env("DIGEST_TO"):
        return "email"
    return "none"


def _load_state() -> set:
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("sent", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_state(sent: set) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # keep the most recent 5000 ids
    STATE_PATH.write_text(json.dumps({"sent": list(sent)[-5000:]}), encoding="utf-8")


def _qualifies(a: Dict, min_relevance: int, min_impact: int, keywords: List[str]) -> bool:
    if a.get("relevance", 0) >= min_relevance:
        return True
    if abs(a.get("impact_score", 0)) >= min_impact and a.get("impact") != "neutral":
        return True
    if keywords:
        hay = (a["title"] + " " + (a.get("summary") or "")).lower()
        if any(k in hay for k in keywords):
            return True
    return False


def _send_telegram(text: str) -> bool:
    token, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    r = requests.post(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        json={"chat_id": chat, "text": text, "parse_mode": "Markdown",
              "disable_web_page_preview": False},
        timeout=15,
    )
    return r.ok


def _send_email(subject: str, text: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(text)
    msg["Subject"] = subject
    msg["From"] = _env("DIGEST_FROM") or _env("SMTP_USER")
    msg["To"] = _env("DIGEST_TO")
    with smtplib.SMTP(_env("SMTP_HOST", "smtp.gmail.com"), int(_env("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(_env("SMTP_USER"), _env("SMTP_PASS"))
        s.sendmail(msg["From"], [x.strip() for x in msg["To"].split(",")], msg.as_string())
    return True


def _format(a: Dict) -> str:
    badge = "🟢 BULLISH" if a.get("impact") == "bullish" else "🔴 BEARISH" if a.get("impact") == "bearish" else "⚪"
    return "*%s* · rel %d · %s\n%s\n%s" % (
        a["source_name"], a.get("relevance", 0), badge, a["title"], a.get("url", ""))


def run_once(min_relevance=70, min_impact=60, keywords=None, limit=200, log=None) -> Dict:
    """Alert on newly-qualifying articles. First run baselines silently. Returns summary."""
    log = log or (lambda *_: None)
    ch = channel()
    if ch == "none":
        return {"sent": 0, "channel": "none", "note": "no channel configured"}

    keywords = [k.strip().lower() for k in (keywords or []) if k.strip()]
    sent = _load_state()
    first_run = not STATE_PATH.exists()
    pool = db.query_articles(limit=limit, min_relevance=0)
    fresh = [a for a in pool if a["id"] not in sent and _qualifies(a, min_relevance, min_impact, keywords)]

    if first_run:
        for a in pool:
            sent.add(a["id"])
        _save_state(sent)
        log("Baselined %d existing articles (no alerts sent on first run)." % len(pool))
        return {"sent": 0, "channel": ch, "note": "baselined"}

    pushed = 0
    for a in fresh:
        text = _format(a)
        try:
            ok = _send_telegram(text) if ch == "telegram" else _send_email("Oil alert: " + a["title"][:80], text)
        except Exception as exc:  # noqa: BLE001
            log("  [FAIL] %s" % exc)
            ok = False
        if ok:
            sent.add(a["id"])
            pushed += 1
            log("  [sent] %s" % a["title"][:70])
    _save_state(sent)
    return {"sent": pushed, "channel": ch, "candidates": len(fresh)}

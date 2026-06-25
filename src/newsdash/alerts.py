"""Real-time alerts — push high-impact / watchlist news to Telegram or email.

Two paths:
  * run_once()  — Telegram-first feed (one message per qualifying story), oil-desk tuned.
  * run_urgent() — intra-day EMAIL for *very big* headlines only (high bar, cross-asset,
                   not oil-only), batched into a single email so the inbox stays clean.
De-dupes via separate state files so each story alerts at most once per path.

Fail-soft and gated. Email goes through the provider-agnostic mailer (Resend or SMTP).
"""

import html
import json
import os
from datetime import datetime, timezone
from typing import Dict, List

import requests

from . import DATA_DIR, db, mailer

STATE_PATH = DATA_DIR / "alerts_state.json"  # Telegram-feed dedupe (run_once); urgent path uses the DB

# Shock terms that make a headline "urgent" even if its oil-relevance score is moderate —
# geopolitical / macro / market ruptures the principal would want pinged on intra-day.
URGENT_KEYWORDS = [
    "invasion", "invades", "war", "missile", "airstrike", "air strike", "attack",
    "strikes ", "nuclear", "ceasefire", "sanction", "embargo", "blockade", "hormuz",
    "strait", "coup", "assassinat", "opec", "spr ", "emergency", "default", "collapse",
    "crash", "plunge", "halts trading", "circuit breaker", "tariff", "shutdown",
    "rate cut", "rate hike", "downgrade", "bankrupt",
]


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


def _load_state(path=STATE_PATH) -> set:
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("sent", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_state(sent: set, path=STATE_PATH) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # keep the most recent 5000 ids
    path.write_text(json.dumps({"sent": list(sent)[-5000:]}), encoding="utf-8")


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


# ---------------------------------------------------------------------------
# Urgent intra-day EMAIL path — very big headlines only, batched into one email.
# ---------------------------------------------------------------------------

def _urgent_qualifies(a: Dict, min_relevance: int, min_impact: int, keywords: List[str]) -> bool:
    if a.get("relevance", 0) >= min_relevance:
        return True
    if abs(a.get("impact_score", 0)) >= min_impact and a.get("impact") != "neutral":
        return True
    if keywords and a.get("relevance", 0) >= 35:  # keyword shocks, but with a relevance floor
        hay = (a["title"] + " " + (a.get("summary") or "")).lower()
        if any(k in hay for k in keywords):
            return True
    return False


def _urgent_email_html(items: List[Dict], now: datetime) -> str:
    rows = ""
    for a in items:
        imp = a.get("impact")
        badge = ""
        if imp == "bullish":
            badge = '<span style="background:#16c784;color:#04130d;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:800">BULLISH</span>'
        elif imp == "bearish":
            badge = '<span style="background:#ea3943;color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:800">BEARISH</span>'
        rows += (
            '<tr><td style="padding:12px 0;border-bottom:1px solid #1e2733">'
            '<a href="%s" style="color:#e6edf3;text-decoration:none;font-weight:700;font-size:16px">%s</a>'
            '<div style="margin-top:5px;color:#7d8b9a;font-size:12px">'
            '<span style="color:#9fb2c4;font-weight:600">%s</span> &middot; '
            '<span style="color:#ffa45c">relevance %d</span>%s</div></td></tr>'
            % (html.escape(a.get("url", "")), html.escape(a["title"]),
               html.escape(a["source_name"]), a.get("relevance", 0),
               (" &middot; " + badge) if badge else "")
        )
    return """\
<!DOCTYPE html><html><body style="margin:0;background:#0b0f14;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:680px;margin:0 auto;padding:24px;background:#0b0f14;color:#e6edf3">
  <div style="font-size:13px;font-weight:800;color:#ea3943;text-transform:uppercase;letter-spacing:.5px">&#128680; Urgent market headline%s</div>
  <div style="font-size:18px;font-weight:800;margin:2px 0 14px">SHEERSTOCK&nbsp;PARK</div>
  <table width="100%%" cellspacing="0">%s</table>
  <div style="color:#5b6b7a;font-size:11px;margin-top:18px">Sent because these crossed the urgent threshold &middot; %s</div>
</div></body></html>""" % ("s" if len(items) > 1 else "", rows, now.strftime("%H:%M UTC, %d %b %Y"))


def run_urgent(min_relevance: int = 78, min_impact: int = 72, keywords: List[str] = None,
               limit: int = 200, log=None) -> Dict:
    """Email a batch of newly-qualifying *very big* headlines. First run baselines silently.

    Dedupe state lives in the DB (db.alert_state, scope='urgent') so it survives the ephemeral
    CI runners the cron runs on — a local file would re-baseline every run and never send.
    """
    log = log or (lambda *_: None)
    if not mailer.configured():
        return {"sent": 0, "channel": "none", "note": "no email backend (set RESEND_API_KEY or SMTP_*)"}

    db.init_db()  # ensure alert_state table exists (idempotent)
    kw = URGENT_KEYWORDS if keywords is None else [k.strip().lower() for k in keywords if k.strip()]
    already = db.alerted_ids("urgent")
    pool = db.query_articles(limit=limit, min_relevance=0)

    if not already:  # first run on a fresh DB: baseline the backlog, don't blast it
        db.mark_alerted([a["id"] for a in pool], "urgent")
        log("Baselined %d existing articles (no urgent email on first run)." % len(pool))
        return {"sent": 0, "channel": "email", "note": "baselined"}

    fresh = [a for a in pool
             if a["id"] not in already and _urgent_qualifies(a, min_relevance, min_impact, kw)]
    if not fresh:
        return {"sent": 0, "channel": "email", "candidates": 0}

    now = datetime.now(timezone.utc)
    subject = "🚨 Sheerstock Park — %d urgent headline%s" % (len(fresh), "s" if len(fresh) > 1 else "")
    try:
        ok = mailer.send_html(subject, _urgent_email_html(fresh, now))
    except Exception as exc:  # noqa: BLE001 — keep the cron green
        log("  [FAIL] %s" % exc)
        ok = False
    if ok:
        db.mark_alerted([a["id"] for a in fresh], "urgent")
        for a in fresh:
            log("  [urgent] %s" % a["title"][:70])
    return {"sent": len(fresh) if ok else 0, "channel": "email",
            "backend": mailer.backend(), "candidates": len(fresh)}

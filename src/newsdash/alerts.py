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
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests

from . import DATA_DIR, db, email_render, mailer

STATE_PATH = DATA_DIR / "alerts_state.json"  # Telegram-feed dedupe (run_once); urgent path uses the DB

# Rupture terms for the urgent path — matched with WORD BOUNDARIES against the TITLE only
# (a substring match once fired on "award" ⊃ "war"). Curated HARD 2026-07-13 after the user
# reported far too many urgent emails: everything that appears in routine daily coverage is
# out (missile, airstrike, drone strike, sanctions, opec, spr, ceasefire, downgrade — those
# belong in the briefings). What remains is the vocabulary of genuine market ruptures.
URGENT_KEYWORDS = [
    "invasion", "invades", "declares war", "declaration of war", "nuclear",
    "hormuz", "blockade", "embargo", "no-fly zone", "martial law",
    "coup", "assassinat", "state of emergency", "emergency meeting",
    "force majeure", "halts production", "production halted",
    "default", "defaults", "bankruptcy", "collapse", "collapses",
    "crash", "crashes", "plunge", "plunges", "halts trading", "trading halted",
    "circuit breaker", "capital controls", "shutdown",
    # Fed DECISIONS, not chatter — "rate hike/cut" alone matched every speculation piece
    # ("rate hike bets", "could mean a rate hike"). Decision headlines are verb-led.
    "raises rates", "cuts rates", "hikes rates", "emergency rate",
]

# Sources whose *pronouncements* the desk wants first — Trump's raw Truth Social feed and
# the Google News voice sweeps (see config/sources.yaml). Matched as substrings of the
# lower-cased source_name. These get a deliberately lower urgent bar (user 2026-07-13:
# "focus more on outlets such as Truth Social").
VOICE_SOURCES = ("truth social", "trump says", "fed speak", "musk / x")


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
            ok = _send_telegram(text) if ch == "telegram" \
                else _send_email("Sheerstock Park · Oil alert — " + a["title"][:80], text)
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
    """BIG headlines only; opinion & sport never qualify.

    Retuned 2026-07-13 after the user reported far too many urgent emails (the 2026-07-04
    rules still admitted routine coverage via the keyword+rel55 path). Three ways in:
      A) a rupture keyword in the TITLE of a clearly relevant story (rel >= min_relevance);
      B) an extreme directional shock (|impact| >= min_impact) on a relevant story (rel >= 60);
      C) a market-relevant pronouncement from a voice feed (Truth Social, Trump-says,
         Fed-speak, Musk-X) — deliberately lower bar: the desk wants these first.
    """
    import re

    from . import tagging

    title = a.get("title") or ""
    if tagging._OFF_TOPIC.search(title):  # noqa: SLF001 — same-package heuristic
        return False
    # Question headlines are analysis/explainers, never ruptures ("Will OPEC intervene
    # again?", "Should you still buy oil stocks?") — ruptures are declarative. Check before
    # the "- Outlet" suffix, where Google News hides the question mark.
    if title.rsplit(" - ", 1)[0].rstrip().endswith("?"):
        return False
    t = title.lower()
    kw_hit = bool(keywords) and any(
        re.search(r"\b" + re.escape(k) + r"\b", t) for k in keywords)
    rel = a.get("relevance", 0)
    shock = abs(a.get("impact_score", 0))

    # A) Rupture word in the title of a clearly relevant story.
    if kw_hit and rel >= min_relevance:
        return True
    # B) Extreme directional read on a relevant story.
    if shock >= min_impact and a.get("impact") != "neutral" and rel >= 60:
        return True
    # C) Voice-feed pronouncement that reads market-relevant.
    src = (a.get("source_name") or "").lower()
    if any(v in src for v in VOICE_SOURCES) and rel >= 60 and (shock >= 40 or kw_hit):
        return True
    return False


def _urgent_email_html(items: List[Dict], now: datetime) -> str:
    rows = ""
    for a in items:
        imp = a.get("impact")
        badge = ""
        if imp == "bullish":
            badge = (' &middot; <span style="background:#16c784;color:#04130d;border-radius:4px;'
                     'padding:1px 7px;font-size:11px;font-weight:800">&#9650; BULLISH</span>')
        elif imp == "bearish":
            badge = (' &middot; <span style="background:#ea3943;color:#fff;border-radius:4px;'
                     'padding:1px 7px;font-size:11px;font-weight:800">&#9660; BEARISH</span>')
        ago = email_render._ago(a.get("published_at") or a.get("fetched_at"), now)
        ago_chip = (" &middot; " + ago) if ago else ""
        rows += (
            '<tr><td style="padding:13px 0;border-bottom:1px solid #1e2733">'
            '<a href="%s" style="color:#e6edf3;text-decoration:none;font-weight:700;'
            'font-size:16px;line-height:1.4">%s</a>'
            '<div style="margin-top:5px;color:#7d8b9a;font-size:12px">'
            '<span style="color:#9fb2c4;font-weight:600">%s</span>%s%s</div></td></tr>'
            % (html.escape(a.get("url", "")), html.escape(a["title"]),
               html.escape(a["source_name"]), ago_chip, badge)
        )
    return """\
<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
</head><body bgcolor="#0b0f14" style="margin:0;padding:0;background:#0b0f14;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:680px;margin:0 auto;padding:20px 22px 26px;background:#0b0f14;color:#e6edf3">
  <div style="height:3px;background:#ea3943;border-radius:2px;margin-bottom:16px"></div>
  <table width="100%%" cellspacing="0" cellpadding="0"><tr>
    <td style="font-size:20px;font-weight:800;color:#e6edf3;letter-spacing:.5px">SHEERSTOCK&nbsp;PARK</td>
    <td align="right" style="vertical-align:middle"><span style="background:#2a1215;color:#ff6b74;border:1px solid #5c1f26;border-radius:6px;padding:3px 9px;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;white-space:nowrap">&#128680; Urgent</span></td>
  </tr></table>
  <div style="color:#7d8b9a;font-size:13px;margin:2px 0 12px">%s market headline%s &middot; %s</div>
  <table width="100%%" cellspacing="0">%s</table>
  <div style="color:#5b6b7a;font-size:11px;line-height:1.6;margin-top:18px;padding-top:12px;border-top:1px solid #1e2733">Sent within minutes of these crossing the desk's urgent threshold. Full context in the next briefing.<br>Created by Saavan Sumray-Roots.</div>
</div></body></html>""" % (len(items), "s" if len(items) > 1 else "",
                           now.strftime("%H:%M UTC &middot; %a %d %b"), rows)


URGENT_STATE_PATH = DATA_DIR / "urgent_state.json"

# One big story arrives as dozens of near-identical headlines from 57 feeds. These control
# the echo-storm: similar titles collapse to the strongest version inside a batch, echoes of
# stories alerted in the last day are suppressed entirely, and an email carries at most
# URGENT_MAX_ITEMS distinct stories (the rest wait, unmarked, for the next window).
URGENT_MAX_ITEMS = 8
_ECHO_SUPPRESS_HOURS = 24
_TITLE_STOPWORDS = frozenset(
    "a an the of to in on at as and or for with by from after amid over into its his her "
    "their our your says said say saying us will would could may might be is are was were "
    "has have had new latest breaking live update updates news report reports".split())


# Headline verbs that outlets swap freely for the same event — folded before matching so
# "Iran shuts Hormuz, shipping halted" reads as an echo of "Iran closes Hormuz". Direction
# reversals stay safe: _same_story() refuses to merge opposite bullish/bearish reads.
_TITLE_SYNONYMS = {
    "shut": "close", "shuts": "close", "shutting": "close",
    "halt": "close", "halts": "close", "halted": "close",
    "reopen": "open", "reopens": "open", "reopened": "open",
    "resume": "open", "resumes": "open", "resumed": "open",
    "restart": "open", "restarts": "open", "restarted": "open",
}


def _title_tokens(title: str) -> frozenset:
    """4-char prefix signatures of the meaningful title words — outlets rephrase the same
    story with different morphology (closes/closure/closed), and prefixes ride over that."""
    t = (title or "").split(" - ")[0].lower()  # drop the trailing "- Outlet" suffix
    words = (_TITLE_SYNONYMS.get(w, w) for w in re.findall(r"[a-z0-9']+", t))
    return frozenset(w[:4] for w in words if w not in _TITLE_STOPWORDS and len(w) > 2)


def _similar_titles(t1: str, t2: str) -> bool:
    a, b = _title_tokens(t1), _title_tokens(t2)
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= 0.5 or inter >= 0.8 * min(len(a), len(b))


def _same_story(a_title: str, a_impact: str, b_title: str, b_impact: str) -> bool:
    """Similar wording AND not a directional reversal — 'Hormuz reopens' must never be
    swallowed as an echo of 'Hormuz closes' (they share tokens but opposite market impact)."""
    if {a_impact, b_impact} == {"bullish", "bearish"}:
        return False
    return _similar_titles(a_title, b_title)


def _cluster_batch(items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Collapse near-duplicate headlines: returns (representatives, duplicates).

    Strongest version of each story (relevance, then |impact|) represents the cluster."""
    ranked = sorted(items, key=lambda a: (a.get("relevance", 0),
                                          abs(a.get("impact_score", 0))), reverse=True)
    reps, dups = [], []
    for a in ranked:
        if any(_same_story(a["title"], a.get("impact", ""), r["title"], r.get("impact", ""))
               for r in reps):
            dups.append(a)
        else:
            reps.append(a)
    return reps, dups


def _load_urgent_state():
    """File-backed urgent state, or None if it doesn't exist yet (=> baseline silently).

    On GitHub runners the file survives between ephemeral jobs via actions/cache — see
    .github/workflows/urgent-loop.yml. Shape: {"sent": [ids...], "last_email_at": iso|null}.
    """
    try:
        return json.loads(URGENT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_urgent_state(state: Dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state["sent"] = list(state["sent"])[-5000:]
    URGENT_STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def run_urgent(min_relevance: int = 70, min_impact: int = 80, keywords: List[str] = None,
               limit: int = 200, log=None) -> Dict:
    """Email a batch of newly-qualifying *very big* headlines. First run baselines silently.

    Dedupe state: Turso (db.alert_state, scope='urgent') when TURSO_* env is set, else the
    local file above. The GitHub urgent loop deliberately runs WITHOUT Turso credentials
    since 2026-07-13 — its every-60s polling burned through the free-tier read quota and got
    the whole database read-blocked. Articles then come from the runner-local SQLite that
    --fetch fills, and state continuity comes from actions/cache.
    """
    log = log or (lambda *_: None)
    if not mailer.configured():
        return {"sent": 0, "channel": "none", "note": "no email backend (set RESEND_API_KEY or SMTP_*)"}

    use_db = db.using_turso()
    kw = URGENT_KEYWORDS if keywords is None else [k.strip().lower() for k in keywords if k.strip()]

    if use_db:
        db.init_db()  # ensure alert_state table exists (idempotent)
        already = db.alerted_ids("urgent")
        first_run = not already
        last = db.last_sent("urgent")
        state = None
    else:
        state = _load_urgent_state()
        first_run = state is None
        state = state if state is not None else {"sent": [], "last_email_at": None}
        already = set(state["sent"])
        last = state.get("last_email_at")

    pool = db.query_articles(limit=limit, min_relevance=0)

    if first_run:  # fresh state: baseline the backlog, don't blast it
        ids = [a["id"] for a in pool]
        if use_db:
            db.mark_alerted(ids, "urgent")
        else:
            state["sent"] = list(already.union(ids))
            _save_urgent_state(state)
        log("Baselined %d existing articles (no urgent email on first run)." % len(pool))
        return {"sent": 0, "channel": "email", "note": "baselined"}

    fresh = [a for a in pool
             if a["id"] not in already and _urgent_qualifies(a, min_relevance, min_impact, kw)]
    if not fresh:
        return {"sent": 0, "channel": "email", "candidates": 0}

    now = datetime.now(timezone.utc)

    # Echo suppression (file mode): a story we already alerted on keeps arriving reworded
    # from other outlets for hours — those echoes are seen-and-buried, never re-alerted.
    echo_ids: List[str] = []
    if state is not None:
        cutoff = (now - timedelta(hours=_ECHO_SUPPRESS_HOURS)).isoformat()
        # entries: [sent_at_iso, title, impact]
        recent = [e for e in state.get("recent_titles", []) if e and e[0] >= cutoff][-200:]
        state["recent_titles"] = recent
        echoes = [a for a in fresh
                  if any(_same_story(a["title"], a.get("impact", ""), e[1],
                                     e[2] if len(e) > 2 else "") for e in recent)]
        if echoes:
            echo_ids = [a["id"] for a in echoes]
            state["sent"].extend(echo_ids)
            _save_urgent_state(state)
            log("echo-suppressed %d headline(s) (story already alerted)" % len(echoes))
            fresh = [a for a in fresh if a["id"] not in set(echo_ids)]
            if not fresh:
                return {"sent": 0, "channel": "email", "candidates": 0, "note": "echoes only"}

    # Collapse the batch to distinct stories; duplicates ride along as marked-seen.
    reps, dups = _cluster_batch(fresh)
    if len(reps) > URGENT_MAX_ITEMS:  # beyond-wild day: the rest wait for the next window
        log("capping batch at %d distinct stories (%d held for next window)"
            % (URGENT_MAX_ITEMS, len(reps) - URGENT_MAX_ITEMS))
        reps = reps[:URGENT_MAX_ITEMS]
    fresh = reps
    dup_ids = [a["id"] for a in dups
               if any(_same_story(a["title"], a.get("impact", ""), r["title"],
                                  r.get("impact", "")) for r in reps)]
    # Cooldown: at most one urgent email per URGENT_COOLDOWN_MIN minutes (default 120). During
    # a hot news run, candidates accumulate unmarked and go out as ONE batch when the window
    # reopens — the inbox gets periodic digests of the storm, not a drip-feed of pings.
    cooldown_min = int(_env("URGENT_COOLDOWN_MIN") or "120")
    if last and cooldown_min > 0:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_min = (now - last_dt).total_seconds() / 60.0
            if age_min < cooldown_min:
                log("cooldown: holding %d candidate(s) — %.0fm since last urgent (window %dm)"
                    % (len(fresh), age_min, cooldown_min))
                return {"sent": 0, "channel": "email", "candidates": len(fresh), "note": "cooldown"}
        except ValueError:
            pass
    # Subject leads with the actual top headline so the inbox tells the story at a glance.
    lead = max(fresh, key=lambda a: (a.get("relevance", 0), abs(a.get("impact_score", 0))))
    lt = lead["title"]
    lt = (lt[:78] + "…") if len(lt) > 79 else lt
    subject = ("🚨 URGENT · %s" % lt) if len(fresh) == 1 \
        else ("🚨 URGENT · %s  (+%d more)" % (lt, len(fresh) - 1))
    try:
        ok = mailer.send_html(subject, _urgent_email_html(fresh, now))
    except Exception as exc:  # noqa: BLE001 — keep the cron green
        log("  [FAIL] %s" % exc)
        ok = False
    if ok:
        ids = [a["id"] for a in fresh] + dup_ids  # bury each sent story's echoes with it
        if use_db:
            db.mark_alerted(ids, "urgent")
        else:
            state["sent"].extend(ids)
            state["last_email_at"] = now.isoformat()
            state.setdefault("recent_titles", []).extend(
                [now.isoformat(), a["title"], a.get("impact", "")] for a in fresh)
            _save_urgent_state(state)
        for a in fresh:
            log("  [urgent] %s" % a["title"][:70])
    return {"sent": len(fresh) if ok else 0, "channel": "email",
            "backend": mailer.backend(), "candidates": len(fresh)}

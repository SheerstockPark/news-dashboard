#!/usr/bin/env python3
"""Generate the AI cross-asset briefing and email it to Neil (morning / evening editions).

Pulls the latest news + prices, asks Claude for the sectioned briefing (macro, geopolitical,
energy/fuel, reserves, market movers), renders it into a branded HTML email and sends it via
the configured backend (Resend if RESEND_API_KEY set, else SMTP). Designed to run from a
GitHub Actions cron twice a day.

Usage:
    python tools/send_briefing.py --edition Morning           # generate + email
    python tools/send_briefing.py --edition Evening --fetch    # ingest fresh feeds first
    python tools/send_briefing.py --edition Morning --no-send  # build + save only (dry run)

Needs: ANTHROPIC_API_KEY (brief), plus an email backend (RESEND_API_KEY or SMTP_* + DIGEST_TO).
Exits 0 with a notice — never a hard failure — if something isn't configured.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import REPO_ROOT  # noqa: E402
from newsdash import brief, db, eia, email_render, events, ingest, mailer, prices  # noqa: E402

try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass


def build_briefing(edition: str = "Morning", fetch: bool = False,
                   min_relevance: int = 0, log=print, brief_text: str = None) -> dict:
    """Generate + render one briefing edition into a ready-to-send email — NO send.

    Returns {"subject", "html", "text", "model", "edition", "path"} or {} if it can't build
    (e.g. no ANTHROPIC_API_KEY). Splitting build from send lets the worker generate once and
    then retry *sending* on later ticks without re-paying for generation — important when the
    send path is temporarily failing (e.g. a blocked SMTP egress).

    brief_text: pre-written briefing Markdown (same **section** + bullet shape the generator
    produces). Skips the Claude call entirely — used when something else wrote the prose, e.g.
    a scheduled Claude routine running on a subscription instead of API credit.
    """
    if brief_text is None and not brief.available():
        log("ANTHROPIC_API_KEY not set — cannot generate the briefing. Skipping.")
        return {}

    if fetch:
        s = ingest.run_once()
        log("Fetched: %d new, %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    db.init_db()
    now = datetime.now(timezone.utc)
    articles = db.query_articles(limit=400, min_relevance=min_relevance)
    quotes, spreads = prices.get_quotes(), prices.get_spreads()

    if brief_text is not None:
        payload = {"text": brief_text, "edition": edition, "model": "provided"}
        log("%s briefing text provided (%d chars) — skipping generation." % (edition, len(brief_text)))
    else:
        payload = brief.generate(
            articles, quotes, spreads,
            equities=prices.get_quotes(prices.MARKET_MOVERS),
            eia=eia.get_inventories(),
            edition=edition,
        )
        log("%s briefing generated (%s)." % (payload["edition"], payload["model"]))

    upcoming = events.upcoming(now, limit=5)
    # Deterministic, clickable source links: the real top articles behind the brief.
    top_links = sorted(articles, key=lambda a: (a.get("relevance", 0),
                                                a.get("published_at") or a.get("fetched_at") or ""),
                       reverse=True)[:10]
    html_body = email_render.briefing_html(payload["text"], edition, quotes, spreads,
                                           upcoming, top_links, now)
    text_body = email_render.briefing_text(payload["text"], edition)

    # Save a copy to reports/ for the record (and easy local preview).
    reports = REPO_ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / ("briefing-%s-%s.html" % (now.strftime("%Y%m%d"), edition.lower()))
    out.write_text(html_body, encoding="utf-8")
    log("Saved: %s" % out)

    subject = "Sheerstock Park — %s Briefing · %s" % (edition, now.strftime("%a %d %b %Y"))
    return {"subject": subject, "html": html_body, "text": text_body,
            "model": payload["model"], "edition": edition, "path": str(out)}


def _uk_today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London")).strftime("%Y-%m-%d")
    except Exception:  # pragma: no cover
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def send_briefing(edition: str = "Morning", fetch: bool = False, no_send: bool = False,
                  min_relevance: int = 0, log=print, brief_text: str = None,
                  force: bool = False) -> dict:
    """Build + (optionally) email one briefing edition. Reusable by the CLI and the worker.

    Delivery is deduped per UK day via alert_state scope 'briefing-<edition>' — the same mark
    the worker and the watchdog use. That makes every sender (worker, GitHub cron, a scheduled
    routine) mutually exclusive: whoever sends first today wins, the rest skip. force=True
    overrides the skip for deliberate manual re-sends.

    Returns {"sent": bool, "edition": ..., "model": ..., "html": path}. Fail-soft: never raises
    on a send error — logs it and returns sent=False so a caller loop stays alive.
    """
    scope = "briefing-" + edition.strip().lower()
    today = _uk_today()
    if not no_send and not force:
        db.init_db()
        if today in db.alerted_ids(scope):
            log("%s briefing already delivered today (%s) — skipping (use --force to re-send)."
                % (edition, today))
            return {"sent": False, "edition": edition, "note": "already sent today"}

    if not no_send and not mailer.configured():
        log("No email backend configured (set RESEND_API_KEY or SMTP_* + DIGEST_TO). "
            "Building HTML only.")

    built = build_briefing(edition, fetch=fetch, min_relevance=min_relevance, log=log,
                           brief_text=brief_text)
    if not built:
        return {"sent": False, "edition": edition, "note": "could not build"}

    if no_send:
        return {"sent": False, "edition": edition, "model": built["model"], "html": built["path"]}

    to = mailer.briefing_recipients()  # DIGEST_TO + briefing-only extras (BRIEFING_EXTRA_TO)
    try:
        sent = mailer.send_html(built["subject"], built["html"], built["text"], to=to)
    except Exception as exc:  # noqa: BLE001 — fail-soft so the cron / worker loop stays alive
        log("Email send failed: %s" % exc)
        return {"sent": False, "edition": edition, "model": built["model"], "error": str(exc)}
    if sent:
        db.mark_alerted([today], scope)  # confirmed-delivery mark: dedupe + watchdog heartbeat
        log("Emailed via %s to %s" % (mailer.backend(), ", ".join(to)))
    else:
        log("Email not sent (backend unconfigured).")
    return {"sent": bool(sent), "edition": edition, "model": built["model"], "html": built["path"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate + email the AI cross-asset briefing.")
    ap.add_argument("--edition", default="Morning", help="Morning / Evening (label + subject).")
    ap.add_argument("--fetch", action="store_true", help="Ingest fresh feeds first.")
    ap.add_argument("--no-send", action="store_true", help="Build + save HTML only; don't email.")
    ap.add_argument("--min-relevance", type=int, default=0)
    ap.add_argument("--text-file", default=None,
                    help="Path to pre-written briefing Markdown — skips the Claude call "
                         "(for prose written by a scheduled Claude routine).")
    ap.add_argument("--force", action="store_true",
                    help="Send even if a briefing was already delivered today.")
    args = ap.parse_args()

    brief_text = None
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as fh:
            brief_text = fh.read().strip()
        if not brief_text:
            print("--text-file %s is empty — refusing to send a blank briefing." % args.text_file)
            return 1

    send_briefing(edition=args.edition, fetch=args.fetch, no_send=args.no_send,
                  min_relevance=args.min_relevance, brief_text=brief_text, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())

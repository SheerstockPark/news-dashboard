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


def send_briefing(edition: str = "Morning", fetch: bool = False, no_send: bool = False,
                  min_relevance: int = 0, log=print) -> dict:
    """Build + (optionally) email one briefing edition. Reusable by the CLI and the worker.

    Returns {"sent": bool, "edition": ..., "model": ..., "html": path}. Fail-soft: never raises
    on a send error — logs it and returns sent=False so a caller loop stays alive.
    """
    if not brief.available():
        log("ANTHROPIC_API_KEY not set — cannot generate the briefing. Skipping.")
        return {"sent": False, "edition": edition, "note": "no ANTHROPIC_API_KEY"}
    if not no_send and not mailer.configured():
        log("No email backend configured (set RESEND_API_KEY or SMTP_* + DIGEST_TO). "
            "Building HTML only.")

    if fetch:
        s = ingest.run_once()
        log("Fetched: %d new, %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    db.init_db()
    now = datetime.now(timezone.utc)
    articles = db.query_articles(limit=400, min_relevance=min_relevance)
    quotes, spreads = prices.get_quotes(), prices.get_spreads()

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

    if no_send:
        return {"sent": False, "edition": edition, "model": payload["model"], "html": str(out)}

    subject = "Sheerstock Park — %s Briefing · %s" % (edition, now.strftime("%a %d %b %Y"))
    try:
        sent = mailer.send_html(subject, html_body, text_body)
    except Exception as exc:  # noqa: BLE001 — fail-soft so the cron / worker loop stays alive
        log("Email send failed: %s" % exc)
        return {"sent": False, "edition": edition, "model": payload["model"], "error": str(exc)}
    if sent:
        log("Emailed via %s to %s" % (mailer.backend(), ", ".join(mailer.recipients())))
    else:
        log("Email not sent (backend unconfigured).")
    return {"sent": bool(sent), "edition": edition, "model": payload["model"], "html": str(out)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate + email the AI cross-asset briefing.")
    ap.add_argument("--edition", default="Morning", help="Morning / Evening (label + subject).")
    ap.add_argument("--fetch", action="store_true", help="Ingest fresh feeds first.")
    ap.add_argument("--no-send", action="store_true", help="Build + save HTML only; don't email.")
    ap.add_argument("--min-relevance", type=int, default=0)
    args = ap.parse_args()

    send_briefing(edition=args.edition, fetch=args.fetch, no_send=args.no_send,
                  min_relevance=args.min_relevance)
    return 0


if __name__ == "__main__":
    sys.exit(main())

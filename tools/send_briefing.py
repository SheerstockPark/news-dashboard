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


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate + email the AI cross-asset briefing.")
    ap.add_argument("--edition", default="Morning", help="Morning / Evening (label + subject).")
    ap.add_argument("--fetch", action="store_true", help="Ingest fresh feeds first.")
    ap.add_argument("--no-send", action="store_true", help="Build + save HTML only; don't email.")
    ap.add_argument("--min-relevance", type=int, default=0)
    args = ap.parse_args()

    if not brief.available():
        print("ANTHROPIC_API_KEY not set — cannot generate the briefing. Skipping.")
        return 0
    if not args.no_send and not mailer.configured():
        print("No email backend configured (set RESEND_API_KEY or SMTP_* + DIGEST_TO). "
              "Building HTML only.")

    if args.fetch:
        s = ingest.run_once()
        print("Fetched: %d new, %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    db.init_db()
    now = datetime.now(timezone.utc)
    articles = db.query_articles(limit=400, min_relevance=args.min_relevance)
    quotes, spreads = prices.get_quotes(), prices.get_spreads()

    payload = brief.generate(
        articles, quotes, spreads,
        equities=prices.get_quotes(prices.MARKET_MOVERS),
        eia=eia.get_inventories(),
        edition=args.edition,
    )
    print("%s briefing generated (%s)." % (payload["edition"], payload["model"]))

    upcoming = events.upcoming(now, limit=5)
    html_body = email_render.briefing_html(payload["text"], args.edition, quotes, spreads, upcoming, now)
    text_body = email_render.briefing_text(payload["text"], args.edition)

    # Save a copy to reports/ for the record (and easy local preview).
    reports = REPO_ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / ("briefing-%s-%s.html" % (now.strftime("%Y%m%d"), args.edition.lower()))
    out.write_text(html_body, encoding="utf-8")
    print("Saved: %s" % out)

    if args.no_send:
        return 0

    subject = "Sheerstock Park — %s Briefing, %s" % (args.edition, now.strftime("%d %b"))
    try:
        sent = mailer.send_html(subject, html_body, text_body)
    except Exception as exc:  # noqa: BLE001 — fail-soft so the cron stays green
        print("Email send failed: %s" % exc)
        return 0
    if sent:
        print("Emailed via %s to %s" % (mailer.backend(), ", ".join(mailer.recipients())))
    else:
        print("Email not sent (backend unconfigured).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

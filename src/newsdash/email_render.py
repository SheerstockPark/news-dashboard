"""Render the AI briefing into a branded, email-client-safe HTML document.

Email clients are fussy: no external CSS, no flexbox, inline styles only, tables for layout.
This converts the brief's Markdown (bold section headers + bullets) into styled HTML and
wraps it with a Sheerstock Park header, a live price tape and an upcoming-events footer.
"""

import html
import re
from datetime import datetime, timezone
from typing import Dict, List

BG = "#0b0f14"
CARD = "#121823"
BORDER = "#1e2733"
TEXT = "#e6edf3"
MUTED = "#7d8b9a"
ACCENT = "#ffa45c"
UP = "#16c784"
DOWN = "#ea3943"


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    return s


def md_to_html(md: str) -> str:
    """Convert the briefing Markdown to inline-styled HTML blocks (headers, bullets, paragraphs)."""
    parts: List[str] = []
    in_list = False

    def close():
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close()
            continue
        header = re.match(r"^\*\*(.+?)\*\*:?$", line.strip())
        if header:
            close()
            parts.append(
                '<div style="margin:18px 0 8px;font-size:15px;font-weight:800;color:%s;'
                'letter-spacing:.2px">%s</div>' % (ACCENT, _inline(header.group(1)))
            )
            continue
        if line.lstrip()[:2] in ("- ", "* "):
            if not in_list:
                parts.append('<ul style="margin:0 0 6px;padding-left:18px">')
                in_list = True
            parts.append(
                '<li style="margin:4px 0;color:%s;font-size:14px;line-height:1.5">%s</li>'
                % (TEXT, _inline(line.lstrip()[2:]))
            )
            continue
        close()
        parts.append(
            '<p style="margin:6px 0;color:%s;font-size:14px;line-height:1.55">%s</p>'
            % (TEXT, _inline(line))
        )
    close()
    return "\n".join(parts)


def _tape(quotes: List[Dict], spreads: List[Dict]) -> str:
    cells = ""
    for q in quotes:
        color = UP if q["dir"] == "up" else DOWN if q["dir"] == "down" else MUTED
        arrow = "&#9650;" if q["dir"] == "up" else "&#9660;" if q["dir"] == "down" else "&#9632;"
        cells += (
            '<td style="padding:8px 12px;border:1px solid %s;border-radius:8px;background:%s">'
            '<div style="color:%s;font-size:10px;text-transform:uppercase">%s</div>'
            '<div style="font-size:16px;font-weight:800;color:%s">%s</div>'
            '<div style="color:%s;font-size:12px;font-weight:700">%s %+.2f%%</div></td>'
            % (BORDER, CARD, MUTED, html.escape(q["label"]), TEXT, q["last"], color, arrow, q["pct"])
        )
    for s in spreads:
        cells += (
            '<td style="padding:8px 12px;border:1px solid %s;border-radius:8px;background:%s">'
            '<div style="color:%s;font-size:10px;text-transform:uppercase">%s</div>'
            '<div style="font-size:16px;font-weight:800;color:%s">%.2f</div>'
            '<div style="color:%s;font-size:12px">%s</div></td>'
            % (BORDER, CARD, MUTED, html.escape(s["label"]), TEXT, s["value"], MUTED, s.get("unit", ""))
        )
    return '<table cellspacing="6" style="border-collapse:separate;margin:6px 0 4px"><tr>%s</tr></table>' % cells


def _events_block(events: List[Dict], now: datetime) -> str:
    if not events:
        return ""
    rows = ""
    for e in events[:5]:
        when = e["when"].strftime("%a %d %b %H:%MZ")
        rows += (
            '<tr><td style="padding:4px 0;color:%s;font-size:13px">%s</td>'
            '<td style="padding:4px 0;color:%s;font-size:13px;text-align:right">%s</td></tr>'
            % (TEXT, html.escape(e["name"]), MUTED, when)
        )
    return (
        '<div style="margin-top:18px;padding-top:14px;border-top:1px solid %s">'
        '<div style="font-size:12px;font-weight:700;color:%s;text-transform:uppercase;'
        'margin-bottom:6px">Upcoming catalysts</div>'
        '<table width="100%%" cellspacing="0">%s</table></div>' % (BORDER, MUTED, rows)
    )


def briefing_html(brief_text: str, edition: str, quotes: List[Dict], spreads: List[Dict],
                  events: List[Dict] = None, now: datetime = None) -> str:
    now = now or datetime.now(timezone.utc)
    date_str = now.strftime("%A %d %B %Y")
    return """\
<!DOCTYPE html><html><body style="margin:0;background:{bg};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:680px;margin:0 auto;padding:24px;background:{bg};color:{text}">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div style="font-size:20px;font-weight:800;color:{text}">SHEERSTOCK&nbsp;PARK</div>
    <div style="color:{accent};font-size:12px;font-weight:700;text-transform:uppercase">{edition} Briefing</div>
  </div>
  <div style="color:{muted};font-size:13px;margin:2px 0 14px">{date}</div>
  {tape}
  <div style="margin-top:8px">{body}</div>
  {events}
  <div style="color:#5b6b7a;font-size:11px;margin-top:22px;padding-top:12px;border-top:1px solid {border}">
    Generated by the Sheerstock Park News Dashboard. Market reads are AI-assisted heuristics, not investment advice.
  </div>
</div></body></html>""".format(
        bg=BG, text=TEXT, accent=ACCENT, muted=MUTED, border=BORDER, edition=html.escape(edition),
        date=date_str, tape=_tape(quotes, spreads), body=md_to_html(brief_text),
        events=_events_block(events or [], now),
    )


def briefing_text(brief_text: str, edition: str) -> str:
    """Plain-text fallback: strip Markdown emphasis markers."""
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", brief_text)
    plain = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"\1", plain)
    return "SHEERSTOCK PARK — %s Briefing\n\n%s" % (edition, plain)

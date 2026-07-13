"""Render the AI briefing into a branded, email-client-safe HTML document.

Email clients are fussy: no external CSS, no flexbox (Gmail strips it), inline styles only,
tables for layout. This converts the brief's Markdown (bold section headers + bullets) into
styled HTML and wraps it with a Sheerstock Park header, a live price tape, the day's top
stories and an upcoming-events footer. The ⚡ Desk Take section is pulled out and rendered
as a hero card, and its text doubles as the hidden inbox-preview line.
"""

import html
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple

BG = "#0b0f14"
CARD = "#121823"
BORDER = "#1e2733"
TEXT = "#e6edf3"
MUTED = "#7d8b9a"
ACCENT = "#ffa45c"
BRAND = "#ff7a18"
UP = "#16c784"
DOWN = "#ea3943"

DASHBOARD_URL = "https://news-dashboard-sheerstockpark.streamlit.app"


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    return s


_HEADER_RE = re.compile(r"^\*\*(.+?)\*\*:?$")


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
        header = _HEADER_RE.match(line.strip())
        if header:
            close()
            parts.append(
                '<div style="margin:24px 0 10px;padding-bottom:7px;border-bottom:1px solid %s;'
                'font-size:15px;font-weight:800;color:%s;letter-spacing:.3px">%s</div>'
                % (BORDER, ACCENT, _inline(header.group(1)))
            )
            continue
        if line.lstrip()[:2] in ("- ", "* "):
            if not in_list:
                parts.append('<ul style="margin:0 0 6px;padding-left:18px">')
                in_list = True
            parts.append(
                '<li style="margin:5px 0;color:%s;font-size:14px;line-height:1.55">%s</li>'
                % (TEXT, _inline(line.lstrip()[2:]))
            )
            continue
        close()
        parts.append(
            '<p style="margin:6px 0;color:%s;font-size:14px;line-height:1.6">%s</p>'
            % (TEXT, _inline(line))
        )
    close()
    return "\n".join(parts)


def _split_desk_take(md: str) -> Tuple[str, str]:
    """Pull the ⚡ Desk Take section out of the brief so it can be rendered as a hero card.

    Returns (desk_take_body_md, remaining_md). If no Desk Take section exists (older prose),
    returns ("", md) and the brief renders exactly as before.
    """
    lines = md.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        h = _HEADER_RE.match(line.strip())
        if h and start is None and "desk take" in h.group(1).lower():
            start = i
            continue
        if h and start is not None:
            end = i
            break
    if start is None:
        return "", md
    end = end if end is not None else len(lines)
    body = "\n".join(lines[start + 1:end]).strip()
    rest = "\n".join(lines[:start] + lines[end:]).strip()
    return body, rest


def _md_plain(md: str) -> str:
    """Markdown → single-line plain text (for the hidden inbox-preview snippet)."""
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    plain = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"\1", plain)
    plain = re.sub(r"^\s*[-*]\s+", "", plain, flags=re.M)
    return re.sub(r"\s+", " ", plain).strip()


def _preheader(snippet: str) -> str:
    """Hidden preview text + padding so clients don't pull body text into the inbox preview."""
    if not snippet:
        return ""
    pad = "&nbsp;&zwnj;" * 90
    return (
        '<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;'
        'opacity:0;overflow:hidden;color:%s">%s%s</div>' % (BG, html.escape(snippet[:220]), pad)
    )


def _desk_take_card(body_md: str) -> str:
    if not body_md:
        return ""
    return (
        '<table width="100%%" cellspacing="0" cellpadding="0" style="margin:16px 0 4px"><tr>'
        '<td style="width:4px;background:%s;border-radius:3px"></td>'
        '<td style="padding:14px 16px;background:%s;border:1px solid %s;border-left:0;'
        'border-radius:0 10px 10px 0">'
        '<div style="font-size:12px;font-weight:800;color:%s;text-transform:uppercase;'
        'letter-spacing:.8px;margin-bottom:6px">&#9889; Desk Take</div>'
        '<div style="color:%s;font-size:15px;line-height:1.6;font-weight:500">%s</div>'
        '</td></tr></table>'
        % (BRAND, CARD, BORDER, ACCENT, TEXT,
           md_to_html(body_md).replace("font-size:14px", "font-size:15px"))
    )


def _header(edition_label: str, date_str: str) -> str:
    return (
        '<div style="height:3px;background:%s;border-radius:2px;margin-bottom:16px"></div>'
        '<table width="100%%" cellspacing="0" cellpadding="0"><tr>'
        '<td style="font-size:20px;font-weight:800;color:%s;letter-spacing:.5px">'
        'SHEERSTOCK&nbsp;PARK</td>'
        '<td align="right" style="color:%s;font-size:12px;font-weight:700;'
        'text-transform:uppercase;letter-spacing:.6px;vertical-align:middle">%s</td>'
        '</tr></table>'
        '<div style="color:%s;font-size:13px;margin:2px 0 14px">%s</div>'
        % (BRAND, TEXT, ACCENT, html.escape(edition_label), MUTED, date_str)
    )


def _tape(quotes: List[Dict], spreads: List[Dict]) -> str:
    """Price tape as rows of four cells so it stays readable on a phone."""
    cells = []
    for q in quotes:
        color = UP if q["dir"] == "up" else DOWN if q["dir"] == "down" else MUTED
        arrow = "&#9650;" if q["dir"] == "up" else "&#9660;" if q["dir"] == "down" else "&#9632;"
        cells.append(
            '<td width="25%%" style="padding:9px 10px;border:1px solid %s;border-radius:8px;background:%s">'
            '<div style="color:%s;font-size:10px;text-transform:uppercase;letter-spacing:.4px">%s</div>'
            '<div style="font-size:16px;font-weight:800;color:%s">%s</div>'
            '<div style="color:%s;font-size:12px;font-weight:700">%s %+.2f%%</div></td>'
            % (BORDER, CARD, MUTED, html.escape(q["label"]), TEXT, q["last"], color, arrow, q["pct"])
        )
    for s in spreads:
        cells.append(
            '<td width="25%%" style="padding:9px 10px;border:1px solid %s;border-radius:8px;background:%s">'
            '<div style="color:%s;font-size:10px;text-transform:uppercase;letter-spacing:.4px">%s</div>'
            '<div style="font-size:16px;font-weight:800;color:%s">%.2f</div>'
            '<div style="color:%s;font-size:12px">%s</div></td>'
            % (BORDER, CARD, MUTED, html.escape(s["label"]), TEXT, s["value"], MUTED, s.get("unit", ""))
        )
    rows = ""
    for i in range(0, len(cells), 4):
        chunk = cells[i:i + 4]
        chunk += ['<td width="25%"></td>'] * (4 - len(chunk))  # keep cell widths even
        rows += "<tr>%s</tr>" % "".join(chunk)
    return ('<table width="100%%" cellspacing="6" cellpadding="0" '
            'style="border-collapse:separate;margin:6px 0 4px">%s</table>' % rows)


def _events_block(events: List[Dict], now: datetime) -> str:
    if not events:
        return ""
    rows = ""
    for e in events[:5]:
        when = e["when"].strftime("%a %d %b %H:%MZ")
        rows += (
            '<tr><td style="padding:4px 0;color:%s;font-size:13px">%s</td>'
            '<td style="padding:4px 0;color:%s;font-size:13px;text-align:right;white-space:nowrap">%s</td></tr>'
            % (TEXT, html.escape(e["name"]), MUTED, when)
        )
    return (
        '<div style="margin-top:20px;padding-top:14px;border-top:1px solid %s">'
        '<div style="font-size:12px;font-weight:800;color:%s;text-transform:uppercase;'
        'letter-spacing:.6px;margin-bottom:6px">&#128197; Upcoming catalysts</div>'
        '<table width="100%%" cellspacing="0">%s</table></div>' % (BORDER, ACCENT, rows)
    )


def _ago(iso: str, now: datetime) -> str:
    """Relative freshness, e.g. '12m ago' / '3h ago' / '2d ago'."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    s = int((now - dt).total_seconds())
    if s < 120:
        return "just now"
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh ago" % (s // 3600)
    return "%dd ago" % (s // 86400)


def _sources_block(articles: List[Dict], now: datetime) -> str:
    """A deterministic, clickable list of the real top articles behind today's brief."""
    if not articles:
        return ""
    rows = ""
    for a in articles[:10]:
        imp = ""
        if a.get("impact") == "bullish":
            imp = ' &middot; <span style="color:%s;font-weight:700">▲ bullish</span>' % UP
        elif a.get("impact") == "bearish":
            imp = ' &middot; <span style="color:%s;font-weight:700">▼ bearish</span>' % DOWN
        ago = _ago(a.get("published_at") or a.get("fetched_at"), now)
        ago_chip = ' &middot; <span>%s</span>' % ago if ago else ""
        rows += (
            '<tr><td style="padding:9px 0;border-bottom:1px solid %s">'
            '<a href="%s" style="color:%s;text-decoration:none;font-weight:600;font-size:14px;line-height:1.4">%s</a>'
            '<div style="margin-top:3px;color:%s;font-size:12px">'
            '<span style="color:#9fb2c4;font-weight:600">%s</span>%s%s</div></td></tr>'
            % (BORDER, html.escape(a.get("url", "")), TEXT, html.escape(a["title"]),
               MUTED, html.escape(a.get("source_name", "")), ago_chip, imp)
        )
    return (
        '<div style="margin-top:20px;padding-top:14px;border-top:1px solid %s">'
        '<div style="font-size:12px;font-weight:800;color:%s;text-transform:uppercase;'
        'letter-spacing:.6px;margin-bottom:4px">📌 Today\'s top stories</div>'
        '<table width="100%%" cellspacing="0">%s</table></div>' % (BORDER, ACCENT, rows)
    )


def _footer() -> str:
    return (
        '<div style="color:#5b6b7a;font-size:11px;line-height:1.6;margin-top:22px;'
        'padding-top:12px;border-top:1px solid %s">'
        'Generated by the <a href="%s" style="color:#7d8b9a;text-decoration:underline">'
        'Sheerstock Park News Terminal</a>. Market reads are AI-assisted heuristics, '
        'not investment advice.<br>Created by Saavan Sumray-Roots.</div>' % (BORDER, DASHBOARD_URL)
    )


def edition_label(edition: str) -> str:
    e = (edition or "").strip().lower()
    if e == "weekly":
        return "Weekly Desk Review"
    return "%s Briefing" % (edition.strip().title() or "Desk")


def briefing_html(brief_text: str, edition: str, quotes: List[Dict], spreads: List[Dict],
                  events: List[Dict] = None, articles: List[Dict] = None,
                  now: datetime = None) -> str:
    now = now or datetime.now(timezone.utc)
    if (edition or "").strip().lower() == "weekly":
        date_str = "Week ending %s" % now.strftime("%d %B %Y")
    else:
        date_str = now.strftime("%A %d %B %Y")
    desk_take, rest = _split_desk_take(brief_text)
    preview = _md_plain(desk_take) or _md_plain(brief_text)
    return """\
<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
</head><body bgcolor="{bg}" style="margin:0;padding:0;background:{bg};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
{preheader}
<div style="max-width:680px;margin:0 auto;padding:20px 22px 26px;background:{bg};color:{text}">
  {header}
  {tape}
  {desk_take}
  <div style="margin-top:8px">{body}</div>
  {sources}
  {events}
  {footer}
</div></body></html>""".format(
        bg=BG, text=TEXT,
        preheader=_preheader(preview),
        header=_header(edition_label(edition), date_str),
        tape=_tape(quotes, spreads),
        desk_take=_desk_take_card(desk_take),
        body=md_to_html(rest),
        sources=_sources_block(articles or [], now),
        events=_events_block(events or [], now),
        footer=_footer(),
    )


def briefing_text(brief_text: str, edition: str) -> str:
    """Plain-text fallback: strip Markdown emphasis markers."""
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", brief_text)
    plain = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"\1", plain)
    return "SHEERSTOCK PARK — %s\n\n%s" % (edition_label(edition), plain)

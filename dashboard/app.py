#!/usr/bin/env python3
"""Oil-trading news terminal — Streamlit dashboard.

Reads normalized articles from the SQLite store and renders a fast, filterable,
auto-refreshing news feed tuned for an energy trading desk, with a live commodity
price tape and bullish/bearish crude-impact tagging.

Deploy-ready: ingest runs *in-process* on load (cached), so no background worker is
needed (works on Streamlit Community Cloud). Run locally with:
    streamlit run dashboard/app.py
"""

import html
import os
import sys
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from newsdash import config as cfg  # noqa: E402
from newsdash import db, ingest, prices  # noqa: E402

st.set_page_config(page_title="Oil Desk — News Terminal", page_icon="🛢️", layout="wide")

# ---------------------------------------------------------------- styling
CSS = """
<style>
:root { --bg:#0b0f14; --panel:#121821; --line:#1e2733; --txt:#e6edf3; --mut:#7d8b9a;
        --accent:#ff7a18; --hot:#ff3b30; --bull:#16c784; --bear:#ea3943; }
.stApp { background: radial-gradient(1200px 600px at 80% -10%, #14202c 0%, var(--bg) 55%); color: var(--txt); }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.0rem; padding-bottom: 2rem; max-width: 1500px; }
.term-title { font-size: 1.9rem; font-weight: 800; letter-spacing:-.5px; margin:0; }
.term-title .bar { color: var(--accent); }
.term-sub { color: var(--mut); font-size:.85rem; margin-top:-2px; }

/* price tape */
.tape { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 4px; }
.tick { background: var(--panel); border:1px solid var(--line); border-radius:10px;
        padding:8px 14px; min-width:118px; }
.tick .l { color:var(--mut); font-size:.66rem; text-transform:uppercase; letter-spacing:.7px; }
.tick .p { font-size:1.18rem; font-weight:800; line-height:1.1; }
.tick .c { font-size:.74rem; font-weight:700; }
.up   { color: var(--bull); } .down { color: var(--bear); } .flat { color: var(--mut); }

.kpi { background: var(--panel); border:1px solid var(--line); border-radius:14px; padding:12px 16px; }
.kpi .v { font-size:1.5rem; font-weight:800; }
.kpi .l { color:var(--mut); font-size:.70rem; text-transform:uppercase; letter-spacing:.8px; }

.card { background: var(--panel); border:1px solid var(--line); border-left:4px solid var(--line);
        border-radius:12px; padding:13px 16px; margin-bottom:10px; transition:.12s; }
.card:hover { border-color:#2c3a49; transform:translateY(-1px); }
.card.hot { border-left-color: var(--hot); }
.card.warm { border-left-color: var(--accent); }
.card a { color: var(--txt); text-decoration:none; font-weight:650; font-size:1.02rem; line-height:1.3; }
.card a:hover { color: var(--accent); }
.meta { color:var(--mut); font-size:.76rem; margin-top:6px; display:flex; gap:9px; flex-wrap:wrap; align-items:center;}
.src { color:#9fb2c4; font-weight:600; }
.chip { background:#1b2530; border:1px solid var(--line); color:#9fb2c4; border-radius:20px; padding:1px 9px; font-size:.68rem; }
.score { font-weight:800; border-radius:6px; padding:1px 8px; font-size:.72rem; }
.s-hot { background:rgba(255,59,48,.15); color:#ff6b62; }
.s-warm{ background:rgba(255,122,24,.15); color:#ffa45c; }
.s-mild{ background:rgba(125,139,154,.15); color:#9fb2c4; }
.imp { font-weight:800; border-radius:6px; padding:1px 8px; font-size:.72rem; }
.imp-bull { background:rgba(22,199,132,.16); color:#27d397; }
.imp-bear { background:rgba(234,57,67,.16); color:#ff5b66; }
.summary { color:#9aa7b4; font-size:.86rem; margin-top:6px; line-height:1.4; }
hr { border-color: var(--line); margin:.6rem 0 1rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- data (cached)
@st.cache_data(ttl=90, show_spinner=False)
def auto_ingest(_bucket: int):
    """Run ingest in-process at most once per TTL (shared across sessions)."""
    return ingest.run_once()


@st.cache_data(ttl=60, show_spinner=False)
def load_prices():
    return prices.get_quotes()


@st.cache_data(ttl=8, show_spinner=False)
def load_articles(sources, categories, min_rel, impact_filter, search, limit):
    rows = db.query_articles(
        limit=limit, sources=sources or None, categories=categories or None,
        min_relevance=min_rel, search=search or None,
    )
    if impact_filter in ("bullish", "bearish"):
        rows = [r for r in rows if r.get("impact") == impact_filter]
    return rows


@st.cache_data(ttl=8, show_spinner=False)
def load_stats():
    return db.stats()


# ---------------------------------------------------------------- helpers
def humanize(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh ago" % (s // 3600)
    return "%dd ago" % (s // 86400)


def score_class(r: int) -> str:
    return "hot" if r >= 70 else "warm" if r >= 40 else "mild"


# ---------------------------------------------------------------- sidebar
all_sources = cfg.load_config()["sources"]
src_label = {s["id"]: s["name"] for s in all_sources}
categories_all = sorted({s["category"] for s in all_sources})

with st.sidebar:
    st.markdown("### ⚙️ Controls")
    auto = st.toggle("Auto-refresh page", value=True)
    interval = st.select_slider("Refresh every (s)", options=[15, 30, 60, 120], value=30)
    live_ingest = st.toggle("Live ingest (auto-fetch feeds)", value=True,
                            help="Pulls fresh headlines in the background, at most once every 90s.")
    if st.button("⟳ Fetch latest now", use_container_width=True):
        with st.spinner("Fetching feeds…"):
            s = ingest.run_once()
        st.cache_data.clear()
        st.success("%d new article(s), %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    st.divider()
    f_min_rel = st.slider("Min oil-relevance", 0, 100, 0, 5,
                          help="0 = all news. Raise to focus on crude-moving stories.")
    f_impact = st.radio("Crude impact", ["all", "bullish", "bearish"], horizontal=True)
    f_cats = st.multiselect("Categories", categories_all, default=[])
    f_src = st.multiselect("Sources", [s["id"] for s in all_sources],
                           default=[], format_func=lambda i: src_label.get(i, i))
    f_search = st.text_input("Search", placeholder="e.g. Hormuz, OPEC, diesel")
    f_limit = st.slider("Max headlines", 20, 400, 120, 20)

# In-process ingest on load (cached; bucketed so it fires ~once per 90s window).
if live_ingest:
    try:
        from time import time as _t
        auto_ingest(int(_t()) // 90)
    except Exception:
        pass  # never let ingest failure blank the page

if auto:
    st.markdown('<meta http-equiv="refresh" content="%d">' % interval, unsafe_allow_html=True)

# ---------------------------------------------------------------- header
stats = load_stats()
quotes = load_prices()
articles = load_articles(f_src, f_cats, f_min_rel, f_impact, f_search.strip(), f_limit)
hot = [a for a in articles if a["relevance"] >= 70]

st.markdown('<p class="term-title">🛢️ OIL DESK <span class="bar">/</span> NEWS TERMINAL</p>',
            unsafe_allow_html=True)
st.markdown('<p class="term-sub">Real-time multi-source aggregation · %d sources · updated %s</p>'
            % (len(all_sources), humanize(stats["latest_fetch"])), unsafe_allow_html=True)

# price tape
if quotes:
    ticks = []
    for q in quotes:
        arrow = "▲" if q["dir"] == "up" else "▼" if q["dir"] == "down" else "■"
        unit = (" <span style='color:#5b6b7a'>%s</span>" % q["unit"]) if q["unit"] else ""
        ticks.append(
            '<div class="tick"><div class="l">%s</div>'
            '<div class="p">%s%s</div>'
            '<div class="c %s">%s %+.2f (%+.2f%%)</div></div>'
            % (html.escape(q["label"]), q["last"], unit, q["dir"], arrow, q["change"], q["pct"])
        )
    st.markdown('<div class="tape">%s</div>' % "".join(ticks), unsafe_allow_html=True)

# KPI strip
k1, k2, k3, k4 = st.columns(4)
bull_n = sum(1 for a in articles if a.get("impact") == "bullish")
bear_n = sum(1 for a in articles if a.get("impact") == "bearish")
for col, label, val in (
    (k1, "Articles stored", stats["total"]),
    (k2, "Showing", len(articles)),
    (k3, "Bullish / Bearish", "%d / %d" % (bull_n, bear_n)),
    (k4, "High-relevance", len(hot)),
):
    col.markdown('<div class="kpi"><div class="v">%s</div><div class="l">%s</div></div>'
                 % (val, label), unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ---------------------------------------------------------------- feed
if not articles:
    st.info("No articles match these filters. Lower the relevance threshold, clear filters, "
            "or click **⟳ Fetch latest now** in the sidebar.")
else:
    for a in articles:
        cls = score_class(a["relevance"])
        sc = {"hot": "s-hot", "warm": "s-warm", "mild": "s-mild"}[cls]
        imp_html = ""
        if a.get("impact") == "bullish":
            imp_html = '<span class="imp imp-bull">▲ BULLISH %+d</span>' % a.get("impact_score", 0)
        elif a.get("impact") == "bearish":
            imp_html = '<span class="imp imp-bear">▼ BEARISH %d</span>' % a.get("impact_score", 0)
        chips = "".join('<span class="chip">%s</span>' % html.escape(t) for t in a["tags"][:5])
        summary = ('<div class="summary">%s</div>' % html.escape(a["summary"])) if a["summary"] else ""
        st.markdown(
            """
            <div class="card %s">
              <a href="%s" target="_blank">%s</a>
              %s
              <div class="meta">
                <span class="src">%s</span>
                <span class="chip">%s</span>
                <span>%s</span>
                <span class="score %s">⚡ %d</span>
                %s
                %s
              </div>
            </div>
            """ % (
                cls, html.escape(a["url"]), html.escape(a["title"]), summary,
                html.escape(a["source_name"]), html.escape(a["category"]),
                humanize(a.get("published_at") or a.get("fetched_at")),
                sc, a["relevance"], imp_html, chips,
            ),
            unsafe_allow_html=True,
        )

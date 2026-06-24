#!/usr/bin/env python3
"""Sheerstock Park — Oil Desk News Terminal (Streamlit).

A living, multi-tab terminal over the SQLite news store:
  • Feed     — ranked, filterable headlines with oil-relevance + crude-impact tags
  • Pulse    — analytics across all articles (volume, sentiment flow, sources, topics)
  • Voices   — key-people tracker (Trump via Truth Social; others via news mentions)
  • Markets  — live commodity tape + top bullish/bearish movers

Deploy-ready: ingest runs in-process on load (cached), so no background worker is needed.
Run locally:  streamlit run dashboard/app.py
"""

import base64
import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(_HERE, "assets")
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

# Bridge Streamlit Cloud secrets -> environment so the env-based config (Turso, API keys)
# works identically in the cloud and locally (where .env is used instead).
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from newsdash import config as cfg  # noqa: E402
from newsdash import ask as askmod  # noqa: E402
from newsdash import brief as briefmod  # noqa: E402
from newsdash import db, eia, events, ingest, prices  # noqa: E402

st.set_page_config(page_title="Sheerstock Park — Oil Desk Terminal", page_icon="🛢️", layout="wide")

BULL, BEAR, MUT, ACCENT = "#16c784", "#ea3943", "#7d8b9a", "#ff7a18"


def asset_data_uri(filename, mime):
    try:
        with open(os.path.join(ASSETS, filename), "rb") as fh:
            return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))
    except OSError:
        return ""


# ---------------------------------------------------------------- styling
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root { --bg:#0b0f14; --panel:#121821; --line:#1e2733; --txt:#e6edf3; --mut:#7d8b9a;
        --accent:#ff7a18; --hot:#ff3b30; --bull:#16c784; --bear:#ea3943; }
html, body, [class*="css"], .stApp, .stMarkdown { font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif; }
.stApp { background: radial-gradient(1200px 600px at 80% -10%, #14202c 0%, var(--bg) 55%); color: var(--txt); scroll-behavior:smooth; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.0rem; padding-bottom: 2rem; max-width: 1500px; }
::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:#26313d; border-radius:6px; border:2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background:#33414f; }
.num { font-variant-numeric:tabular-nums; font-feature-settings:'tnum'; }
@keyframes fadein { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }

/* cover hero */
.cover { position:relative; height:158px; border-radius:16px; overflow:hidden; margin:0 0 12px;
         border:1px solid var(--line); box-shadow:0 8px 30px rgba(0,0,0,.35); }
.cover .bg { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.cover .veil { position:absolute; inset:0;
               background:linear-gradient(95deg, rgba(7,11,16,.94) 0%, rgba(7,11,16,.7) 45%,
                                          rgba(7,11,16,.32) 75%, rgba(255,122,24,.10) 100%); }
.cover .content { position:relative; z-index:2; height:100%; display:flex; align-items:center;
                  justify-content:space-between; padding:0 24px; gap:14px; }
.brand-name { font-size:1.55rem; font-weight:800; letter-spacing:2px; color:#f6f9fc; line-height:1.05;
              text-shadow:0 2px 10px rgba(0,0,0,.6); }
.brand-desk { color:#c5d2df; font-size:.78rem; letter-spacing:2.5px; text-transform:uppercase; margin-top:3px; }
.brand-meta { color:#c5d2df; font-size:.78rem; text-align:right; white-space:nowrap;
              background:rgba(7,11,16,.45); border:1px solid var(--line); border-radius:20px; padding:5px 12px; }
.live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--bull);
            margin-right:6px; box-shadow:0 0 0 0 rgba(22,199,132,.6); animation:pulse 2s infinite; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(22,199,132,.5)} 70%{box-shadow:0 0 0 7px rgba(22,199,132,0)} 100%{box-shadow:0 0 0 0 rgba(22,199,132,0)} }
@media (max-width:760px){ .brand-desk{display:none} .cover{height:120px} }

/* price tape */
.tape { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 4px; padding:8px;
        position:sticky; top:0; z-index:50; border-radius:14px;
        background:rgba(11,15,20,.82); backdrop-filter:blur(10px); border:1px solid rgba(30,39,51,.6); }
.tick { background: var(--panel); border:1px solid var(--line); border-radius:11px; padding:8px 13px;
        min-width:132px; display:flex; flex-direction:column; gap:2px; transition:.14s; }
.tick:hover { border-color:#2c3a49; transform:translateY(-2px); }
.tick .top { display:flex; align-items:baseline; justify-content:space-between; gap:8px; }
.tick .l { color:var(--mut); font-size:.64rem; text-transform:uppercase; letter-spacing:.8px; font-weight:600; }
.tick .p { font-size:1.16rem; font-weight:800; line-height:1.1; }
.tick .spark { margin:2px 0 1px; height:18px; }
.tick .c { font-size:.72rem; font-weight:700; }
.up { color: var(--bull); } .down { color: var(--bear); } .flat { color: var(--mut); }

/* market-tone bar */
.tone { display:flex; align-items:center; gap:10px; margin:2px 0 8px; }
.tone .bar { flex:1; height:7px; border-radius:6px; overflow:hidden; display:flex; background:#1b2530; }
.tone .bar i { display:block; height:100%; }
.tone .lab { font-size:.7rem; color:var(--mut); white-space:nowrap; letter-spacing:.4px; }

/* favicons */
.fav { width:14px; height:14px; border-radius:3px; vertical-align:-2px; margin-right:5px; opacity:.9; }

/* events calendar */
.evts { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.evt { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:7px 13px; min-width:120px; }
.evt-n { font-size:.76rem; color:#cbd5e1; font-weight:600; }
.evt-c { font-size:.72rem; color:var(--accent); font-weight:700; margin-top:2px; }

/* featured hero story */
.hero { position:relative; background:linear-gradient(120deg,#15202b 0%, var(--panel) 70%);
        border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:14px;
        padding:18px 20px; margin-bottom:14px; animation:fadein .25s ease both; }
.hero .tagline { font-size:.66rem; text-transform:uppercase; letter-spacing:1.6px; color:var(--accent); font-weight:700; margin-bottom:6px; }
.hero a { color:#f4f8fc; text-decoration:none; font-size:1.32rem; font-weight:800; line-height:1.25; }
.hero a:hover { color:var(--accent); }
.hero .summary { color:#aebccd; font-size:.92rem; margin-top:8px; line-height:1.45; }

.kpi { background: var(--panel); border:1px solid var(--line); border-radius:14px; padding:12px 16px; }
.kpi .v { font-size:1.5rem; font-weight:800; }
.kpi .l { color:var(--mut); font-size:.70rem; text-transform:uppercase; letter-spacing:.8px; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap:4px; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab"] { background:transparent; border-radius:9px 9px 0 0; padding:7px 16px;
                               color:var(--mut); font-weight:650; }
.stTabs [aria-selected="true"] { background:var(--panel); color:var(--txt) !important;
                                 border:1px solid var(--line); border-bottom:2px solid var(--accent); }

/* article cards */
.card { background: var(--panel); border:1px solid var(--line); border-left:4px solid var(--line);
        border-radius:12px; padding:13px 16px; margin-bottom:10px; transition:.14s; animation:fadein .2s ease both; }
.card:hover { border-color:#33414f; transform:translateY(-1px); box-shadow:0 6px 18px rgba(0,0,0,.25); }
.card.hot { border-left-color: var(--hot); }
.card.warm { border-left-color: var(--accent); }
.card a { color: var(--txt); text-decoration:none; font-weight:650; font-size:1.02rem; line-height:1.3; }
.card a:hover { color: var(--accent); }
.meta { color:var(--mut); font-size:.76rem; margin-top:6px; display:flex; gap:9px; flex-wrap:wrap; align-items:center;}
.src { color:#9fb2c4; font-weight:600; }
.chip { background:#1b2530; border:1px solid var(--line); color:#9fb2c4; border-radius:20px; padding:1px 9px; font-size:.68rem; }
.chip.dupe { background:rgba(74,158,255,.12); border-color:rgba(74,158,255,.3); color:#7db4ff; cursor:help; }
.score { font-weight:800; border-radius:6px; padding:1px 8px; font-size:.72rem; }
.s-hot { background:rgba(255,59,48,.15); color:#ff6b62; }
.s-warm{ background:rgba(255,122,24,.15); color:#ffa45c; }
.s-mild{ background:rgba(125,139,154,.15); color:#9fb2c4; }
.imp { font-weight:800; border-radius:6px; padding:1px 8px; font-size:.72rem; }
.imp-bull { background:rgba(22,199,132,.16); color:#27d397; }
.imp-bear { background:rgba(234,57,67,.16); color:#ff5b66; }
.summary { color:#9aa7b4; font-size:.86rem; margin-top:6px; line-height:1.4; }

/* section + voices */
.sec { font-size:.78rem; text-transform:uppercase; letter-spacing:1.4px; color:var(--mut);
       margin:6px 0 8px; font-weight:700; }
.voice { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:14px; height:100%; }
.voice .hd { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.voice .nm { font-size:1.05rem; font-weight:800; }
.voice .ct { color:var(--mut); font-size:.74rem; }
.voice .net { font-weight:800; border-radius:20px; padding:2px 10px; font-size:.72rem; }
.voice ul { margin:6px 0 0; padding-left:0; list-style:none; }
.voice li { padding:5px 0; border-top:1px solid var(--line); font-size:.84rem; line-height:1.3; }
.voice li a { color:#d7e1ec; text-decoration:none; } .voice li a:hover { color:var(--accent); }
.voice .pos { color:var(--bull); } .voice .neg { color:var(--bear); }
.ts { background:rgba(255,122,24,.07); border:1px solid rgba(255,122,24,.25); border-radius:10px;
      padding:9px 12px; margin-bottom:8px; }
.ts a { color:#f0d7bd; text-decoration:none; font-weight:600; } .ts a:hover { color:var(--accent); }
.ts .t { color:#9a7b5c; font-size:.68rem; }
hr { border-color: var(--line); margin:.6rem 0 1rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- data (cached)
@st.cache_data(ttl=90, show_spinner=False)
def auto_ingest(_bucket):
    return ingest.run_once()


@st.cache_data(ttl=60, show_spinner=False)
def load_prices():
    return prices.get_quotes()


@st.cache_data(ttl=300, show_spinner=False)
def load_history(symbols):
    return prices.get_history(list(symbols))


@st.cache_data(ttl=120, show_spinner=False)
def load_equities():
    return prices.get_quotes(prices.EQUITIES)


@st.cache_data(ttl=120, show_spinner=False)
def load_spreads():
    return prices.get_spreads()


@st.cache_data(ttl=1800, show_spinner=False)
def load_eia():
    return eia.get_inventories()


@st.cache_data(ttl=900, show_spinner=False)
def load_history_long(symbols, period):
    return prices.get_history(list(symbols), period=period, interval="1d")


@st.cache_data(ttl=20, show_spinner=False)
def load_corpus(_bucket):
    """All articles as a DataFrame with a parsed UTC timestamp column `ts`."""
    rows = db.query_articles(limit=8000, min_relevance=0)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["published_at"].fillna(df["fetched_at"]), utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    return df


@st.cache_data(ttl=10, show_spinner=False)
def load_stats():
    return db.stats()


@st.cache_data(ttl=300, show_spinner=False)
def load_voices_cfg():
    return cfg.load_voices()


# ---------------------------------------------------------------- helpers
def humanize(iso):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
    except ValueError:
        return str(iso)
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


def score_class(r):
    return "hot" if r >= 70 else "warm" if r >= 40 else "mild"


def favicon(url):
    """Google favicon service URL for an article's source domain, or '' if no host."""
    try:
        host = re.sub(r"^https?://", "", url or "").split("/")[0]
    except Exception:
        host = ""
    return ("https://www.google.com/s2/favicons?sz=32&domain=%s" % host) if host else ""


def sparkline(values, color, w=124, h=18):
    """Inline SVG area+line sparkline for an intraday series. '' if too few points."""
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    n = len(pts)
    coords = " ".join(
        "%.1f,%.1f" % (i * (w - 2) / (n - 1) + 1, h - 1 - (v - lo) / span * (h - 2))
        for i, v in enumerate(pts)
    )
    gid = "g%d" % (abs(hash((color, n))) % 100000)
    return (
        '<svg class="spark" width="%d" height="%d" viewBox="0 0 %d %d" preserveAspectRatio="none">'
        '<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%s" stop-opacity=".30"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient></defs>'
        '<polygon points="1,%d %s %.1f,%d" fill="url(#%s)"/>'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/></svg>'
        % (w, h, w, h, gid, color, color, h, coords, float(w - 1), h, gid, coords, color)
    )


def resolve_sentiment(a, use_llm):
    """Overlay the LLM verdict onto an article dict when present and enabled."""
    if use_llm and a.get("llm_impact"):
        a["impact"] = a["llm_impact"]
        a["impact_score"] = a.get("llm_impact_score") or 0
        a["rationale"] = a.get("llm_rationale") or ""
        a["ai"] = True
    return a


def _hours_since(iso, now):
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return 999.0


def rank_score(a, now):
    """Blend oil-relevance, crude-impact magnitude, and recency into one feed score."""
    rel = a.get("relevance", 0)
    imp = abs(a.get("impact_score", 0))
    hrs = _hours_since(a.get("published_at") or a.get("fetched_at"), now)
    recency = 38.0 * (0.90 ** hrs)  # ~halves every 7h, near-zero after a day
    return rel + 0.35 * imp + recency


_STOP = {"the", "a", "an", "to", "of", "in", "on", "as", "is", "are", "for", "and", "at",
         "by", "with", "from", "after", "amid", "over", "says", "say", "new", "us", "u"}


def cluster_key(title):
    """Signature for collapsing the same story carried by multiple wires."""
    words = [w for w in re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).split() if w not in _STOP]
    return " ".join(words[:5]) if len(words) >= 4 else "\x00" + (title or "")  # short titles stay unique


def cluster_articles(sorted_articles):
    """Collapse near-duplicate stories. Input must be pre-sorted (best first).

    Returns list of (primary_article, [other_source_names]) preserving order.
    """
    groups, order = {}, []
    for a in sorted_articles:
        k = cluster_key(a["title"])
        if k in groups:
            groups[k][1].append(a["source_name"])
        else:
            groups[k] = (a, [])
            order.append(k)
    return [groups[k] for k in order]


def article_card(a, also_in=None):
    cls = score_class(a["relevance"])
    sc = {"hot": "s-hot", "warm": "s-warm", "mild": "s-mild"}[cls]
    ai = "🤖 " if a.get("ai") else ""
    tip = (' title="%s"' % html.escape(a["rationale"])) if a.get("rationale") else ""
    imp = ""
    if a.get("impact") == "bullish":
        imp = '<span class="imp imp-bull"%s>%s▲ BULLISH %+d</span>' % (tip, ai, a.get("impact_score", 0))
    elif a.get("impact") == "bearish":
        imp = '<span class="imp imp-bear"%s>%s▼ BEARISH %d</span>' % (tip, ai, a.get("impact_score", 0))
    tags = a.get("tags") or []
    chips = "".join('<span class="chip">%s</span>' % html.escape(t) for t in tags[:4])
    # extra wires carrying the same story
    dupe = ""
    if also_in:
        uniq = list(dict.fromkeys(s for s in also_in if s != a["source_name"]))
        if uniq:
            tip = html.escape(", ".join(uniq[:8]))
            dupe = '<span class="chip dupe" title="%s">＋%d more</span>' % (tip, len(uniq))
    summary = ('<div class="summary">%s</div>' % html.escape(a["summary"])) if a.get("summary") else ""
    fav = favicon(a.get("url", ""))
    favimg = ('<img class="fav" src="%s" loading="lazy" onerror="this.style.display=\'none\'">' % fav) if fav else ""
    return """
        <div class="card %s">
          <a href="%s" target="_blank">%s</a>
          %s
          <div class="meta">
            <span class="src">%s%s</span>%s<span class="chip">%s</span><span>%s</span>
            <span class="score %s num">%d</span>%s%s
          </div>
        </div>""" % (
        cls, html.escape(a.get("url", "")), html.escape(a["title"]), summary,
        favimg, html.escape(a["source_name"]), dupe, html.escape(a["category"]),
        humanize(a.get("published_at") or a.get("fetched_at")), sc, a["relevance"], imp, chips,
    )


def hero_card(a, also_in=None):
    fav = favicon(a.get("url", ""))
    favimg = ('<img class="fav" src="%s" loading="lazy" onerror="this.style.display=\'none\'">' % fav) if fav else ""
    imp = ""
    if a.get("impact") == "bullish":
        imp = '<span class="imp imp-bull">▲ BULLISH %+d</span>' % a.get("impact_score", 0)
    elif a.get("impact") == "bearish":
        imp = '<span class="imp imp-bear">▼ BEARISH %d</span>' % a.get("impact_score", 0)
    dupe = ""
    if also_in:
        uniq = list(dict.fromkeys(s for s in also_in if s != a["source_name"]))
        if uniq:
            dupe = '<span class="chip dupe" title="%s">＋%d more</span>' % (html.escape(", ".join(uniq[:8])), len(uniq))
    summary = ('<div class="summary">%s</div>' % html.escape(a["summary"])) if a.get("summary") else ""
    return """
        <div class="hero">
          <div class="tagline">★ Top story</div>
          <a href="%s" target="_blank">%s</a>
          %s
          <div class="meta" style="margin-top:10px">
            <span class="src">%s%s</span>%s<span class="chip">%s</span><span>%s</span>
            <span class="score %s num">%d</span>%s
          </div>
        </div>""" % (
        html.escape(a.get("url", "")), html.escape(a["title"]), summary,
        favimg, html.escape(a["source_name"]), dupe, html.escape(a["category"]),
        humanize(a.get("published_at") or a.get("fetched_at")),
        score_class(a["relevance"]).replace("hot", "s-hot").replace("warm", "s-warm").replace("mild", "s-mild"),
        a["relevance"], imp,
    )


def style_chart(ch, h=200):
    return (
        ch.properties(height=h, background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#9aa7b4", titleColor="#9aa7b4", gridColor="#16202b",
                        domainColor="#1e2733", labelFontSize=11, titleFontSize=11)
        .configure_legend(labelColor="#9aa7b4", titleColor="#9aa7b4")
    )


# ---------------------------------------------------------------- sidebar
all_sources = cfg.load_config()["sources"]
src_label = {s["id"]: s["name"] for s in all_sources}
categories_all = sorted({s["category"] for s in all_sources})

with st.sidebar:
    st.markdown("### ⚙️ Controls")
    auto = st.toggle("Auto-refresh page", value=True)
    interval = st.select_slider("Refresh every (s)", options=[15, 30, 60, 120], value=30)
    live_ingest = st.toggle("Live ingest (auto-fetch)", value=True,
                            help="Pulls fresh headlines in-process, at most once every 90s.")
    use_llm = st.toggle("AI sentiment (when scored)", value=True,
                        help="Use Claude's crude-impact verdict where available; "
                             "falls back to the keyword tagger. Run tools/enrich_sentiment.py to score.")
    compact = st.toggle("Compact view", value=False, help="Denser cards, hide summaries.")
    if st.button("⟳ Fetch latest now", use_container_width=True):
        with st.spinner("Fetching feeds…"):
            s = ingest.run_once()
        st.cache_data.clear()
        st.success("%d new article(s), %d/%d sources ok" % (s["new"], s["ok"], s["sources"]))

    st.divider()
    st.caption("Feed filters")
    f_sort = st.radio("Sort by", ["Smart", "Newest", "Most relevant"], horizontal=False,
                      help="Smart blends oil-relevance, crude impact and recency.")
    f_min_rel = st.slider("Min oil-relevance", 0, 100, 10, 5,
                          help="Default 10 hides non-oil noise. Set 0 to see everything.")
    f_impact = st.radio("Crude impact", ["all", "bullish", "bearish"], horizontal=True)
    f_cats = st.multiselect("Categories", categories_all, default=[])
    f_src = st.multiselect("Sources", [s["id"] for s in all_sources],
                           default=[], format_func=lambda i: src_label.get(i, i))
    f_search = st.text_input("Search", placeholder="e.g. Hormuz, OPEC, diesel")
    f_limit = st.slider("Max headlines", 20, 400, 120, 20)

if compact:
    st.markdown("<style>.card{padding:8px 14px;margin-bottom:6px} .card a{font-size:.95rem}"
                " .summary{display:none} .hero{padding:12px 16px} .hero a{font-size:1.1rem}</style>",
                unsafe_allow_html=True)


# --- live region: a fragment that reruns in-session (preserves active tab + scroll) ---
def terminal():
    # In-process ingest on load — LOCAL ONLY. In the cloud (Turso) the GitHub Actions cron
    # keeps the DB fresh, so the app stays read-only and renders instantly instead of
    # blocking for minutes while it fetches 50 feeds over the network.
    if live_ingest and not db.using_turso():
        try:
            from time import time as _t
            auto_ingest(int(_t()) // 90)
        except Exception:
            pass

    # ---------------------------------------------------------------- header + tape
    stats = load_stats()
    quotes = load_prices()
    corpus = load_corpus(int(__import__("time").time()) // 20)
    if use_llm and not corpus.empty and "llm_impact" in corpus.columns:
        corpus = corpus.copy()
        has = corpus["llm_impact"].notna() & (corpus["llm_impact"] != "")
        llm_sc = pd.to_numeric(corpus["llm_impact_score"], errors="coerce").fillna(0)
        corpus["impact"] = corpus["impact"].where(~has, corpus["llm_impact"])
        corpus["impact_score"] = (pd.to_numeric(corpus["impact_score"], errors="coerce").fillna(0)
                                  .where(~has, llm_sc).astype(int))

    _banner = asset_data_uri("banner.jpg", "image/jpeg")
    _bg = ('<img class="bg" src="%s">' % _banner) if _banner else ""
    st.markdown(
        """
        <div class="cover">
          %s<div class="veil"></div>
          <div class="content">
            <div class="brand"><div class="brand-txt">
              <span class="brand-name">SHEERSTOCK&nbsp;PARK</span>
              <span class="brand-desk">Oil Desk · News Terminal</span>
            </div></div>
            <div class="brand-meta"><span class="live-dot"></span><b>LIVE</b> · %d sources · updated %s</div>
          </div>
        </div>""" % (_bg, len(all_sources), humanize(stats["latest_fetch"])),
        unsafe_allow_html=True,
    )

    if quotes:
        hist = load_history(tuple(q["symbol"] for q in quotes))
        ticks = ""
        for q in quotes:
            arrow = "▲" if q["dir"] == "up" else "▼" if q["dir"] == "down" else "■"
            unit = (" <span style='color:#5b6b7a;font-size:.7rem'>%s</span>" % q["unit"]) if q["unit"] else ""
            col = BULL if q["dir"] == "up" else BEAR if q["dir"] == "down" else MUT
            spark = sparkline([c for _, c in hist.get(q["symbol"], [])], col)
            ticks += (
                '<div class="tick">'
                '<div class="top"><span class="l">%s</span><span class="c %s num">%s %+.2f%%</span></div>'
                '<div class="p num">%s%s</div>%s'
                '<div class="c %s num">%+.2f</div></div>'
                % (html.escape(q["label"]), q["dir"], arrow, q["pct"],
                   q["last"], unit, spark, q["dir"], q["change"])
            )
        st.markdown('<div class="tape">%s</div>' % ticks, unsafe_allow_html=True)

    # market-tone bar (crude sentiment balance over the last 24h)
    if not corpus.empty:
        _recent = corpus[corpus["ts"] >= (datetime.now(timezone.utc) - timedelta(hours=24))]
        _nb = int((_recent["impact"] == "bullish").sum())
        _ng = int((_recent["impact"] == "bearish").sum())
        if _nb + _ng > 0:
            bp = 100.0 * _nb / (_nb + _ng)
            tone = "bullish" if bp >= 55 else "bearish" if bp <= 45 else "balanced"
            tcol = BULL if bp >= 55 else BEAR if bp <= 45 else MUT
            st.markdown(
                '<div class="tone"><span class="lab">Crude tone · 24h</span>'
                '<div class="bar"><i style="width:%.0f%%;background:%s"></i>'
                '<i style="width:%.0f%%;background:%s"></i></div>'
                '<span class="lab" style="color:%s;font-weight:700">%d%% %s</span></div>'
                % (bp, BULL, 100 - bp, BEAR, tcol, round(bp), tone.upper()),
                unsafe_allow_html=True,
            )

    # ---------------------------------------------------------------- tabs
    tab_brief, tab_feed, tab_pulse, tab_voices, tab_markets = st.tabs(
        ["📋  Brief", "📰  Feed", "📊  Pulse", "🗣️  Voices", "🛢️  Markets"]
    )

    # ============================================================ BRIEF
    with tab_brief:
        b = briefmod.load()
        left, right = st.columns([4, 1])
        with right:
            if briefmod.available():
                if st.button("✨ Generate", use_container_width=True):
                    with st.spinner("Writing the desk brief…"):
                        arts = db.query_articles(limit=40, min_relevance=20)
                        briefmod.generate(arts, load_prices(), load_spreads())
                    st.cache_data.clear()
                    b = briefmod.load()
            else:
                st.caption("Add ANTHROPIC_API_KEY to .env to enable.")
        with left:
            if b.get("text"):
                st.markdown('<div class="sec">AI Morning Brief · %s · %s</div>'
                            % (b.get("model", ""), humanize(b.get("generated_at"))),
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="sec">AI Morning Brief</div>', unsafe_allow_html=True)
        if b.get("text"):
            with st.container(border=True):
                st.markdown(b["text"])
        else:
            st.info("No brief yet. Click **✨ Generate** (needs an API key), or run "
                    "`python tools/generate_brief.py`. It distills the top oil-relevant "
                    "stories + live prices into a 30-second desk note.")

        st.markdown('<div class="sec" style="margin-top:18px">💬 Ask the news</div>',
                    unsafe_allow_html=True)
        q = st.text_input("Ask", placeholder="e.g. What's the latest on Iran and the Strait of Hormuz?",
                          label_visibility="collapsed", key="ask_box")
        if q:
            if not askmod.available():
                st.caption("Add ANTHROPIC_API_KEY to .env to enable Q&A over the news.")
            else:
                with st.spinner("Reading the wires…"):
                    res = askmod.answer(q)
                with st.container(border=True):
                    st.markdown(res["text"])
                    if res["sources"]:
                        with st.expander("Sources (%d)" % len(res["sources"])):
                            for i, a in enumerate(res["sources"][:15]):
                                st.markdown("**[%d]** [%s](%s) — *%s*"
                                            % (i + 1, a["title"], a.get("url", "#"), a["source_name"]))

    # ============================================================ FEED
    with tab_feed:
        pool = db.query_articles(limit=max(f_limit, 600), sources=f_src or None,
                                 categories=f_cats or None, min_relevance=f_min_rel,
                                 search=f_search.strip() or None)
        pool = [resolve_sentiment(a, use_llm) for a in pool]
        if f_impact in ("bullish", "bearish"):
            pool = [a for a in pool if a.get("impact") == f_impact]
        _now = datetime.now(timezone.utc)
        if f_sort == "Newest":
            pool.sort(key=lambda a: a.get("published_at") or a.get("fetched_at") or "", reverse=True)
        elif f_sort == "Most relevant":
            pool.sort(key=lambda a: (a["relevance"], a.get("published_at") or ""), reverse=True)
        else:
            pool.sort(key=lambda a: rank_score(a, _now), reverse=True)
        clustered = cluster_articles(pool)[:f_limit]
        articles = [c[0] for c in clustered]
        hot = [a for a in articles if a["relevance"] >= 70]
        bull_n = sum(1 for a in articles if a.get("impact") == "bullish")
        bear_n = sum(1 for a in articles if a.get("impact") == "bearish")

        cols = st.columns(4)
        for col, label, val in (
            (cols[0], "Articles stored", stats["total"]),
            (cols[1], "Showing", len(articles)),
            (cols[2], "Bullish / Bearish", "%d / %d" % (bull_n, bear_n)),
            (cols[3], "High-relevance", len(hot)),
        ):
            col.markdown('<div class="kpi"><div class="v">%s</div><div class="l">%s</div></div>'
                         % (val, label), unsafe_allow_html=True)

        # active-filter chips + CSV export
        active = []
        if f_sort != "Smart":
            active.append("sort: " + f_sort)
        if f_min_rel:
            active.append("relevance ≥ %d" % f_min_rel)
        if f_impact != "all":
            active.append(f_impact)
        if f_cats:
            active.append("cat: " + ", ".join(f_cats))
        if f_src:
            active.append("src: " + ", ".join(src_label.get(s, s) for s in f_src))
        if f_search.strip():
            active.append('"%s"' % f_search.strip())
        fc, dc = st.columns([5, 1])
        with fc:
            if active:
                st.markdown('<div style="margin:6px 0">' + "".join(
                    '<span class="chip" style="margin-right:6px">%s</span>' % html.escape(x)
                    for x in active) + "</div>", unsafe_allow_html=True)
        with dc:
            if articles:
                import io
                buf = io.StringIO()
                buf.write("published,source,category,relevance,impact,title,url\n")
                for a in articles:
                    t = (a["title"] or "").replace('"', "'")
                    buf.write('%s,%s,%s,%d,%s,"%s",%s\n' % (
                        a.get("published_at") or a.get("fetched_at") or "", a["source_name"],
                        a["category"], a["relevance"], a.get("impact", ""), t, a.get("url", "")))
                st.download_button("⬇ CSV", buf.getvalue(), file_name="oil_desk_feed.csv",
                                   mime="text/csv", use_container_width=True)
        st.markdown("<hr>", unsafe_allow_html=True)

        if not articles:
            st.info("No articles match these filters. Lower the relevance threshold or clear filters.")
        else:
            html_out = ""
            if f_sort != "Newest" and clustered[0][0]["relevance"] >= 20:
                html_out += hero_card(*clustered[0])
                rest = clustered[1:]
            else:
                rest = clustered
            html_out += "".join(article_card(a, also_in=others) for a, others in rest)
            st.markdown(html_out, unsafe_allow_html=True)

    # ============================================================ PULSE (analytics)
    with tab_pulse:
        if corpus.empty:
            st.info("No data yet — click **⟳ Fetch latest now**.")
        else:
            win = st.selectbox("Window", ["Last 24h", "Last 48h", "Last 7d"], index=1, key="pulse_win")
            hours = {"Last 24h": 24, "Last 48h": 48, "Last 7d": 168}[win]
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            d = corpus[corpus["ts"] >= cutoff].copy()

            nb = int((d["impact"] == "bullish").sum())
            ng = int((d["impact"] == "bearish").sum())
            net = nb - ng
            net_lbl = ("BULLISH +%d" % net) if net > 0 else ("BEARISH %d" % net) if net < 0 else "NEUTRAL 0"
            net_col = BULL if net > 0 else BEAR if net < 0 else MUT
            m = st.columns(4)
            m[0].markdown('<div class="kpi"><div class="v">%d</div><div class="l">Articles (%s)</div></div>' % (len(d), win.lower()), unsafe_allow_html=True)
            m[1].markdown('<div class="kpi"><div class="v" style="color:%s">%d</div><div class="l">Bullish</div></div>' % (BULL, nb), unsafe_allow_html=True)
            m[2].markdown('<div class="kpi"><div class="v" style="color:%s">%d</div><div class="l">Bearish</div></div>' % (BEAR, ng), unsafe_allow_html=True)
            m[3].markdown('<div class="kpi"><div class="v" style="color:%s">%s</div><div class="l">Net crude tone</div></div>' % (net_col, net_lbl), unsafe_allow_html=True)
            st.markdown("<hr>", unsafe_allow_html=True)

            freq = "1h" if hours <= 48 else "6h"
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown('<div class="sec">News flow by crude impact</div>', unsafe_allow_html=True)
                vol = (d.assign(bucket=d["ts"].dt.floor(freq))
                         .groupby(["bucket", "impact"]).size().reset_index(name="n"))
                area = alt.Chart(vol).mark_area(opacity=0.85).encode(
                    x=alt.X("bucket:T", title=None),
                    y=alt.Y("n:Q", title="articles", stack=True),
                    color=alt.Color("impact:N", scale=alt.Scale(
                        domain=["bullish", "neutral", "bearish"], range=[BULL, "#37485a", BEAR]),
                        legend=alt.Legend(title=None, orient="top")),
                    tooltip=["bucket:T", "impact:N", "n:Q"])
                st.altair_chart(style_chart(area, 230), use_container_width=True)
            with c2:
                st.markdown('<div class="sec">Net crude tone over time</div>', unsafe_allow_html=True)
                _g = d.assign(bucket=d["ts"].dt.floor(freq),
                              _pol=(d["impact"] == "bullish").astype(int) - (d["impact"] == "bearish").astype(int))
                sign = _g.groupby("bucket")["_pol"].sum().reset_index(name="net")
                bars = alt.Chart(sign).mark_bar().encode(
                    x=alt.X("bucket:T", title=None),
                    y=alt.Y("net:Q", title="bull − bear"),
                    color=alt.condition(alt.datum.net >= 0, alt.value(BULL), alt.value(BEAR)),
                    tooltip=["bucket:T", "net:Q"])
                st.altair_chart(style_chart(bars, 230), use_container_width=True)

            c3, c4 = st.columns(2)
            with c3:
                st.markdown('<div class="sec">Coverage by desk</div>', unsafe_allow_html=True)
                cat = d.groupby("category").size().reset_index(name="n").sort_values("n", ascending=False)
                ch = alt.Chart(cat).mark_bar(color=ACCENT, cornerRadiusEnd=3).encode(
                    x=alt.X("n:Q", title=None),
                    y=alt.Y("category:N", sort="-x", title=None),
                    tooltip=["category:N", "n:Q"])
                st.altair_chart(style_chart(ch, 220), use_container_width=True)
            with c4:
                st.markdown('<div class="sec">Most active sources</div>', unsafe_allow_html=True)
                srcs = d.groupby("source_name").size().reset_index(name="n").sort_values("n", ascending=False).head(12)
                ch = alt.Chart(srcs).mark_bar(color="#4a9eff", cornerRadiusEnd=3).encode(
                    x=alt.X("n:Q", title=None),
                    y=alt.Y("source_name:N", sort="-x", title=None),
                    tooltip=["source_name:N", "n:Q"])
                st.altair_chart(style_chart(ch, 220), use_container_width=True)

            c5, c6 = st.columns([3, 2])
            with c5:
                st.markdown('<div class="sec">Trending topics (oil-relevant tags)</div>', unsafe_allow_html=True)
                ex = d.explode("tags")
                ex = ex[ex["tags"].notna()]
                if len(ex):
                    top = ex.groupby("tags").size().reset_index(name="n").sort_values("n", ascending=False).head(12)
                    ch = alt.Chart(top).mark_bar(color="#9b6dff", cornerRadiusEnd=3).encode(
                        x=alt.X("n:Q", title=None), y=alt.Y("tags:N", sort="-x", title=None),
                        tooltip=["tags:N", "n:Q"])
                    st.altair_chart(style_chart(ch, 240), use_container_width=True)
                else:
                    st.caption("No tagged topics in this window.")
            with c6:
                st.markdown('<div class="sec">Oil-relevance distribution</div>', unsafe_allow_html=True)
                rel = d[d["relevance"] > 0]
                if len(rel):
                    ch = alt.Chart(rel).mark_bar(color=ACCENT, opacity=0.8).encode(
                        x=alt.X("relevance:Q", bin=alt.Bin(maxbins=20), title="relevance"),
                        y=alt.Y("count():Q", title=None), tooltip=["count():Q"])
                    st.altair_chart(style_chart(ch, 240), use_container_width=True)
                else:
                    st.caption("No oil-relevant articles in this window.")

    # ============================================================ VOICES
    with tab_voices:
        people = load_voices_cfg()
        if corpus.empty or not people:
            st.info("No data / no people configured (see config/voices.yaml).")
        else:
            win = st.selectbox("Window", ["Last 24h", "Last 48h", "Last 7d"], index=1, key="voices_win")
            hours = {"Last 24h": 24, "Last 48h": 48, "Last 7d": 168}[win]
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            d = corpus[corpus["ts"] >= cutoff].copy()
            d["hay"] = (d["title"].fillna("") + " " + d["summary"].fillna("")).str.lower()

            cols = st.columns(2)
            for i, p in enumerate(people):
                pat = "|".join(__import__("re").escape(k) for k in p["keywords"])
                sub = d[d["hay"].str.contains(pat, regex=True, na=False)]
                sub = sub.sort_values(["relevance", "ts"], ascending=[False, False])
                nb = int((sub["impact"] == "bullish").sum())
                ng = int((sub["impact"] == "bearish").sum())
                net = nb - ng
                ncol = BULL if net > 0 else BEAR if net < 0 else MUT
                ntxt = ("▲ +%d" % net) if net > 0 else ("▼ %d" % net) if net < 0 else "— 0"

                items = ""
                # Trump: show his actual Truth Social posts first
                if p.get("truth_source"):
                    ts = sub[sub["source_id"] == p["truth_source"]].head(3)
                    for _, r in ts.iterrows():
                        items += ('<div class="ts"><a href="%s" target="_blank">%s</a>'
                                  '<div class="t">Truth Social · %s</div></div>'
                                  % (html.escape(r["url"]), html.escape(r["title"][:140]),
                                     humanize(r["ts"].isoformat())))
                news = sub[sub["source_id"] != p.get("truth_source")].head(5)
                lis = ""
                for _, r in news.iterrows():
                    dot = ('<span class="pos">▲</span> ' if r["impact"] == "bullish"
                           else '<span class="neg">▼</span> ' if r["impact"] == "bearish" else "")
                    lis += ('<li>%s<a href="%s" target="_blank">%s</a> '
                            '<span style="color:#5b6b7a">· %s</span></li>'
                            % (dot, html.escape(r["url"]), html.escape(r["title"][:110]),
                               html.escape(r["source_name"])))
                if not lis and not items:
                    lis = '<li style="color:#5b6b7a">No mentions in this window.</li>'

                cols[i % 2].markdown(
                    """<div class="voice">
                         <div class="hd">
                           <span class="nm">%s %s</span>
                           <span class="net" style="background:%s22;color:%s">%s</span>
                         </div>
                         <div class="ct">%d mentions · %d bullish · %d bearish</div>
                         %s<ul>%s</ul>
                       </div>""" % (
                        p["emoji"], html.escape(p["name"]), ncol, ncol, ntxt,
                        len(sub), nb, ng, items, lis),
                    unsafe_allow_html=True,
                )

    # ============================================================ MARKETS
    with tab_markets:
        _now2 = datetime.now(timezone.utc)
        evs = events.upcoming(_now2, 6)
        if evs:
            st.markdown('<div class="sec">📅 Upcoming catalysts</div>', unsafe_allow_html=True)
            ev_html = "".join(
                '<div class="evt"><div class="evt-n">%s</div><div class="evt-c">%s</div></div>'
                % (html.escape(e["name"]), events.countdown(e["when"], _now2)) for e in evs
            )
            st.markdown('<div class="evts">%s</div>' % ev_html, unsafe_allow_html=True)

        if quotes:
            st.markdown('<div class="sec">Live commodity & FX tape</div>', unsafe_allow_html=True)
            mc = st.columns(len(quotes))
            for col, q in zip(mc, quotes):
                col.metric("%s %s" % (q["label"], ("(%s)" % q["unit"]) if q["unit"] else ""),
                           "%s" % q["last"], "%+.2f%%" % q["pct"])
        else:
            st.caption("Live quotes unavailable right now (data provider throttled).")

        st.markdown('<div class="sec">Intraday — % change vs day open</div>', unsafe_allow_html=True)
        hist = load_history(("BZ=F", "CL=F", "NG=F"))
        labelmap = {"BZ=F": "Brent", "CL=F": "WTI", "NG=F": "NatGas"}
        frames = []
        for sym, series in hist.items():
            if not series:
                continue
            h = pd.DataFrame(series, columns=["t", "close"])
            h["t"] = pd.to_datetime(h["t"], utc=True)
            base = h["close"].iloc[0] or h["close"].iloc[-1]
            h["pct"] = (h["close"] / base - 1.0) * 100.0 if base else 0.0
            h["inst"] = labelmap.get(sym, sym)
            frames.append(h)
        if frames:
            allh = pd.concat(frames, ignore_index=True)
            line = alt.Chart(allh).mark_line(strokeWidth=2).encode(
                x=alt.X("t:T", title=None),
                y=alt.Y("pct:Q", title="% vs open"),
                color=alt.Color("inst:N", scale=alt.Scale(
                    domain=["Brent", "WTI", "NatGas"], range=[ACCENT, "#4a9eff", BULL]),
                    legend=alt.Legend(title=None, orient="top")),
                tooltip=["inst:N", alt.Tooltip("t:T", title="time"),
                         alt.Tooltip("pct:Q", title="%", format="+.2f")])
            st.altair_chart(style_chart(line, 240), use_container_width=True)
        else:
            st.caption("Intraday series unavailable right now.")

        # historical Brent/WTI with news overlay
        st.markdown('<div class="sec">Brent / WTI history · headlines overlaid</div>',
                    unsafe_allow_html=True)
        per = st.radio("Period", ["1mo", "3mo", "1y"], horizontal=True, key="hist_per",
                       label_visibility="collapsed")
        lh = load_history_long(("BZ=F", "CL=F"), per)
        hframes = []
        for sym, lab in (("BZ=F", "Brent"), ("CL=F", "WTI")):
            ser = lh.get(sym, [])
            if ser:
                hd = pd.DataFrame(ser, columns=["t", "price"])
                hd["t"] = pd.to_datetime(hd["t"], utc=True)
                hd["inst"] = lab
                hframes.append(hd)
        if hframes:
            allh = pd.concat(hframes, ignore_index=True)
            line = alt.Chart(allh).mark_line(strokeWidth=2).encode(
                x=alt.X("t:T", title=None),
                y=alt.Y("price:Q", title="$/bbl", scale=alt.Scale(zero=False)),
                color=alt.Color("inst:N", scale=alt.Scale(domain=["Brent", "WTI"],
                                range=[ACCENT, "#4a9eff"]), legend=alt.Legend(title=None, orient="top")),
                tooltip=["inst:N", alt.Tooltip("price:Q", format=".2f")])
            layers = [line]
            # overlay top headlines on the Brent line
            brent = allh[allh["inst"] == "Brent"][["t", "price"]].sort_values("t")
            if not brent.empty and not corpus.empty:
                wnd = corpus[(corpus["ts"] >= brent["t"].min()) & (corpus["relevance"] >= 50)].copy()
                wnd = wnd.sort_values(["relevance", "ts"], ascending=False).head(20)
                if not wnd.empty:
                    mk = pd.merge_asof(wnd.sort_values("ts")[["ts", "title", "impact"]],
                                       brent.rename(columns={"t": "ts"}), on="ts", direction="nearest")
                    cmap = {"bullish": BULL, "bearish": BEAR, "neutral": "#cbd5e1"}
                    mk["c"] = mk["impact"].map(cmap).fillna("#cbd5e1")
                    pts = alt.Chart(mk).mark_point(size=70, filled=True, opacity=0.9).encode(
                        x="ts:T", y="price:Q",
                        color=alt.Color("c:N", scale=None),
                        tooltip=[alt.Tooltip("title:N", title="headline"),
                                 alt.Tooltip("impact:N"), alt.Tooltip("ts:T", title="date")])
                    layers.append(pts)
            st.altair_chart(style_chart(alt.layer(*layers), 260), use_container_width=True)
            st.caption("● dots = high-relevance headlines (last ~14 days) on the Brent line — "
                       "green bullish, red bearish. Hover for the story.")
        else:
            st.caption("Historical series unavailable right now.")

        spreads = load_spreads()
        equities = load_equities()
        if spreads or equities:
            cl, cr = st.columns([1, 3])
            with cl:
                st.markdown('<div class="sec">Key spreads</div>', unsafe_allow_html=True)
                for s in spreads:
                    st.metric("%s (%s)" % (s["label"], s["unit"]), "%.2f" % s["value"])
            with cr:
                st.markdown('<div class="sec">Energy equities</div>', unsafe_allow_html=True)
                ecols = st.columns(4)
                for i, q in enumerate(equities):
                    ecols[i % 4].metric(q["label"], "%s" % q["last"], "%+.2f%%" % q["pct"])

        inv = load_eia()
        if inv:
            st.markdown('<div class="sec">EIA weekly petroleum balance · week of %s</div>'
                        % html.escape(inv[0].get("period", "")), unsafe_allow_html=True)
            icols = st.columns(len(inv))
            for col, s in zip(icols, inv):
                tag = " 🟢" if s["bias"] == "bullish" else " 🔴" if s["bias"] == "bearish" else ""
                col.metric("%s%s" % (s["label"], tag), "{:,.0f}".format(s["value"]),
                           "{:+,.0f} {}".format(s["change"], s["unit"]),
                           delta_color="inverse" if "stocks" in s["label"].lower() or s["label"] == "SPR" else "normal")
        elif eia.available() is False:
            st.caption("💡 Add **EIA_API_KEY** to `.env` (free at eia.gov/opendata) to show "
                       "weekly crude/SPR/gasoline inventories and production.")

        st.markdown("<hr>", unsafe_allow_html=True)
        near = [resolve_sentiment(a, use_llm) for a in db.query_articles(limit=400, min_relevance=20)]
        bull = sorted([a for a in near if a.get("impact") == "bullish"],
                      key=lambda a: (a.get("impact_score", 0), a["relevance"]), reverse=True)[:8]
        bear = sorted([a for a in near if a.get("impact") == "bearish"],
                      key=lambda a: (a.get("impact_score", 0), -a["relevance"]))[:8]
        cb, cs = st.columns(2)
        with cb:
            st.markdown('<div class="sec" style="color:%s">▲ Bullish for crude</div>' % BULL, unsafe_allow_html=True)
            st.markdown("".join(article_card(a) for a in bull) or "<div class='summary'>None right now.</div>",
                        unsafe_allow_html=True)
        with cs:
            st.markdown('<div class="sec" style="color:%s">▼ Bearish for crude</div>' % BEAR, unsafe_allow_html=True)
            st.markdown("".join(article_card(a) for a in bear) or "<div class='summary'>None right now.</div>",
                        unsafe_allow_html=True)


st.fragment(terminal, run_every=("%ds" % interval) if auto else None)()

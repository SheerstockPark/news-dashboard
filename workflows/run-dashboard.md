# Workflow: run-dashboard

## Objective
Serve the live oil-trading news terminal — a filterable, auto-refreshing Streamlit UI over
the articles in `data/db/news.sqlite`.

## Inputs
- Required: a populated `data/db/news.sqlite` (run the `ingest-news` workflow first).
- Optional: a running ingest loop in a second terminal for true real-time updates.

## Steps
1. (Recommended) Start continuous ingest in one terminal:
   `.venv/bin/python tools/fetch_rss.py --loop --interval 60`
2. Start the dashboard in another:
   `.venv/bin/streamlit run dashboard/app.py`
3. Open http://localhost:8501. Use the sidebar to filter by relevance, category, source,
   and free-text search. Toggle auto-refresh / interval. The **⟳ Fetch latest now** button
   runs a one-shot ingest on demand.

## Expected Output
- Browser terminal UI: KPI strip (articles stored / showing / high-relevance / live sources)
  and a ranked feed. Cards are color-coded by relevance (red ≥70 hot, orange ≥40 warm).

## Edge Cases & Failure Modes
- **Empty feed / "No articles match"**: DB not yet populated, or filters too strict. Run
  ingest, or lower the relevance slider / clear filters.
- **Stale "updated Nd ago"**: ingest loop isn't running. Start it, or use Fetch latest now.
- **Auto-refresh**: implemented via an HTML meta refresh at the chosen interval (no extra
  dependency). DB reads are cached 8s (`@st.cache_data`) so refresh is cheap.
- **Port in use**: pass `--server.port <N>`.

## Tools Used
- `dashboard/app.py` — the Streamlit terminal.
- `src/newsdash/db.py` — read queries (`query_articles`, `stats`).
- `.streamlit/config.toml` — dark theme + headless server defaults.

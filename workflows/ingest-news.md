# Workflow: ingest-news

## Objective
Pull the latest headlines from every configured news source, normalize and oil-relevance-tag
them, and store them (deduplicated) in the SQLite database that the dashboard reads.

## Inputs
- Required: `config/sources.yaml` defining the feeds (id, name, url, category, weight, enabled).
- Optional: specific source ids to limit the fetch; a loop interval for continuous polling.

## Steps
1. Ensure the venv is active / deps installed (`requirements.txt`).
2. Run the ingest tool:
   - One-shot, all sources:  `.venv/bin/python tools/fetch_rss.py`
   - Specific sources:       `.venv/bin/python tools/fetch_rss.py --source oilprice bbc-world`
   - Continuous (high refresh): `.venv/bin/python tools/fetch_rss.py --loop --interval 60`
3. The tool fetches each feed, strips HTML, scores oil-trading relevance (0–100) + topic tags,
   and upserts into `data/db/news.sqlite` (dedup by SHA1 of the article guid/url).

## Expected Output
- New rows in `data/db/news.sqlite` table `articles`.
- A summary line: `Ingest complete: N new article(s), X/Y sources ok`.
- Exit 0 if ≥1 source succeeded; exit 1 only if every source failed.

## Edge Cases & Failure Modes
- **A feed returns 0 entries but HTTP 200**: the endpoint changed. Diagnose with
  `feedparser.parse(url)` and find the current feed URL. *Learned: CNBC moved from
  `search.cnbc.com/rss/2.0/id/<id>/...` to `www.cnbc.com/id/<id>/device/rss/rss.html`.*
- **Reuters / Bloomberg**: no public RSS anymore — covered indirectly via Investing.com,
  MarketWatch, CNBC. Do not add their old feed URLs back; they 404 or return empty.
- **A single source fails**: the tool logs `[FAIL] <name> <error>` to stderr and continues.
  Fix the URL in `config/sources.yaml`, don't disable silently unless the source is dead.
- **Truth Social**: no RSS — would need a dedicated scraper tool (not yet built).
- **Rate limits**: RSS is cheap; `--loop --interval 60` is safe. Don't go below ~30s.

## Tools Used
- `tools/fetch_rss.py` — fetch, normalize, tag, and store feeds.
- `src/newsdash/config.py` — loads & validates `config/sources.yaml`.
- `src/newsdash/tagging.py` — oil-trading relevance scoring + topic tags.
- `src/newsdash/db.py` — SQLite schema, upsert/dedup, queries.

# 🛢️ Oil Desk — News Terminal

A real-time, multi-source news dashboard tuned for an oil/energy trading desk. Aggregates
~15 sources (energy wires, commodities, macro, geopolitics, and Trump's Truth Social),
tags each headline for **oil-relevance** and **bullish/bearish crude impact**, and shows a
live **Brent/WTI/NatGas** price tape — with an optional **daily email digest**.

Built on the WAT architecture: plain-language **W**orkflows (`workflows/`), an **A**gent
orchestrator, and deterministic **T**ools (`tools/`) + shared modules (`src/newsdash/`).

## Quick start (local)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python tools/fetch_rss.py          # pull fresh headlines
.venv/bin/streamlit run dashboard/app.py     # open http://localhost:8501
```

The dashboard self-fetches feeds in-process (cached, ~every 90s), so you don't need a
separate ingest loop. For a continuous local worker anyway:
`.venv/bin/python tools/fetch_rss.py --loop --interval 60`.

## Deploy (Streamlit Community Cloud — free, public URL)

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io → **New app** → pick the repo/branch.
3. Set **Main file path** to `dashboard/app.py`. Deploy.

No background worker needed — the app ingests on load. Data lives in an ephemeral SQLite
DB that repopulates automatically.

## Daily email digest

Runs serverless via `.github/workflows/digest.yml` (GitHub Actions, 06:00 UTC daily).
Add these under **Settings → Secrets and variables → Actions**:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`, `DIGEST_FROM`.
See `.env.example` for the Gmail App Password setup. Test locally:
`.venv/bin/python tools/build_digest.py --fetch --email`.

## Project map

| Path | What |
|---|---|
| `config/sources.yaml` | Feed list — add/disable sources here, no code changes |
| `tools/fetch_rss.py` | Ingest: fetch → normalize → tag → store |
| `tools/build_digest.py` | Build/email the daily digest |
| `src/newsdash/` | Shared: config, db, ingest, tagging, prices |
| `dashboard/app.py` | Streamlit terminal UI |
| `workflows/` | Plain-language SOPs for each task |

> Oil-relevance and crude-impact tags are deterministic keyword heuristics — directional
> hints for triage, **not** trading advice.

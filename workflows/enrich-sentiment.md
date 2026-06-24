# Workflow: enrich-sentiment

## Objective
Upgrade crude-impact tagging from keyword heuristics to a Claude judgment for the
oil-relevant headlines, storing a bullish/bearish/neutral verdict, magnitude, and a
one-line rationale. Opt-in and offline — the dashboard shows it when present.

## Inputs
- Required: `ANTHROPIC_API_KEY` in `.env` (or env). See `.env.example`.
- A populated DB (run the `ingest-news` workflow first).

## Steps
1. Add your key to `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
2. Run the enrichment:
   - `.venv/bin/python tools/enrich_sentiment.py`                 # ~200 recent oil-relevant
   - `.venv/bin/python tools/enrich_sentiment.py --min-relevance 30 --limit 300`
   - `.venv/bin/python tools/enrich_sentiment.py --reclassify`    # re-score existing
3. In the dashboard, the **AI sentiment (when scored)** toggle (sidebar, on by default)
   uses the Claude verdict where available; scored cards show a 🤖 marker and the
   rationale on hover. Unscored articles keep the keyword tag.

## Model & cost
- Model: `claude-haiku-4-5` (cost-effective tier), structured JSON output.
- ~$1 / 1M input, $5 / 1M output tokens. Headlines are batched ~20 per request; a run
  over a few hundred costs well under $0.05. The Batch API would halve it (not used here —
  we favor freshness over the 50% discount).

## Edge Cases & Failure Modes
- **No key**: the tool prints a notice and exits 0 — never errors. Dashboard falls back to
  keyword tagging silently.
- **Unparseable chunk**: that chunk is skipped with a warning; others still store.
- **Cost control**: bound work with `--limit` / `--min-relevance`; only un-scored rows are
  classified unless `--reclassify`.

## Tools Used
- `tools/enrich_sentiment.py` — select → classify → store.
- `src/newsdash/llm_sentiment.py` — Claude Haiku 4.5 structured classification.
- `src/newsdash/db.py` — `set_llm_sentiment`, `llm_*` columns.

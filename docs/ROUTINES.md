# Scheduled Claude routines — briefings on the subscription (no API credit)

The two daily briefings are written by **scheduled Claude Code routines** (cloud agents running
on the owner's Claude plan), not by API calls. Each routine wakes on a cron, pulls fresh
headlines itself, writes the trader-voice prose, and hands delivery to GitHub Actions —
which renders the branded email and sends it via Gmail SMTP (GitHub runners are not
SMTP-blocked; per-day dedupe in `alert_state` makes double-delivery impossible).

Managed at https://claude.ai/code/routines. **Prerequisite:** the claude.ai account must have
GitHub connected (App installed on `SheerstockPark/news-dashboard`) — creation fails with a
401 otherwise.

## The two routines

| Name | Cron (UTC) | Lands (UK, BST) |
|---|---|---|
| Sheerstock Morning Briefing | `0 5 * * *` | 06:00 |
| Sheerstock Evening Briefing | `0 19 * * *` | 20:00 |

Config: environment `Default`, model `claude-sonnet-5`, source repo
`https://github.com/SheerstockPark/news-dashboard`, tools Bash/Read/Write/Edit/Glob/Grep.

## The routine prompt (swap Morning/Evening + the delivery filename)

1. **Setup** — `pip install feedparser PyYAML requests python-dotenv yfinance` (fail-soft; no
   `anthropic` — the routine writes the prose itself).
2. **Headlines** — `python tools/fetch_rss.py` into the local SQLite (no cloud creds), then
   query the freshest ~120 via `newsdash.db.query_articles`.
3. **Prices** (best effort) — yfinance: BZ=F, CL=F, ^GSPC, ^IXIC, ^VIX, DX-Y.NYB, GC=F.
4. **Write** — exact brief.py Markdown shape (**📰 Top Headlines / 🛢 Energy & Fuel /
   🌍 Geopolitics / 📊 Macro & Rates / 📈 Market Movers / 🛡 Reserves & Inventories /
   👀 On the Radar**), terse trader voice, 3–6 bullets/section, never invent facts.
5. **Deliver** — try in order:
   a. `gh workflow run briefing.yml --repo SheerstockPark/news-dashboard --ref main -f edition=Morning -F brief_text=@/tmp/brief.md`
   b. fallback: commit the prose to `briefs/pending-morning.md` and push to main — the
      `push` trigger on briefing.yml delivers it.
6. **Report** — one line saying which path delivered, or a clear FAILED with errors.

## Interplay with the rest of the system

- `briefing.yml` accepts the prose via `brief_text` input or the pushed `briefs/pending-*.md`
  file, passes it to `tools/send_briefing.py --text-file`, and never calls the Claude API.
- `send_briefing.py` marks `alert_state` scope `briefing-<edition>` on confirmed send — the
  watchdog heartbeat reads that same mark, and any other sender (worker, manual dispatch)
  skips if today's mark exists (`--force` overrides).
- If routines are ever retired, re-enable the crons in briefing.yml (needs API credit for
  generation again).

# Scheduled Claude routines — briefings on the subscription (no API credit)

The two daily briefings are written by **scheduled Claude Code routines** (cloud agents running
on the owner's Claude plan), not by API calls. Each routine wakes on a cron, pulls fresh
headlines itself, writes the trader-voice prose, and hands delivery to GitHub Actions —
which renders the branded email and sends it via Gmail SMTP (GitHub runners are not
SMTP-blocked; per-day dedupe in `alert_state` makes double-delivery impossible).

Managed at https://claude.ai/code/routines. **Prerequisite:** the claude.ai account must have
GitHub connected (App installed on `SheerstockPark/news-dashboard`) — creation fails with a
401 otherwise.

## The three routines

| Name | Cron (UTC) | Lands (UK, BST) |
|---|---|---|
| Sheerstock Morning Briefing | `0 5 * * *` | 06:00 daily |
| Sheerstock Evening Briefing | `0 19 * * *` | 20:00 daily |
| Sheerstock Weekly Desk Review | `0 8 * * 6` | 09:00 Saturday |

Config: environment `Default`, model `claude-sonnet-5`, source repo
`https://github.com/SheerstockPark/news-dashboard`, tools Bash/Read/Write/Edit/Glob/Grep.

## The routine prompt (swap Morning/Evening + the delivery filename)

1. **Setup** — `pip install feedparser PyYAML requests python-dotenv yfinance` (fail-soft; no
   `anthropic` — the routine writes the prose itself).
2. **Headlines** — `python tools/fetch_rss.py` into the local SQLite (no cloud creds), then
   query the freshest ~120 via `newsdash.db.query_articles`.
3. **Prices** (best effort) — yfinance: BZ=F, CL=F, ^GSPC, ^IXIC, ^VIX, DX-Y.NYB, GC=F.
4. **Write** — sections, in order: **⚡ Desk Take / 📰 Top Headlines / 🛢 Energy & Fuel /
   🌍 Geopolitics / 📊 Macro & Rates / 📈 Market Movers / 🛡 Reserves & Inventories /
   👀 On the Radar** (bold headers, dash bullets, no title/preamble/code fences).
   Quality bar (see reports/briefing-20260704-evening.html for the reference sample):
   - **⚡ Desk Take** = 1–2 sentences, the single most important tension of the day (what's
     supporting price vs what's capping it) + a posture cue. This is what gets read on a phone.
   - Every bullet = *what happened* + *why the desk cares*, with direction (bullish/bearish)
     where honest. Weave the actual numbers into the prose (Brent level + %, spreads).
   - Prioritise ruthlessly: 3–6 bullets/section, omit an empty section, collapse duplicate
     coverage of the same story into its strongest version.
   - Call out divergences and second-order reads (e.g. gasoline down while crude up = demand
     peak passing; rotation vs risk-off in equities).
   - Weekend/holiday awareness: markets closed → say so; frame Morning as day-ahead, Evening
     as recap + what the overnight/next session brings.
   - NEVER invent facts not present in the gathered headlines/prices; if data is missing
     (prices failed etc.), write around it rather than guessing.
5. **Deliver** — try in order:
   a. `gh workflow run briefing.yml --repo SheerstockPark/news-dashboard --ref main -f edition=Morning -F brief_text=@/tmp/brief.md`
   b. fallback: commit the prose to `briefs/pending-morning.md` and push to main — the
      `push` trigger on briefing.yml delivers it.
6. **Report** — one line saying which path delivered, or a clear FAILED with errors.

## The Weekly Desk Review (Saturday routine)

Same mechanics as the dailies, different brief: analyse the **whole week**, not the day.
Saturday 09:00 UK was chosen deliberately — all Friday settles (incl. late-US energy) are final,
it never collides with a daily briefing, and it reads as the weekend sit-down piece.

Prompt differences from the dailies:
1. **Data window** — the full week: pull ~7 days of archive headlines; get daily closes for the
   week (yfinance `history(period='14d')`) for Brent/WTI/NatGas/Gold/S&P/VIX/DXY and compute
   week-on-week moves. Never invent a number.
2. **Shape** (still plain briefing Markdown — bold `**section**` headers + dash bullets, tables
   as bullet lines): **⚡ Desk Take** (the week's central tension) / **📊 The Week in Numbers**
   (one bullet per market: Fri→Fri level + %) / **🗓 How the Week Unfolded** (one bullet per day)
   / 2–4 **theme sections** with genuine desk reads (divergences, what's mispriced) /
   **👀 The Week Ahead**.
3. **Quality reference** — docs/week-in-review-2026-07-04.html (the hand-written first edition).
4. **Deliver** — dispatch briefing.yml with `edition=Weekly` + the prose (or fallback: commit
   `briefs/pending-weekly.md` and push). Subject becomes "Weekly Desk Review · week ending …";
   per-day dedupe scope `briefing-weekly` means Saturday retries can't double-send.

## Interplay with the rest of the system

- `briefing.yml` accepts the prose via `brief_text` input or the pushed `briefs/pending-*.md`
  file, passes it to `tools/send_briefing.py --text-file`, and never calls the Claude API.
- `send_briefing.py` marks `alert_state` scope `briefing-<edition>` on confirmed send — the
  watchdog heartbeat reads that same mark, and any other sender (worker, manual dispatch)
  skips if today's mark exists (`--force` overrides).
- If routines are ever retired, re-enable the crons in briefing.yml (needs API credit for
  generation again).

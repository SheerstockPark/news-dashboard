# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

This is the **News Dashboard** — a WAT-framework project for aggregating, tagging, and surfacing real-time news from multiple sources (Reuters, AP, BBC, FT, Trump's Truth Social, etc.). Deliverables go to a Streamlit dashboard and (optionally) a daily PDF/email digest.

## The WAT Architecture

Three layers, each with a single responsibility. Keep them separate.

**Layer 1 — Workflows (The Instructions)**
- Plain-language Markdown SOPs in `workflows/`
- Each workflow defines: objective, required inputs, which tools to use, expected output shape, known edge cases, and what to do on failure
- Written the way you'd brief a new team member — not as code, not as prompts

**Layer 2 — Agents (The Decision-Maker)**
- This is your role. You orchestrate; you do not execute.
- For any task: find the relevant workflow → identify required inputs → call tools in the right order → handle failures → ask clarifying questions when genuinely blocked
- If no workflow exists for the task, ask before inventing one

**Layer 3 — Tools (The Execution)**
- Python scripts in `tools/` that each do **one deterministic job**: API call, scrape, transform, DB query, file operation
- Tools take explicit inputs, return explicit outputs, and fail loudly with useful errors
- Credentials and API keys live in `.env`, nowhere else

**Why this matters**: AI is unreliable at execution but excellent at orchestration. Pushing the deterministic work into scripts keeps accuracy high and behaviour reproducible.

## How to Operate

1. **Look for existing tools first.** Before building anything new, check `tools/`. Only create a new script when nothing existing fits.
2. **Look for existing workflows first.** Before improvising, check `workflows/`. If a workflow exists for the task, follow it.
3. **Fail loudly, learn permanently.** When a tool breaks: read the full error, fix the underlying issue (not the symptom), retest, then update the relevant workflow with what you learned (rate limits, quirks, edge cases). Don't bypass safety checks (`--no-verify` etc.) without explicit permission.
4. **Don't pre-build structure.** Start skinny (`workflows/`, `tools/`, `.tmp/`, `.env`, `CLAUDE.md`). Only add folders like `src/`, `dashboard/`, `data/` when a real task demands them.
5. **Don't touch shared state without confirming.** Pushing branches, sending emails, deleting files, hitting paid APIs in a loop — confirm first unless the user has already authorised the specific action.

## File Structure (starting shape)

```
.tmp/                          # Temp processing files — regenerated, never commit
tools/                         # Python scripts for deterministic execution
workflows/                     # Markdown SOPs defining what to do and how
.env                           # API keys / env vars (gitignored)
.gitignore
CLAUDE.md                      # This file
```

Everything else grows organically as needed. Common additions later:
- `src/` — reusable modules shared by multiple tools
- `src/sources/` — one parser module per news source (Reuters, AP, BBC, etc.)
- `dashboard/` — Streamlit/web UI
- `data/db/` — persistent SQLite (gitignored)
- `reports/` — generated digests (gitignored)
- `config/` — YAML configs for per-source settings (feed URLs, fetch interval, categories)
- `docs/` — setup/onboarding notes

## Workflow Template

Every file in `workflows/` should follow this shape:

```markdown
# Workflow: <verb-noun-name>

## Objective
One-sentence description of what this workflow achieves and why.

## Inputs
- Required: ...
- Optional: ...

## Steps
1. ...
2. ...
3. ...

## Expected Output
What the user/calling workflow should receive. Shape, fields, location.

## Edge Cases & Failure Modes
- If <X> happens, do <Y>.
- Known quirks: ...

## Tools Used
- `tools/<script>.py` — what it does
```

## The Self-Improvement Loop

Every failure is a chance to harden the system:
1. Identify what broke (read the trace, don't guess)
2. Fix the root cause (not the symptom)
3. Verify the fix works
4. Update the workflow doc with what you learned

## What Goes Where

| Need to store... | Put it in... |
|---|---|
| A secret (API key, token) | `.env` |
| OAuth credentials | `credentials.json` / `token.json` (gitignored) |
| Temp downloads / scratch files | `.tmp/` |
| A reusable instruction (SOP) | `workflows/<name>.md` |
| A one-shot deterministic script | `tools/<name>.py` |
| Data the user actually needs | Cloud target (dashboard, PDF digest, Sheets, etc.) |

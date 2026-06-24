# Workflow: build-digest

## Objective
Produce (and optionally email) a daily oil-desk digest: the top oil-relevant headlines
from the last 24h plus a live commodity price snapshot, as a self-contained HTML email.

## Inputs
- Required: a populated `data/db/news.sqlite` (or pass `--fetch` to ingest first).
- Optional (for email): SMTP env vars — `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`
  (+ `SMTP_HOST`/`SMTP_PORT`/`DIGEST_FROM`). Locally these can live in `.env`;
  in CI they come from GitHub repo secrets.

## Steps
1. Build only (saved to `reports/digest-YYYYMMDD.html`):
   `.venv/bin/python tools/build_digest.py --fetch`
2. Build + email:
   `.venv/bin/python tools/build_digest.py --fetch --email`
3. Tune: `--hours 24 --top 25 --min-relevance 25`.

## Automated schedule
`.github/workflows/digest.yml` runs daily at 06:00 UTC (and on manual dispatch). It
installs deps, ingests fresh feeds, builds the digest, emails it, and uploads the HTML
as a run artifact. Configure secrets under **Settings → Secrets and variables → Actions**:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`, `DIGEST_FROM`.

## Expected Output
- `reports/digest-YYYYMMDD.html` written.
- If `--email` and creds present: email sent to `DIGEST_TO`; otherwise a skip message.

## Edge Cases & Failure Modes
- **Gmail**: use an App Password (not your login password); 2FA must be on. Host
  `smtp.gmail.com`, port `587` (STARTTLS).
- **No creds**: the tool still writes the HTML and prints a skip notice — never errors.
- **Empty digest**: widen `--hours` or lower `--min-relevance`; check ingest succeeded.

## Tools Used
- `tools/build_digest.py` — query, render HTML, optional SMTP send.
- `src/newsdash/prices.py` — price snapshot; `src/newsdash/db.py` — article query.

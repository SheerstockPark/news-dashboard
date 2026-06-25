"""Email delivery — provider-agnostic, fail-soft, gated.

Prefers Resend (HTTP API) when RESEND_API_KEY is set — the most reliable path for automated
mail. Otherwise falls back to SMTP (Gmail / Google Workspace / Microsoft 365) using the
SMTP_* vars. Either way the caller just builds HTML and calls send_html(); this module picks
the backend. Credentials come from env / .env / GitHub-or-Streamlit secrets — never code.

Config (set whichever backend you use):
    Resend:  RESEND_API_KEY, DIGEST_TO, DIGEST_FROM (default "Sheerstock Park <onboarding@resend.dev>")
    SMTP:    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 587),
             SMTP_USER, SMTP_PASS, DIGEST_TO (comma-separated), DIGEST_FROM (default SMTP_USER)
"""

import os
from typing import List, Optional

import requests

_RESEND_DEFAULT_FROM = "Sheerstock Park <onboarding@resend.dev>"


def _env(name: str, default: str = "") -> str:
    if not os.environ.get(name):
        try:
            from dotenv import load_dotenv

            from . import REPO_ROOT

            load_dotenv(REPO_ROOT / ".env")
        except Exception:
            pass
    return os.environ.get(name, default)


def recipients() -> List[str]:
    return [x.strip() for x in _env("DIGEST_TO").split(",") if x.strip()]


def backend() -> str:
    if _env("RESEND_API_KEY"):
        return "resend"
    if _env("SMTP_USER") and _env("SMTP_PASS"):
        return "smtp"
    return "none"


def configured() -> bool:
    return backend() != "none" and bool(recipients())


def _send_resend(subject: str, html: str, text: Optional[str], to: List[str]) -> bool:
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": "Bearer %s" % _env("RESEND_API_KEY")},
        json={
            "from": _env("DIGEST_FROM") or _RESEND_DEFAULT_FROM,
            "to": to,
            "subject": subject,
            "html": html,
            **({"text": text} if text else {}),
        },
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError("Resend %d: %s" % (r.status_code, r.text[:300]))
    return True


def _send_smtp(subject: str, html: str, text: Optional[str], to: List[str]) -> bool:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _env("DIGEST_FROM") or _env("SMTP_USER")
    msg["To"] = ", ".join(to)
    if text:
        msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    # Use `or` (not the get-default) so empty secrets — e.g. SMTP_PORT passed as "" by the
    # GitHub workflow when the secret isn't set — fall back to the Gmail defaults.
    host = _env("SMTP_HOST") or "smtp.gmail.com"
    port = int(_env("SMTP_PORT") or "587")
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(_env("SMTP_USER"), _env("SMTP_PASS"))
        s.sendmail(msg["From"], to, msg.as_string())
    return True


def send_html(subject: str, html: str, text: Optional[str] = None) -> bool:
    """Send an HTML email via the configured backend. Returns False (no raise) if unconfigured."""
    b = backend()
    to = recipients()
    if b == "none" or not to:
        return False
    if b == "resend":
        return _send_resend(subject, html, text, to)
    return _send_smtp(subject, html, text, to)

#!/usr/bin/env python3
"""Verify the database connection (local SQLite or cloud Turso) and report health.

Run this after configuring Turso to confirm the cloud DB works before relying on it:
    TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... python tools/db_check.py
Locally (no env) it checks the SQLite file. Exits non-zero on failure.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

try:
    from dotenv import load_dotenv

    from newsdash import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

from newsdash import db  # noqa: E402


def main() -> int:
    print("Backend: %s" % db.backend())
    if db.backend() == "turso":
        print("  URL: %s" % os.environ.get("TURSO_DATABASE_URL", "")[:48])
    try:
        db.init_db()
        s = db.stats()
        print("Connected OK ✅")
        print("  articles stored: %d" % s["total"])
        print("  latest fetch:    %s" % s["latest_fetch"])
        print("  sources:         %d" % len(s["per_source"]))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("Connection FAILED ❌: %s" % exc, file=sys.stderr)
        if db.backend() == "turso":
            print("  Check TURSO_DATABASE_URL (libsql://... or https://...) and TURSO_AUTH_TOKEN.",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

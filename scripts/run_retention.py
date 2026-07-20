"""Run the payload retention/tombstone job.

Run: python scripts/run_retention.py

Uses OBSV_RETENTION_DATABASE_URL (from .env.generated or the environment) --
never the app or owner credentials, since retention should only ever be able
to touch obsv_payloads, never obsv_audit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from obsvagent.db.env import get_retention_database_url  # noqa: E402
from obsvagent.db.retention import run_retention_job  # noqa: E402


def main() -> int:
    dsn = get_retention_database_url()
    if not dsn:
        print("OBSV_RETENTION_DATABASE_URL not set -- run scripts/apply_migrations.py first.", file=sys.stderr)
        return 1
    count = run_retention_job(dsn)
    print(f"Tombstoned {count} expired payload(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

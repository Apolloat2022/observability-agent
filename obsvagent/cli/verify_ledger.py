"""verify-ledger CLI (Phase 5, 🟢). Re-walks a project's audit chain and
reports the first broken link, if any. Wire into nightly CI as an integrity
check; a compliance dashboard can surface its exit code as a badge.

Entrypoint declared in pyproject.toml: `verify-ledger --project <name>`.
"""
from __future__ import annotations

import argparse
import sys

import psycopg

from ..db.dao import AuditDAO
from ..db.env import get_app_database_url, get_database_url
from ..ledger import verify_chain


def _resolve_database_url(explicit: str | None) -> str:
    url = explicit or get_app_database_url() or get_database_url()
    if not url:
        print("No database URL available (checked --database-url, OBSV_APP_DATABASE_URL, DATABASE_URL).", file=sys.stderr)
        sys.exit(2)
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-ledger", description="Verify an audit ledger's hash chain")
    parser.add_argument("--project", required=True, help="project name (obsv_audit.project column)")
    parser.add_argument("--database-url", default=None, help="override the DB connection (else env/.env)")
    args = parser.parse_args(argv)

    dsn = _resolve_database_url(args.database_url)

    with psycopg.connect(dsn) as conn:
        records = AuditDAO.fetch_ordered(conn, args.project)

    if not records:
        print(f"project {args.project!r}: no audit records found")
        return 0

    result = verify_chain(records)
    if result.ok:
        print(f"project {args.project!r}: OK -- {result.checked} records verified, chain intact")
        return 0

    print(
        f"project {args.project!r}: BROKEN CHAIN -- first broken record: "
        f"{result.first_broken_id!r} ({result.reason}); {result.checked} records checked before failure"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Apply Neon migrations + provision the obsv_app/obsv_retention roles.

Run: python scripts/apply_migrations.py

Connects with the owner credentials from .env's DATABASE_URL, applies every
migration in obsvagent/db/migrations.py, generates fresh random passwords
for the two least-privileged roles, and writes their connection URLs to
.env.generated (gitignored — never commit it). Safe to re-run: migrations
are idempotent (tracked in obsv_schema_migrations) and role passwords are
rotated on every run.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from obsvagent.db.env import get_database_url  # noqa: E402
from obsvagent.db.migrations import apply_migrations  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GENERATED_ENV = _REPO_ROOT / ".env.generated"


def _url_with_role(owner_url: str, role: str, password: str) -> str:
    parts = urlsplit(owner_url)
    netloc = f"{role}:{password}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def main() -> int:
    owner_url = get_database_url()
    if not owner_url:
        print("DATABASE_URL not set (checked env and .env) -- aborting.", file=sys.stderr)
        return 1

    with psycopg.connect(owner_url) as conn:
        applied = apply_migrations(conn)
        print(f"Migrations applied this run: {applied or '(none — already up to date)'}")

        app_password = secrets.token_urlsafe(32)
        retention_password = secrets.token_urlsafe(32)
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("ALTER ROLE obsv_app WITH PASSWORD {}").format(psycopg.sql.Literal(app_password))
            )
            cur.execute(
                psycopg.sql.SQL("ALTER ROLE obsv_retention WITH PASSWORD {}").format(
                    psycopg.sql.Literal(retention_password)
                )
            )
        conn.commit()

    app_url = _url_with_role(owner_url, "obsv_app", app_password)
    retention_url = _url_with_role(owner_url, "obsv_retention", retention_password)

    _GENERATED_ENV.write_text(
        f"OBSV_APP_DATABASE_URL={app_url}\nOBSV_RETENTION_DATABASE_URL={retention_url}\n",
        encoding="utf-8",
    )
    print(f"obsv_app / obsv_retention credentials written to {_GENERATED_ENV} (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

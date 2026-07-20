"""DATABASE_URL resolution — os.environ first, falling back to a `.env` file
at the repo root (simple KEY=VALUE parsing, no new dependency for this).

`.env` is gitignored; never commit real credentials into a migration or test
file. This module is the single place that reads it.
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"
_GENERATED_ENV_FILE = _REPO_ROOT / ".env.generated"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def get_database_url() -> str | None:
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    return _parse_env_file(_ENV_FILE).get("DATABASE_URL")


def get_app_database_url() -> str | None:
    """The least-privileged obsv_app role's URL, written by
    scripts/apply_migrations.py to .env.generated (gitignored)."""
    if "OBSV_APP_DATABASE_URL" in os.environ:
        return os.environ["OBSV_APP_DATABASE_URL"]
    return _parse_env_file(_GENERATED_ENV_FILE).get("OBSV_APP_DATABASE_URL")


def get_retention_database_url() -> str | None:
    if "OBSV_RETENTION_DATABASE_URL" in os.environ:
        return os.environ["OBSV_RETENTION_DATABASE_URL"]
    return _parse_env_file(_GENERATED_ENV_FILE).get("OBSV_RETENTION_DATABASE_URL")

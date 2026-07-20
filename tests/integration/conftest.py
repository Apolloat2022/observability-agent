"""Integration test fixtures — these tests hit the REAL Neon instance
configured in .env / .env.generated. They are skipped automatically (not
failed) when those files/env vars aren't present, so the main test suite
stays runnable offline for anyone without DB access."""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Coroutine

import pytest

from obsvagent.db.env import get_app_database_url, get_database_url, get_retention_database_url


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """asyncio.run(), but on Windows forces a SelectorEventLoop -- psycopg's
    async mode cannot use the platform-default ProactorEventLoop there.
    Production runs in Docker on Linux (see docker/), where this branch never
    triggers; this is purely a Windows dev-environment accommodation and
    deliberately lives in the test helper, not in db/writer.py itself."""
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def owner_url() -> str:
    url = get_database_url()
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping live Neon integration tests")
    return url


@pytest.fixture(scope="session")
def app_url() -> str:
    url = get_app_database_url()
    if not url:
        pytest.skip("OBSV_APP_DATABASE_URL not configured -- run scripts/apply_migrations.py first")
    return url


@pytest.fixture(scope="session")
def retention_url() -> str:
    url = get_retention_database_url()
    if not url:
        pytest.skip("OBSV_RETENTION_DATABASE_URL not configured -- run scripts/apply_migrations.py first")
    return url

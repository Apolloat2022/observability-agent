"""Phase 5 — retention.py live tests: expired payloads get tombstoned,
non-expired ones are left alone."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from obsvagent.db.dao import PayloadDAO
from obsvagent.db.retention import run_retention_job


def test_retention_tombstones_expired_but_not_fresh_payloads(app_url: str, retention_url: str):
    expired_id = f"retention-expired-{uuid.uuid4().hex[:8]}"
    fresh_id = f"retention-fresh-{uuid.uuid4().hex[:8]}"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    with psycopg.connect(app_url) as conn:
        PayloadDAO.insert(
            conn, payload_id=expired_id, trace_id="T-ret", kind="completion",
            content="expired content", content_hash="hash-expired", expires_at_iso=past,
        )
        PayloadDAO.insert(
            conn, payload_id=fresh_id, trace_id="T-ret", kind="completion",
            content="fresh content", content_hash="hash-fresh", expires_at_iso=future,
        )

    count = run_retention_job(retention_url)
    assert count >= 1  # at least ours (other tests may also have left expired rows)

    with psycopg.connect(app_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content, tombstoned_at FROM obsv.obsv_payloads WHERE id = %s", (expired_id,))
            expired_content, expired_tombstoned = cur.fetchone()
            cur.execute("SELECT content, tombstoned_at FROM obsv.obsv_payloads WHERE id = %s", (fresh_id,))
            fresh_content, fresh_tombstoned = cur.fetchone()

    assert expired_content is None
    assert expired_tombstoned is not None
    assert fresh_content == "fresh content"
    assert fresh_tombstoned is None


def test_retention_is_idempotent(retention_url: str):
    first = run_retention_job(retention_url)
    second = run_retention_job(retention_url)
    assert second == 0  # nothing left to tombstone after the first pass
    assert first >= 0

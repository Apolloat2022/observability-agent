"""Payload retention/tombstone job (Phase 5, 🟢). Finds obsv_payloads rows
past their TTL and tombstones them (nulls `content`, keeps `content_hash` so
the record that a claim was made stays provable without retaining the raw,
possibly-PII-bearing text). Uses the obsv_retention role, which has UPDATE
on obsv_payloads and ZERO access to obsv_audit (see db/migrations.py 0005) --
retention can never touch the ledger.
"""
from __future__ import annotations

import psycopg

from .dao import PayloadDAO


def run_retention_job(dsn: str) -> int:
    """Tombstone every expired, not-yet-tombstoned payload. Returns the
    count tombstoned. Idempotent -- `expired_ids()` only returns rows where
    `tombstoned_at IS NULL`, so re-running after a partial failure is safe."""
    with psycopg.connect(dsn) as conn:
        ids = PayloadDAO.expired_ids(conn)
        for payload_id in ids:
            PayloadDAO.tombstone(conn, payload_id)
    return len(ids)

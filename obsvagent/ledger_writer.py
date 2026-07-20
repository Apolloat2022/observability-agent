"""PostgresLedgerWriter — implements interfaces.LedgerWriter (Phase 5, 🟡
review gate). INSERT-only, FAIL-CLOSED: any failure to append raises
LedgerAppendError, and the caller MUST treat that as "the underlying
decision does not ship" (per the blueprint's compliance §4 fail-closed
requirement).

Serialization uses a Postgres advisory transaction lock keyed by project
(`pg_advisory_xact_lock`), NOT a Python threading/asyncio.Lock. A per-process
lock only protects one process; the realistic deployment shape for a
compliance ledger is multiple app server replicas all writing to the same
Neon instance, so the lock has to be enforced by the database itself. The
lock is held for exactly one transaction (acquire -> read head -> seal ->
insert -> commit, which releases it), which is also what guarantees
`ids.new_audit_id()`'s monotonic-id contract actually matches insertion
order: the audit_id is generated INSIDE this lock, not by the caller, so two
concurrent appenders can never interleave their id generation with their
insert order.
"""
from __future__ import annotations

import psycopg

from .db.dao import AuditDAO
from .ids import new_audit_id
from .ledger import GENESIS_CHAIN_HASH, AuditRecord, seal


class LedgerAppendError(RuntimeError):
    """Raised on any failure to append. Callers MUST treat this as
    fail-closed: the underlying decision must not ship."""


class PostgresLedgerWriter:
    """Implements interfaces.LedgerWriter."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def head_chain_hash(self, project: str) -> str:
        try:
            with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT chain_hash FROM obsv.obsv_audit WHERE project = %s ORDER BY audit_id DESC LIMIT 1",
                    (project,),
                )
                row = cur.fetchone()
        except Exception as exc:
            raise LedgerAppendError(f"failed to read chain head for {project!r}: {exc}") from exc
        return row[0] if row else GENESIS_CHAIN_HASH

    def append(self, record: AuditRecord) -> AuditRecord:
        """`record.audit_id` is OVERWRITTEN with a fresh id generated inside
        the lock, regardless of what the caller passed -- id generation must
        happen under the same lock as the head-read + insert for the
        id-order-equals-chain-order guarantee to hold across concurrent
        appenders."""
        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (record.project,))
                    cur.execute(
                        "SELECT chain_hash FROM obsv.obsv_audit WHERE project = %s "
                        "ORDER BY audit_id DESC LIMIT 1",
                        (record.project,),
                    )
                    row = cur.fetchone()
                prev_hash = row[0] if row else GENESIS_CHAIN_HASH

                record.audit_id = new_audit_id()
                sealed = seal(record, prev_hash)
                AuditDAO.insert(conn, sealed)  # commits, releasing the advisory lock
        except Exception as exc:
            raise LedgerAppendError(f"failed to append audit record for {record.project!r}: {exc}") from exc
        return sealed

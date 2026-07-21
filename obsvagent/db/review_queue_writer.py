"""PostgresAuditQueueWriter — implements checker.node.AuditQueueWriter
(Phase 7, 🟢), backed by obsv_review_queue. Handed to CheckerNode so a
non-PASS verdict lands in the human-review queue the Next.js UI reads from.
"""
from __future__ import annotations

import psycopg

from ..checker.schema import CheckerVerdict
from .dao import ReviewQueueDAO


class PostgresAuditQueueWriter:
    def __init__(self, dsn: str, *, tenant: str | None = None) -> None:
        self._dsn = dsn
        self._tenant = tenant

    def write(self, *, trace_id: str, route: str, verdict: CheckerVerdict) -> None:
        with psycopg.connect(self._dsn) as conn:
            ReviewQueueDAO.write(conn, trace_id=trace_id, route=route, verdict=verdict, tenant=self._tenant)

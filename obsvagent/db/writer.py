"""PostgresEventWriter — batched async writer implementing
interfaces.EventSink against obsv.obsv_events (Phase 2, 🟡).

Mirrors sink.py's RingBufferSink shape (bounded deque `emit()`, async
`drain()`) but targets Neon instead of OTel spans. Apps wire BOTH sinks
(Tempo via sink.RingBufferSink, Neon via this) behind sink.FanOutSink so one
`emit()` reaches both destinations.

Day-partitions are created lazily via `obsv.ensure_events_partition()`
(see db/migrations.py) — at most once per calendar day per process, cached
in `_partitions_ensured` so subsequent drains skip the check.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..ids import new_ulid

_DEFAULT_MAXLEN = 10_000
_INSERT_SQL = """
    INSERT INTO obsv.obsv_events
        (id, trace_id, route, tenant, span_name, start_ns, end_ns, latency_ms, attributes)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class PostgresEventWriter:
    """Implements interfaces.EventSink. `emit()` is O(1) (deque append);
    all Postgres I/O happens in `drain()`, off the request path. Overflow
    policy matches sink.RingBufferSink: fail-open, oldest-effectively-dropped
    (bounded deque discards silently past maxlen; `dropped_count` tracks it)."""

    def __init__(self, dsn: str, *, maxlen: int = _DEFAULT_MAXLEN) -> None:
        self._dsn = dsn
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._dropped = 0
        self._partitions_ensured: set[str] = set()

    def emit(self, event: dict[str, Any]) -> None:
        if len(self._buffer) == (self._buffer.maxlen or 0):
            self._dropped += 1
        self._buffer.append(event)

    @property
    def dropped_count(self) -> int:
        return self._dropped

    @property
    def depth(self) -> int:
        return len(self._buffer)

    async def drain(self) -> int:
        if not self._buffer:
            return 0
        batch: list[dict[str, Any]] = []
        while self._buffer:
            batch.append(self._buffer.popleft())

        today = time.strftime("%Y-%m-%d")
        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            if today not in self._partitions_ensured:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT obsv.ensure_events_partition(%s)", (today,))
                await conn.commit()
                self._partitions_ensured.add(today)

            rows = [self._to_row(e) for e in batch]
            async with conn.cursor() as cur:
                await cur.executemany(_INSERT_SQL, rows)
            await conn.commit()
        return len(batch)

    @staticmethod
    def _to_row(event: dict[str, Any]) -> tuple:
        e = dict(event)
        span_name = e.pop("_span_name", "obsv.event")
        start_ns = e.pop("_start_ns", None)
        end_ns = e.pop("_end_ns", None)
        trace_id = e.pop("obsv.trace_id", None) or new_ulid()
        route = e.pop("obsv.route", None)
        tenant = e.pop("obsv.tenant", None)
        latency_ms = e.pop("obsv.latency_ms", None)
        # Everything left over (http.*, gen_ai.*, obsv.node.*, ...) goes into
        # `attributes` jsonb rather than being enumerated as columns -- event
        # shapes vary per emitter (middleware/gateway/graph/checker) and this
        # keeps the table schema stable as new attribute keys are added.
        return (new_ulid(), trace_id, route, tenant, span_name, start_ns, end_ns, latency_ms, Jsonb(e))

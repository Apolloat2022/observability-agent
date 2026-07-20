"""Phase 2 acceptance criterion (HANDOFF.md): writer survives a backpressure
burst without dropping on the hot path. Proven against the real Neon
instance -- burst-emit N events, confirm emit() stayed O(1) throughout (no
I/O happens until drain()), zero drops, and every row actually persisted."""
from __future__ import annotations

import time
import uuid

import psycopg

from obsvagent.db.writer import PostgresEventWriter

from .conftest import run_async


def test_burst_emit_is_fast_and_drops_nothing_within_capacity(app_url: str):
    marker = f"burst-{uuid.uuid4().hex[:12]}"
    n = 5000
    writer = PostgresEventWriter(app_url, maxlen=n + 100)

    start = time.perf_counter()
    for i in range(n):
        writer.emit(
            {
                "_span_name": "bench.event",
                "obsv.trace_id": marker,
                "obsv.route": "bench_route",
                "obsv.tenant": "bench_tenant",
                "seq": i,
            }
        )
    burst_elapsed = time.perf_counter() - start

    assert writer.dropped_count == 0
    assert writer.depth == n
    # 5000 in-memory deque appends -- generous headroom (should be low
    # single-digit ms in reality; no I/O happens until drain()).
    assert burst_elapsed < 1.0, f"emit() burst took {burst_elapsed:.3f}s -- hot path should never touch I/O"

    drained = run_async(writer.drain())
    assert drained == n
    assert writer.depth == 0

    with psycopg.connect(app_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM obsv.obsv_events WHERE trace_id = %s", (marker,))
            (count,) = cur.fetchone()
    assert count == n, "every burst-emitted event must actually persist -- no silent loss"


def test_drain_is_idempotent_when_buffer_empty(app_url: str):
    writer = PostgresEventWriter(app_url)
    assert run_async(writer.drain()) == 0


def test_overflow_beyond_maxlen_is_tracked_not_silently_ignored(app_url: str):
    writer = PostgresEventWriter(app_url, maxlen=10)
    for i in range(15):
        writer.emit({"_span_name": "x", "seq": i})
    assert writer.dropped_count == 5
    assert writer.depth == 10
    run_async(writer.drain())  # drain what's left so the test cleans up after itself

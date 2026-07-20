"""Benchmark: ObservabilityMiddleware request overhead.

Phase 1 acceptance criterion (HANDOFF.md): middleware p99 overhead < 1 ms.
Run: python scripts/bench_middleware.py [n_requests]

Measures END-TO-END wall time through the middleware wrapping a trivial
downstream app, against a baseline of the SAME downstream app with no
middleware — the delta isolates the middleware's own cost from asyncio/event
loop noise, which is the number the acceptance criterion is actually about
(sink.emit is an in-memory deque append; no I/O happens on this path).
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time

from obsvagent.interfaces import EventSink
from obsvagent.middleware import ObservabilityMiddleware


class _NullSink:
    def emit(self, event: dict) -> None:
        pass

    async def drain(self) -> int:
        return 0


async def _downstream_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _run_once(app) -> None:
    scope = {"type": "http", "method": "GET", "headers": []}

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        pass

    await app(scope, receive, send)


def _percentile(samples: list[float], p: float) -> float:
    s = sorted(samples)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


async def _timed_series(app, n: int) -> list[float]:
    """Run n iterations inside ONE event loop so per-call asyncio.run()
    startup cost (loop creation/teardown, ~0.5-1ms on this machine) doesn't
    swamp the microsecond-scale thing we're actually measuring."""
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        await _run_once(app)
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


def bench(n: int) -> None:
    sink: EventSink = _NullSink()
    mw = ObservabilityMiddleware(_downstream_app, sink=sink, route="bench")

    async def _all() -> tuple[list[float], list[float]]:
        # Warm up (import caches, allocator warmup) within the same loop.
        for _ in range(500):
            await _run_once(_downstream_app)
            await _run_once(mw)
        baseline = await _timed_series(_downstream_app, n)
        instrumented = await _timed_series(mw, n)
        return baseline, instrumented

    baseline, instrumented = asyncio.run(_all())

    base_p50, base_p99 = _percentile(baseline, 0.50), _percentile(baseline, 0.99)
    inst_p50, inst_p99 = _percentile(instrumented, 0.50), _percentile(instrumented, 0.99)
    overhead_p50 = max(inst_p50 - base_p50, 0.0)
    overhead_p99 = max(inst_p99 - base_p99, 0.0)

    print(f"n={n}")
    print(f"baseline      p50={base_p50:.4f}ms  p99={base_p99:.4f}ms")
    print(f"instrumented  p50={inst_p50:.4f}ms  p99={inst_p99:.4f}ms")
    print(f"middleware overhead  p50={overhead_p50:.4f}ms  p99={overhead_p99:.4f}ms")
    print(f"mean overhead: {statistics.mean(instrumented) - statistics.mean(baseline):.4f}ms")

    if overhead_p99 >= 1.0:
        print("FAIL: p99 overhead >= 1ms")
        sys.exit(1)
    print("PASS: p99 overhead < 1ms")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    bench(n)

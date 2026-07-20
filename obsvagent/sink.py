"""EventSink — bounded ring buffer + async OTLP drain (Phase 1).

Hot-path cost is ONE deque append (`emit`). All exporter I/O happens in
`drain()`, called periodically by a background asyncio task — never on the
request path. Implements interfaces.EventSink.

Overflow policy is fail-open: when the buffer is full, the newest event is
counted as dropped rather than blocking the caller or evicting history
(`deque.append` without maxlen semantics is avoided on purpose — see
`RingBufferSink.emit`). Telemetry loss under sustained overload is
acceptable; request failure is not.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_DEFAULT_MAXLEN = 10_000
_SPAN_NAME_KEY = "_span_name"
_START_NS_KEY = "_start_ns"
_END_NS_KEY = "_end_ns"


def build_tracer_provider(
    *, service_name: str, otlp_endpoint: str = "localhost:4317", insecure: bool = True
) -> TracerProvider:
    """Call once at process startup. `service_name` becomes the Tempo/Grafana
    service name — use the repo name (e.g. "riskguard-ai"). `otlp_endpoint`
    defaults to the shared observability stack (docker/docker-compose.observability.yml)."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=insecure)
    provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=512, schedule_delay_millis=5000))
    return provider


class RingBufferSink:
    """Default EventSink. Events are plain dicts; `drain()` materializes each
    as a completed OTel span with an explicit start/end time, so span
    creation cost is paid off the request path."""

    def __init__(self, tracer_provider: TracerProvider, *, maxlen: int = _DEFAULT_MAXLEN) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._dropped = 0
        self._tracer = tracer_provider.get_tracer("obsvagent")

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
        """Pop everything currently buffered and emit each as a span. Safe to
        call concurrently with `emit` — `deque.append`/`popleft` are each
        atomic under the GIL, so no explicit lock is needed for a
        single-writer-many-reader-of-one (asyncio, single event loop) pattern."""
        drained = 0
        while self._buffer:
            event = self._buffer.popleft()
            self._emit_span(event)
            drained += 1
        return drained

    def _emit_span(self, event: dict[str, Any]) -> None:
        name = event.pop(_SPAN_NAME_KEY, "obsv.request")
        start_ns = event.pop(_START_NS_KEY, time.time_ns())
        end_ns = event.pop(_END_NS_KEY, time.time_ns())
        span = self._tracer.start_span(name, start_time=start_ns)
        for key, value in event.items():
            if value is not None:
                span.set_attribute(key, value)
        span.end(end_time=end_ns)


class FanOutSink:
    """Composes multiple EventSink implementations behind one `emit()` --
    e.g. RingBufferSink (-> Tempo) + db.writer.PostgresEventWriter (-> Neon),
    so telemetry lands in both destinations from a single call site
    (middleware.py / gateway.py / graph.py never need to know how many
    sinks are actually wired)."""

    def __init__(self, *sinks: Any) -> None:
        self._sinks = sinks

    def emit(self, event: dict[str, Any]) -> None:
        for s in self._sinks:
            s.emit(dict(event))  # each sink may mutate/pop keys during drain

    async def drain(self) -> int:
        total = 0
        for s in self._sinks:
            total += await s.drain()
        return total


async def run_drain_loop(
    sink: Any, *, interval_s: float = 2.0, stop: asyncio.Event | None = None
) -> None:
    """Background task: call sink.drain() on an interval. Wire into the app's
    FastAPI `lifespan` as `asyncio.create_task(run_drain_loop(sink, stop=stop_event))`;
    set `stop_event` and await the task on shutdown so the final batch flushes.
    Accepts any EventSink-shaped object (RingBufferSink, PostgresEventWriter,
    FanOutSink, ...) -- typed as `Any` rather than the Protocol to avoid an
    import cycle with interfaces.py, which itself references sink-shaped types."""
    while stop is None or not stop.is_set():
        await sink.drain()
        await asyncio.sleep(interval_s)
    await sink.drain()  # final flush

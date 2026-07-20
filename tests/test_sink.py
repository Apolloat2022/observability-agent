"""Phase 1 — sink.py tests. Uses OTel's in-memory exporter (sync,
no network) to verify RingBufferSink materializes buffered events into
correctly-attributed spans."""
from __future__ import annotations

import asyncio
import time

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obsvagent.interfaces import EventSink
from obsvagent.sink import RingBufferSink, run_drain_loop


def _provider_with_memory_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_implements_event_sink_protocol():
    provider, _ = _provider_with_memory_exporter()
    assert isinstance(RingBufferSink(provider), EventSink)


def test_emit_then_drain_materializes_span_with_attributes():
    provider, exporter = _provider_with_memory_exporter()
    sink = RingBufferSink(provider)

    now_ns = time.time_ns()
    sink.emit(
        {
            "_span_name": "GET riskguard_assessment",
            "_start_ns": now_ns,
            "_end_ns": now_ns + 5_000_000,
            "obsv.trace_id": "01ABCXYZ",
            "obsv.route": "riskguard_assessment",
            "http.status_code": 200,
        }
    )

    drained = asyncio.run(sink.drain())
    assert drained == 1
    assert sink.depth == 0

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET riskguard_assessment"
    assert span.attributes["obsv.trace_id"] == "01ABCXYZ"
    assert span.attributes["obsv.route"] == "riskguard_assessment"
    assert span.attributes["http.status_code"] == 200


def test_drain_is_idempotent_on_empty_buffer():
    provider, _ = _provider_with_memory_exporter()
    sink = RingBufferSink(provider)
    assert asyncio.run(sink.drain()) == 0


def test_overflow_drops_oldest_and_counts_it():
    provider, exporter = _provider_with_memory_exporter()
    sink = RingBufferSink(provider, maxlen=2)

    for i in range(3):
        sink.emit({"_span_name": f"e{i}"})

    assert sink.dropped_count == 1
    assert sink.depth == 2
    asyncio.run(sink.drain())
    names = {s.name for s in exporter.get_finished_spans()}
    assert names == {"e1", "e2"}  # e0 was evicted by the bounded deque


def test_run_drain_loop_flushes_on_stop():
    provider, exporter = _provider_with_memory_exporter()
    sink = RingBufferSink(provider)
    sink.emit({"_span_name": "queued"})

    stop = asyncio.Event()
    stop.set()  # already stopped -> loop exits after one final flush, no sleep
    asyncio.run(run_drain_loop(sink, stop=stop))

    assert any(s.name == "queued" for s in exporter.get_finished_spans())

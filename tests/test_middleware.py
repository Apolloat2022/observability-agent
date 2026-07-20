"""Phase 1 — middleware.py tests. Drives the raw ASGI callable directly (no
FastAPI/Starlette dependency needed to test it) with a minimal fake app."""
from __future__ import annotations

import asyncio

from obsvagent.middleware import ObservabilityMiddleware, current_trace_id
from obsvagent.otel import OBSV_PARENT_TRACE_ID, OBSV_ROUTE, OBSV_TENANT, OBSV_TRACE_ID, TRACE_ID_RESPONSE_HEADER


class _FakeSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)

    async def drain(self) -> int:
        return 0


async def _downstream_app(scope, receive, send):
    # Observes the trace_id contextvar is bound while the app runs.
    _downstream_app.seen_trace_id = current_trace_id.get()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _run_request(headers: list[tuple[bytes, bytes]], sink):
    mw = ObservabilityMiddleware(_downstream_app, sink=sink, route="riskguard_assessment")
    scope = {"type": "http", "method": "GET", "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    asyncio.run(mw(scope, receive, send))
    return sent


def test_sets_trace_id_response_header():
    sink = _FakeSink()
    sent = _run_request([], sink)
    start = next(m for m in sent if m["type"] == "http.response.start")
    header_names = {k for k, v in start["headers"]}
    assert TRACE_ID_RESPONSE_HEADER.lower().encode() in header_names


def test_emits_one_event_with_route_and_status():
    sink = _FakeSink()
    _run_request([], sink)
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event[OBSV_ROUTE] == "riskguard_assessment"
    assert event["http.status_code"] == 200
    assert event["http.method"] == "GET"
    assert event[OBSV_TRACE_ID]  # non-empty ULID


def test_trace_id_is_bound_during_downstream_call():
    sink = _FakeSink()
    _run_request([], sink)
    assert _downstream_app.seen_trace_id == sink.events[0][OBSV_TRACE_ID]


def test_contextvar_reset_after_request():
    sink = _FakeSink()
    _run_request([], sink)
    assert current_trace_id.get() == ""  # reset to default after the request


def test_tenant_header_extracted():
    sink = _FakeSink()
    _run_request([(b"x-tenant-id", b"acme-corp")], sink)
    assert sink.events[0][OBSV_TENANT] == "acme-corp"


def test_missing_tenant_defaults_to_unknown():
    sink = _FakeSink()
    _run_request([], sink)
    assert sink.events[0][OBSV_TENANT] == "unknown"


def test_traceparent_stashed_as_parent_trace_id():
    sink = _FakeSink()
    traceparent = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    _run_request([(b"traceparent", traceparent)], sink)
    assert sink.events[0][OBSV_PARENT_TRACE_ID] == traceparent.decode()


def test_own_trace_id_is_always_a_fresh_ulid_not_the_traceparent():
    sink = _FakeSink()
    traceparent = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    _run_request([(b"traceparent", traceparent)], sink)
    # ULID is 26 chars; the W3C trace-id segment is 32 hex chars -- must not collide
    assert len(sink.events[0][OBSV_TRACE_ID]) == 26


def test_non_http_scope_passthrough():
    sink = _FakeSink()
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["type"])

    mw = ObservabilityMiddleware(app, sink=sink, route="r")

    async def receive():
        return {}

    async def send(message):
        pass

    asyncio.run(mw({"type": "lifespan"}, receive, send))
    assert calls == ["lifespan"]
    assert sink.events == []  # no telemetry for non-http scopes

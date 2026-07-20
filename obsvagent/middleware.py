"""ASGI middleware — binds trace_id via contextvars, honors inbound W3C
traceparent for cross-service span linking, times the request, emits ONE
event to the sink. Written as a raw ASGI middleware (not Starlette's
BaseHTTPMiddleware, which buffers the whole response body) so streaming
responses pass through untouched and overhead stays minimal.

`obsv.trace_id` is ALWAYS a fresh ULID per request — the ids.py contract
pins that format. An inbound traceparent's W3C trace-id is NOT reused as
obsv.trace_id (different format/length); instead we extract it via OTel's
own propagator so the emitted span nests correctly under the caller's
distributed trace, and stash the raw header as obsv.parent_trace_id for
cross-referencing.
"""
from __future__ import annotations

import contextvars
import time
from typing import Any, Awaitable, Callable, MutableMapping

from opentelemetry import context as otel_context
from opentelemetry.propagate import extract as otel_extract

from .ids import new_ulid
from .interfaces import EventSink
from .otel import (
    OBSV_PARENT_TRACE_ID,
    OBSV_ROUTE,
    OBSV_TENANT,
    OBSV_TRACE_ID,
    TRACE_ID_RESPONSE_HEADER,
    TRACEPARENT_HEADER,
)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Bound for the duration of the request; read by LLMGateway/graph code deeper
# in the call stack so they can tag their own events with the same trace_id
# without threading it through every function signature.
current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("obsv_trace_id", default="")

_TRACEPARENT_BYTES = TRACEPARENT_HEADER.lower().encode()
_TRACE_ID_HEADER_BYTES = TRACE_ID_RESPONSE_HEADER.lower().encode()


def _header_value(headers: list[tuple[bytes, bytes]], name_bytes: bytes) -> str | None:
    for k, v in headers:
        if k == name_bytes:
            return v.decode("latin-1")
    return None


class ObservabilityMiddleware:
    """Raw ASGI middleware.

    Usage (Starlette/FastAPI accept plain ASGI middleware classes):
        app.add_middleware(ObservabilityMiddleware, sink=sink, route="riskguard_assessment")
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        sink: EventSink,
        route: str,
        tenant_header: str = "x-tenant-id",
    ) -> None:
        self.app = app
        self.sink = sink
        self.route = route
        self._tenant_header_bytes = tenant_header.lower().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        trace_id = new_ulid()
        parent_traceparent = _header_value(headers, _TRACEPARENT_BYTES)
        tenant = _header_value(headers, self._tenant_header_bytes) or "unknown"

        # Extract W3C context (if present) so the span we emit nests under the
        # caller's distributed trace in Tempo; falls back to a fresh root
        # context when no valid traceparent was sent.
        carrier = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers}
        parent_ctx = otel_extract(carrier)

        ctx_token = otel_context.attach(parent_ctx)
        trace_token = current_trace_id.set(trace_id)
        start_perf = time.perf_counter()
        start_ns = time.time_ns()
        status_holder = {"status": 0}

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((_TRACE_ID_HEADER_BYTES, trace_id.encode("latin-1")))
                message = dict(message)
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = (time.perf_counter() - start_perf) * 1000
            self.sink.emit(
                {
                    "_span_name": f"{scope.get('method', 'GET')} {self.route}",
                    "_start_ns": start_ns,
                    "_end_ns": time.time_ns(),
                    OBSV_TRACE_ID: trace_id,
                    OBSV_PARENT_TRACE_ID: parent_traceparent,
                    OBSV_ROUTE: self.route,
                    OBSV_TENANT: tenant,
                    "http.method": scope.get("method"),
                    "http.status_code": status_holder["status"],
                    "obsv.latency_ms": round(latency_ms, 3),
                }
            )
            current_trace_id.reset(trace_token)
            otel_context.detach(ctx_token)

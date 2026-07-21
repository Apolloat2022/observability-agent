"""Observability API for the Next.js UI (Phase 7, 🟡 review gate --
authz/tenant scoping). Backs the trace list, the reasoning-path graph, and
the Audit Review Queue.

No raw-payload/PII leakage: no endpoint here ever selects
obsv_payloads.content or any raw prompt/completion text. obsv_events rows
only ever carry metadata (tokens/cost/latency/model/hashes) -- none of
middleware.py / gateway.py / graph.py / checker/node.py put raw request or
completion text into an event's `attributes`, so exposing `attributes`
as-is is safe by construction, not by filtering.

Auth: a minimal shared-secret API key (`X-API-Key` vs `OBSV_API_KEY`). If
`OBSV_API_KEY` is unset, auth is DISABLED -- fine for local dev, NOT for
production; this is a placeholder for real auth (OAuth/JWT) and is exactly
why this file is flagged 🟡 for review. Tenant scoping is enforced by
requiring an `X-Tenant-Id` header on every trace-scoped request and
filtering every query by it.
"""
from __future__ import annotations

import os
from typing import Any, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..db.dao import ReviewQueueDAO
from ..db.env import get_app_database_url

app = FastAPI(title="obsvagent observability API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("OBSV_WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _dsn() -> str:
    dsn = get_app_database_url()
    if not dsn:
        raise HTTPException(status_code=500, detail="OBSV_APP_DATABASE_URL not configured")
    return dsn


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("OBSV_API_KEY")
    if expected is None:
        return  # auth disabled -- dev mode only, see module docstring
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def require_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    return x_tenant_id


_TRACE_COLUMNS = (
    "trace_id, route, tenant, started_at, ended_at, total_cost_usd, "
    "total_tokens_prompt, total_tokens_completion, node_path, flags, checker_verdict"
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/traces")
def list_traces(
    tenant: str = Depends(require_tenant),
    route: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _auth: None = Depends(require_api_key),
) -> list[dict[str, Any]]:
    query = f"SELECT {_TRACE_COLUMNS} FROM obsv.obsv_traces WHERE tenant = %s"
    params: tuple[Any, ...] = (tenant,)
    if route:
        query += " AND route = %s"
        params += (route,)
    query += " ORDER BY updated_at DESC LIMIT %s"
    params += (limit,)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        assert cur.description is not None
        columns = [d.name for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


@app.get("/api/traces/{trace_id}")
def get_trace(
    trace_id: str, tenant: str = Depends(require_tenant), _auth: None = Depends(require_api_key)
) -> dict[str, Any]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_TRACE_COLUMNS} FROM obsv.obsv_traces WHERE trace_id = %s AND tenant = %s",
            (trace_id, tenant),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="trace not found")
        assert cur.description is not None
        columns = [d.name for d in cur.description]
    return dict(zip(columns, row))


@app.get("/api/traces/{trace_id}/events")
def get_trace_events(
    trace_id: str, tenant: str = Depends(require_tenant), _auth: None = Depends(require_api_key)
) -> list[dict[str, Any]]:
    """Feeds the reasoning-path graph: one row per node/HTTP/LLM-call span."""
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, span_name, start_ns, end_ns, latency_ms, attributes
            FROM obsv.obsv_events
            WHERE trace_id = %s AND tenant = %s
            ORDER BY start_ns ASC NULLS LAST, created_at ASC
            """,
            (trace_id, tenant),
        )
        assert cur.description is not None
        columns = [d.name for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


@app.get("/api/review-queue")
def list_review_queue(
    route: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _auth: None = Depends(require_api_key),
) -> list[dict[str, Any]]:
    with psycopg.connect(_dsn()) as conn:
        return ReviewQueueDAO.fetch_pending(conn, route=route, limit=limit)


class DecisionBody(BaseModel):
    decision: Literal["confirmed_hallucination", "false_positive", "fixed_source"]
    actor: str


@app.post("/api/review-queue/{item_id}/decision")
def submit_decision(
    item_id: str, body: DecisionBody, _auth: None = Depends(require_api_key)
) -> dict[str, Any]:
    with psycopg.connect(_dsn()) as conn:
        updated = ReviewQueueDAO.record_decision(conn, item_id, decision=body.decision, actor=body.actor)
    if not updated:
        raise HTTPException(status_code=409, detail="item not found or already reviewed")
    return {"id": item_id, "decision": body.decision, "status": "recorded"}

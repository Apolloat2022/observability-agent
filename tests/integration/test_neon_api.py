"""Phase 7 acceptance criterion (HANDOFF.md): a FAIL verdict appears in the
queue and a reviewer decision persists. Proven end-to-end against the real
Neon instance via the actual FastAPI app (TestClient -> real DB)."""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from obsvagent.checker.node import CheckerNode
from obsvagent.checker.schema import Grounding
from obsvagent.checker.tier1 import Tier1GroundingChecker
from obsvagent.db.review_queue_writer import PostgresAuditQueueWriter


class _FixedJudge:
    def adjudicate(self, *, claim: str, chunks: list[str]) -> tuple[Grounding, str]:
        return Grounding.CONTRADICTED, "test judge: source contradicts the claim"


@pytest.fixture()
def api_client(app_url: str, monkeypatch):
    monkeypatch.setenv("OBSV_APP_DATABASE_URL", app_url)
    monkeypatch.delenv("OBSV_API_KEY", raising=False)  # auth disabled for this test
    from obsvagent.api.main import app

    return TestClient(app)


def test_fail_verdict_appears_in_queue_and_decision_persists(app_url: str, api_client: TestClient):
    tenant = f"phase7-tenant-{uuid.uuid4().hex[:8]}"
    trace_id = f"phase7-trace-{uuid.uuid4().hex[:8]}"
    route = "riskguard_assessment"  # NOT financial -> shadow mode; CONTRADICTED still hard-blocks

    # 1. Produce a real FAIL verdict through the actual Checker pipeline.
    writer = PostgresAuditQueueWriter(app_url, tenant=tenant)
    node = CheckerNode(tier1=Tier1GroundingChecker(), judge=_FixedJudge(), audit_writer=writer)
    result = node.check(
        trace_id=trace_id,
        route=route,
        answer="The vendor confirmed the shipment will arrive within two business days [1].",
        retrieved={1: "The vendor stated the shipment has been delayed indefinitely and will not arrive."},
    )
    assert result.verdict.verdict.value == "FAIL"
    assert result.audit_written is True

    # 2. Confirm it's queryable via /api/review-queue (unauthenticated in this test).
    resp = api_client.get("/api/review-queue", params={"route": route, "limit": 200})
    assert resp.status_code == 200
    items = resp.json()
    ours = [i for i in items if i["trace_id"] == trace_id]
    assert len(ours) == 1
    item = ours[0]
    assert item["verdict"] == "FAIL"
    # fetch_pending only ever returns rows with reviewer_decision IS NULL
    # (enforced by its WHERE clause) and deliberately doesn't select that
    # always-null column for pending items -- nothing to assert on it here.
    assert any(c["grounding"] == "CONTRADICTED" for c in item["claims"])

    # 3. Submit a reviewer decision and confirm it persists.
    decision_resp = api_client.post(
        f"/api/review-queue/{item['id']}/decision",
        json={"decision": "confirmed_hallucination", "actor": "reviewer@example.com"},
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["status"] == "recorded"

    with psycopg.connect(app_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT reviewer_decision, reviewer_actor, reviewed_at FROM obsv.obsv_review_queue WHERE id = %s",
            (item["id"],),
        )
        decision, actor, reviewed_at = cur.fetchone()
    assert decision == "confirmed_hallucination"
    assert actor == "reviewer@example.com"
    assert reviewed_at is not None

    # 4. It no longer shows up as pending, and double-submit is rejected.
    resp2 = api_client.get("/api/review-queue", params={"route": route, "limit": 200})
    assert item["id"] not in [i["id"] for i in resp2.json()]

    dup_resp = api_client.post(
        f"/api/review-queue/{item['id']}/decision",
        json={"decision": "false_positive", "actor": "someone-else@example.com"},
    )
    assert dup_resp.status_code == 409


def test_health_endpoint(api_client: TestClient):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tenant_required_for_traces(api_client: TestClient):
    resp = api_client.get("/api/traces")
    assert resp.status_code == 400  # X-Tenant-Id missing


def test_auth_enforced_when_api_key_configured(app_url: str, monkeypatch):
    monkeypatch.setenv("OBSV_APP_DATABASE_URL", app_url)
    monkeypatch.setenv("OBSV_API_KEY", "secret123")
    from obsvagent.api.main import app

    client = TestClient(app)
    try:
        resp = client.get("/api/review-queue")
        assert resp.status_code == 401
        resp_ok = client.get("/api/review-queue", headers={"X-API-Key": "secret123"})
        assert resp_ok.status_code == 200
    finally:
        os.environ.pop("OBSV_API_KEY", None)

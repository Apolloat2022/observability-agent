"""Phase 2 — DAO round-trip tests against the real Neon instance."""
from __future__ import annotations

import uuid

import psycopg

from obsvagent.db.dao import AuditDAO, PayloadDAO, TraceDAO
from obsvagent.ledger import GENESIS_CHAIN_HASH, AuditRecord, seal, verify_chain
from obsvagent.schema import new_telemetry


def test_trace_upsert_round_trip(app_url: str):
    tel = new_telemetry(route="riskguard_assessment", tenant="dao-test")
    tel["node_path"] = ["ingest", "assess"]
    tel["cost_usd"] = 0.042
    tel["token_usage"] = {"prompt": 100, "completion": 50}

    with psycopg.connect(app_url) as conn:
        TraceDAO.upsert_from_telemetry(conn, tel)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT total_cost_usd, total_tokens_prompt, node_path FROM obsv.obsv_traces WHERE trace_id = %s",
                (tel["trace_id"],),
            )
            row = cur.fetchone()
    assert row[0] == 0.042
    assert row[1] == 100
    assert list(row[2]) == ["ingest", "assess"]


def test_trace_upsert_is_idempotent_and_updates_in_place(app_url: str):
    tel = new_telemetry(route="r", tenant="dao-test")
    with psycopg.connect(app_url) as conn:
        TraceDAO.upsert_from_telemetry(conn, tel)
        tel["cost_usd"] = 1.0
        TraceDAO.upsert_from_telemetry(conn, tel)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), max(total_cost_usd) FROM obsv.obsv_traces WHERE trace_id = %s", (tel["trace_id"],))
            count, cost = cur.fetchone()
    assert count == 1  # upsert, not a duplicate row
    assert cost == 1.0


def test_payload_insert_and_tombstone(app_url: str, retention_url: str):
    payload_id = f"payload-{uuid.uuid4().hex[:12]}"
    with psycopg.connect(app_url) as conn:
        PayloadDAO.insert(
            conn, payload_id=payload_id, trace_id="T-payload", kind="completion",
            content="the raw completion text", content_hash="abc123",
        )

    with psycopg.connect(retention_url) as conn:
        PayloadDAO.tombstone(conn, payload_id)

    with psycopg.connect(app_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content, content_hash, tombstoned_at FROM obsv.obsv_payloads WHERE id = %s", (payload_id,))
            content, content_hash, tombstoned_at = cur.fetchone()
    assert content is None  # raw text purged
    assert content_hash == "abc123"  # hash retained -- provable without raw text
    assert tombstoned_at is not None


def test_audit_insert_and_verify_chain_round_trip(app_url: str):
    # audit_id is the PK with no run-scoping in the schema (by design -- real
    # audit ids are monotonic ULIDs, globally unique) -- use a fresh uuid
    # suffix each run so repeated test runs don't collide on a stale row.
    run_id = uuid.uuid4().hex[:8]
    project = f"dao-test-{run_id}"

    def rec(audit_id: str, trace_id: str) -> AuditRecord:
        return AuditRecord(
            audit_id=audit_id, trace_id=trace_id, project=project, route="riskguard_assessment",
            actor="dao-test", timestamp="2026-07-20T00:00:00+00:00",
            request_hash="rh", request_ptr="rp", context_hashes=["c1", "c2"], context_scores=[0.9, 0.8],
            model="claude-opus-4-8", model_version="build-1", prompt_template_version="v1",
            parameters={"temperature": 0}, completion_hash="ch", completion_ptr="cp",
            checker_verdict="PASS", final_decision="report",
        )

    r1 = seal(rec(f"dao-audit-{run_id}-01", "T1"), GENESIS_CHAIN_HASH)
    r2 = seal(rec(f"dao-audit-{run_id}-02", "T2"), r1.chain_hash)

    with psycopg.connect(app_url) as conn:
        AuditDAO.insert(conn, r1)
        AuditDAO.insert(conn, r2)
        fetched = AuditDAO.fetch_ordered(conn, project)

    assert [r.audit_id for r in fetched] == [f"dao-audit-{run_id}-01", f"dao-audit-{run_id}-02"]
    result = verify_chain(fetched)
    assert result.ok is True
    assert result.checked == 2

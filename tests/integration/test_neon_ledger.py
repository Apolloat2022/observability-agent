"""Phase 5 acceptance criterion (HANDOFF.md): tamper test -- mutating any
historical row is caught by verify-ledger. Proven against the real Neon
instance: append a real chain, tamper a historical row as the owner
(obsv_app itself cannot -- proven in test_neon_grants.py), and confirm both
ledger.verify_chain() and the verify-ledger CLI catch it."""
from __future__ import annotations

import threading
import uuid

import psycopg

from obsvagent.cli.verify_ledger import main as verify_ledger_main
from obsvagent.db.dao import AuditDAO
from obsvagent.ledger import AuditRecord, verify_chain
from obsvagent.ledger_writer import PostgresLedgerWriter


def _record(project: str, trace_id: str) -> AuditRecord:
    return AuditRecord(
        audit_id="placeholder", trace_id=trace_id, project=project, route="treasury_orchestrator",
        actor="ledger-test", timestamp="2026-07-20T00:00:00+00:00",
        request_hash="rh", request_ptr="rp", context_hashes=["c1"], context_scores=[0.9],
        model="claude-opus-4-8", model_version="build-1", prompt_template_version="v1",
        parameters={"temperature": 0}, completion_hash="ch", completion_ptr="cp",
        checker_verdict="PASS", final_decision="execute",
    )


def test_sequential_appends_chain_correctly(app_url: str):
    project = f"ledger-seq-{uuid.uuid4().hex[:8]}"
    writer = PostgresLedgerWriter(app_url)

    r1 = writer.append(_record(project, "T1"))
    r2 = writer.append(_record(project, "T2"))
    r3 = writer.append(_record(project, "T3"))

    assert r2.prev_chain_hash == r1.chain_hash
    assert r3.prev_chain_hash == r2.chain_hash
    assert writer.head_chain_hash(project) == r3.chain_hash

    with psycopg.connect(app_url) as conn:
        records = AuditDAO.fetch_ordered(conn, project)
    result = verify_chain(records)
    assert result.ok is True
    assert result.checked == 3


def test_concurrent_appends_stay_ordered_no_fork(app_url: str):
    """Proves the pg_advisory_xact_lock actually serializes concurrent
    writers across separate connections/threads -- a Python-level lock
    would NOT catch a bug here since each thread opens its own connection."""
    project = f"ledger-concurrent-{uuid.uuid4().hex[:8]}"
    writer = PostgresLedgerWriter(app_url)
    n = 12
    errors: list[Exception] = []

    def append_one(i: int) -> None:
        try:
            writer.append(_record(project, f"T{i}"))
        except Exception as exc:  # noqa: BLE001 -- collected for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=append_one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with psycopg.connect(app_url) as conn:
        records = AuditDAO.fetch_ordered(conn, project)
    assert len(records) == n
    result = verify_chain(records)
    assert result.ok is True, f"chain forked under concurrent writers: {result.reason}"
    assert result.checked == n


def test_tamper_detected_by_verify_chain_and_cli(app_url: str, owner_url: str):
    project = f"ledger-tamper-{uuid.uuid4().hex[:8]}"
    writer = PostgresLedgerWriter(app_url)
    r1 = writer.append(_record(project, "T1"))
    writer.append(_record(project, "T2"))
    writer.append(_record(project, "T3"))

    with psycopg.connect(app_url) as conn:
        clean_result = verify_chain(AuditDAO.fetch_ordered(conn, project))
    assert clean_result.ok is True

    # Tamper a HISTORICAL row directly as the owner -- obsv_app itself
    # cannot (see test_neon_grants.py); this simulates a compromised
    # superuser/DBA-level actor, the actual threat the hash chain defends
    # against (an app-level bug or exploit is already stopped by the grant).
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE obsv.obsv_audit SET final_decision = 'tampered-reject' WHERE audit_id = %s",
                (r1.audit_id,),
            )
        conn.commit()

    with psycopg.connect(app_url) as conn:
        tampered_records = AuditDAO.fetch_ordered(conn, project)
    tampered_result = verify_chain(tampered_records)
    assert tampered_result.ok is False
    assert tampered_result.first_broken_id == r1.audit_id
    assert "payload_hash mismatch" in tampered_result.reason

    exit_code = verify_ledger_main(["--project", project, "--database-url", app_url])
    assert exit_code == 1

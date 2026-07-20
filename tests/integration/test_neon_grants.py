"""Phase 2 acceptance criterion (HANDOFF.md): app role cannot UPDATE/DELETE
obsv_audit. Proven against the REAL Neon instance, not a mock -- Postgres
checks statement-level privileges before evaluating WHERE, so this fails
with InsufficientPrivilege even against zero matching rows."""
from __future__ import annotations

import psycopg
import pytest


def test_obsv_app_cannot_update_obsv_audit(app_url: str):
    with psycopg.connect(app_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("UPDATE obsv.obsv_audit SET final_decision = 'tampered' WHERE true")
        conn.rollback()


def test_obsv_app_cannot_delete_obsv_audit(app_url: str):
    with psycopg.connect(app_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM obsv.obsv_audit WHERE true")
        conn.rollback()


def test_obsv_app_cannot_truncate_obsv_audit(app_url: str):
    with psycopg.connect(app_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("TRUNCATE obsv.obsv_audit")
        conn.rollback()


def test_obsv_app_can_insert_and_select_obsv_audit(app_url: str):
    """The grant is scoped, not absolute -- INSERT/SELECT must still work."""
    with psycopg.connect(app_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obsv.obsv_audit (
                    audit_id, trace_id, project, route, actor, logical_timestamp,
                    request_hash, request_ptr, context_hashes, context_scores,
                    model, model_version, prompt_template_version, parameters,
                    completion_hash, completion_ptr, checker_verdict, final_decision,
                    payload_hash, prev_chain_hash, chain_hash
                ) VALUES (
                    %s, 'T1', 'grant-test-project', 'riskguard_assessment', 'tester', now(),
                    'rh', 'rp', ARRAY['c1'], ARRAY[0.9]::float8[],
                    'claude-opus-4-8', 'build-1', 'v1', '{}'::jsonb,
                    'ch', 'cp', 'PASS', 'report',
                    'ph', %s, 'chain1'
                )
                ON CONFLICT (audit_id) DO NOTHING
                """,
                ("grant-test-audit-1", "0" * 64),
            )
            conn.commit()
            cur.execute("SELECT final_decision FROM obsv.obsv_audit WHERE audit_id = %s", ("grant-test-audit-1",))
            assert cur.fetchone() == ("report",)


def test_obsv_retention_has_no_access_to_obsv_audit(retention_url: str):
    with psycopg.connect(retention_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM obsv.obsv_audit LIMIT 1")
        conn.rollback()

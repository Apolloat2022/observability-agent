"""Phase 5 — ledger_writer.py offline tests: fail-closed behavior on
connection failure. Live sequencing/concurrency/tamper-detection tests are
in tests/integration/test_neon_ledger.py (need a real Postgres)."""
from __future__ import annotations

import pytest

from obsvagent.ledger import AuditRecord
from obsvagent.ledger_writer import LedgerAppendError, PostgresLedgerWriter

# Port 1 has no listener on virtually any machine -> fast "connection
# refused" rather than a slow timeout, keeping this test in the offline suite.
_BAD_DSN = "postgresql://invalid:invalid@127.0.0.1:1/db?connect_timeout=1"


def _record(project: str = "test-project") -> AuditRecord:
    return AuditRecord(
        audit_id="placeholder", trace_id="T1", project=project, route="riskguard_assessment",
        actor="tester", timestamp="2026-07-20T00:00:00+00:00",
        request_hash="rh", request_ptr="rp", context_hashes=["c1"], context_scores=[0.9],
        model="claude-opus-4-8", model_version="build-1", prompt_template_version="v1",
        parameters={}, completion_hash="ch", completion_ptr="cp",
        checker_verdict="PASS", final_decision="report",
    )


def test_append_fails_closed_on_unreachable_db():
    writer = PostgresLedgerWriter(_BAD_DSN)
    with pytest.raises(LedgerAppendError):
        writer.append(_record())


def test_head_chain_hash_fails_closed_on_unreachable_db():
    writer = PostgresLedgerWriter(_BAD_DSN)
    with pytest.raises(LedgerAppendError):
        writer.head_chain_hash("test-project")

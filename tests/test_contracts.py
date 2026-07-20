"""Contract smoke tests (Opus-authored). These lock the behavior Sonnet builds
against — they must stay green. Run: pytest -q"""
from __future__ import annotations

from obsvagent.alerting.model import SIGNALS_BY_KEY, Severity, is_financial
from obsvagent.checker.schema import (
    Action,
    ClaimVerdict,
    Grounding,
    Thresholds,
    decide_claim,
    needs_judge,
    roll_up,
)
from obsvagent.ids import new_ulid, ulid_time_ms
from obsvagent.ledger import AuditRecord, GENESIS_CHAIN_HASH, seal, verify_chain
from obsvagent.monitoring.workflows import TREASURY_ORCHESTRATOR, check_conformance
from obsvagent.schema import telemetry_reducer


def test_reducer_merges_branches_without_clobbering():
    base = {"trace_id": "A", "node_path": ["intake"], "cost_usd": 0.1,
            "token_usage": {"prompt": 10}, "flags": ["x"]}
    branch1 = {"trace_id": "B", "node_path": ["risk_check"], "cost_usd": 0.2,
               "token_usage": {"prompt": 5, "completion": 3}, "flags": ["x", "y"]}
    out = telemetry_reducer(base, branch1)
    assert out["trace_id"] == "A"                       # set-once: first wins
    assert out["node_path"] == ["intake", "risk_check"]  # append
    assert abs(out["cost_usd"] - 0.3) < 1e-9             # sum
    assert out["token_usage"] == {"prompt": 15, "completion": 3}
    assert out["flags"] == ["x", "y"]                    # append + dedupe


def test_ulid_is_time_sortable():
    a = new_ulid(1000)
    b = new_ulid(2000)
    assert a < b
    assert ulid_time_ms(a) == 1000


def test_needs_judge_only_in_ambiguous_band():
    t = Thresholds()
    assert needs_judge(0.5, t) is True
    assert needs_judge(0.9, t) is False   # Tier-1 resolves high
    assert needs_judge(0.1, t) is False   # Tier-1 resolves low


def test_contradiction_blocks_and_rolls_up_to_fail():
    t = Thresholds()
    claims = [
        ClaimVerdict("ok", [1], Grounding.SUPPORTED, 0.9, 1),
        ClaimVerdict("bad", [2], Grounding.CONTRADICTED, 0.2, 2),
    ]
    for c in claims:
        c.action = decide_claim(c.grounding, t)
    assert claims[1].action is Action.BLOCK
    assert roll_up("T", claims, t).verdict.value == "FAIL"


def test_conformance_catches_execute_without_risk_check():
    # skips risk_check + approval -> must be flagged
    illegal = ["intake", "treasury_route", "execute"]
    res = check_conformance(TREASURY_ORCHESTRATOR, illegal)
    assert res.ok is False
    assert any("required predecessor" in v for v in res.violations)


def test_ledger_detects_tampering():
    def rec(i: str, tr: str) -> AuditRecord:
        return AuditRecord(
            audit_id=i, trace_id=tr, project="stablecoin", route="treasury_orchestrator",
            actor="u1", timestamp="2026-07-20T00:00:00Z", request_hash="rh", request_ptr="p",
            context_hashes=["c1"], context_scores=[0.9], model="claude-opus-4-8",
            model_version="build-1", prompt_template_version="v1", parameters={"temperature": 0},
            completion_hash="ch", completion_ptr="p2", checker_verdict="PASS",
            final_decision="execute",
        )
    r1 = seal(rec("01", "A"), GENESIS_CHAIN_HASH)
    r2 = seal(rec("02", "B"), r1.chain_hash)
    assert verify_chain([r1, r2]).ok is True
    r1.final_decision = "reject"   # retroactive edit
    v = verify_chain([r1, r2])
    assert v.ok is False and v.first_broken_id == "01"


def test_alert_taxonomy_pages_on_grounding_and_logic():
    assert SIGNALS_BY_KEY["grounding_rate_drop"].severity is Severity.CRITICAL
    assert SIGNALS_BY_KEY["enterprise_logic_deviation"].severity is Severity.CRITICAL
    assert is_financial("treasury_orchestrator") is True

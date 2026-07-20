"""Phase 4 acceptance criterion (HANDOFF.md): an injected loop AND an
injected illegal transition must both be caught and audited (i.e. end up in
_telemetry.flags, the same vocabulary the ledger/alerting subsystems read)."""
from __future__ import annotations

import time

from obsvagent.monitoring.guard import (
    GuardContext,
    GuardLimits,
    GuardViolation,
    NodeCycleTracker,
    check_cost_budget,
    check_cycle,
    check_enterprise_logic,
    check_step_budget,
    check_wall_clock,
    enforce,
    evaluate,
)
from obsvagent.monitoring.workflows import TREASURY_ORCHESTRATOR
from obsvagent.schema import Flag, new_telemetry, telemetry_reducer


def test_step_budget_clean_and_violated():
    limits = GuardLimits(max_steps=5)
    assert check_step_budget(["a", "b", "c"], limits).ok is True
    result = check_step_budget(["a", "b", "c", "d", "e", "f"], limits)
    assert result.ok is False
    assert result.flag == Flag.STEP_BUDGET_EXCEEDED


def test_wall_clock_violated():
    limits = GuardLimits(max_wall_clock_s=60.0)
    started = time.time() - 120  # 2 minutes ago
    result = check_wall_clock(started, limits)
    assert result.ok is False
    assert result.flag == Flag.STEP_BUDGET_EXCEEDED
    assert "wall clock" in result.reason


def test_cost_budget_violated():
    limits = GuardLimits(max_cost_usd=1.0)
    result = check_cost_budget(2.5, limits)
    assert result.ok is False
    assert result.flag == Flag.COST_BUDGET_EXCEEDED


def test_cycle_detection_catches_injected_loop():
    """Scenario 1: an agent stuck re-entering the same node with identical
    domain state -- the dead-loop case from blueprint §3.2."""
    tracker = NodeCycleTracker()
    limits = GuardLimits(max_identical_state_repeats=3)
    same_state_hash = "deadbeef0000"

    results = [check_cycle(tracker, "retrieve", same_state_hash, limits) for _ in range(5)]
    assert [r.ok for r in results] == [True, True, True, False, False]
    assert results[3].flag == Flag.LOOP_SUSPECTED


def test_injected_loop_flows_into_telemetry_flags():
    """The loop is not just detected -- it is AUDITED: the flag ends up in
    the run's accumulated _telemetry.flags via the same reducer every other
    subsystem uses."""
    tel = new_telemetry(route="riskguard_assessment", tenant="t1")
    ctx = GuardContext(
        node_path=["ingest", "retrieve", "assess", "retrieve", "assess", "retrieve"],
        started_at=time.time(),
        cost_usd=0.0,
        tracker=NodeCycleTracker(),
        limits=GuardLimits(max_identical_state_repeats=1),
    )
    domain_state = {"query": "same query every time"}

    triggered_flags: list[str] = []
    for _ in range(4):  # simulate 4 identical-state visits to the same node
        violations = evaluate(ctx, node="retrieve", domain_state=domain_state)
        for v in violations:
            assert v.flag is not None
            triggered_flags.append(v.flag)

    assert Flag.LOOP_SUSPECTED in triggered_flags
    audited = telemetry_reducer(tel, {"flags": triggered_flags})
    assert Flag.LOOP_SUSPECTED in audited["flags"]


def test_enterprise_logic_catches_injected_illegal_transition():
    """Scenario 2: execute reached without risk_check/approval -- the
    enterprise-logic-deviation case from blueprint §3.2, using the real
    TREASURY_ORCHESTRATOR spec (frozen, Opus-owned)."""
    illegal_path = ["intake", "treasury_route", "execute"]  # skips risk_check + approval
    result = check_enterprise_logic(TREASURY_ORCHESTRATOR, illegal_path)
    assert result.ok is False
    assert result.flag == Flag.ENTERPRISE_LOGIC_DEVIATION


def test_injected_illegal_transition_flows_into_telemetry_flags():
    tel = new_telemetry(route="treasury_orchestrator", tenant="stablecoin")
    ctx = GuardContext(
        node_path=["intake", "treasury_route", "execute"],
        started_at=time.time(),
        cost_usd=0.0,
        tracker=NodeCycleTracker(),
        spec=TREASURY_ORCHESTRATOR,
    )
    violations = evaluate(ctx, node="execute", domain_state={})
    flags = [v.flag for v in violations if v.flag is not None]
    assert Flag.ENTERPRISE_LOGIC_DEVIATION in flags

    audited = telemetry_reducer(tel, {"flags": flags})
    assert Flag.ENTERPRISE_LOGIC_DEVIATION in audited["flags"]


def test_legal_treasury_path_is_clean():
    ctx = GuardContext(
        node_path=["intake", "treasury_route", "risk_check", "approval", "execute"],
        started_at=time.time(),
        cost_usd=0.1,
        tracker=NodeCycleTracker(),
        spec=TREASURY_ORCHESTRATOR,
    )
    assert evaluate(ctx, node="execute", domain_state={}) == []


def test_enforce_raises_on_first_violation():
    ctx = GuardContext(
        node_path=["a"] * 999,
        started_at=time.time(),
        cost_usd=0.0,
        tracker=NodeCycleTracker(),
        limits=GuardLimits(max_steps=5),
    )
    try:
        enforce(ctx, node="a", domain_state={})
        assert False, "expected GuardViolation"
    except GuardViolation as exc:
        assert exc.flag == Flag.STEP_BUDGET_EXCEEDED

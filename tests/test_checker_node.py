"""Phase 3 — node.py tests. Verifies HANDOFF decision 4: financial routes
inline (block on any FAIL), shadow routes ship-except-hard-block."""
from __future__ import annotations

from obsvagent.checker.node import CheckerNode, mode_for_route
from obsvagent.checker.schema import Grounding, Verdict
from obsvagent.checker.tier1 import Tier1GroundingChecker


class _FixedJudge:
    """Test double: always returns the same verdict, regardless of input."""

    def __init__(self, grounding: Grounding, rationale: str = "test") -> None:
        self._grounding = grounding
        self._rationale = rationale
        self.calls = 0

    def adjudicate(self, *, claim: str, chunks: list[str]) -> tuple[Grounding, str]:
        self.calls += 1
        return self._grounding, self._rationale


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write(self, *, trace_id: str, route: str, verdict) -> None:
        self.writes.append({"trace_id": trace_id, "route": route, "verdict": verdict})


def test_mode_for_route_financial_is_inline():
    assert mode_for_route("treasury_orchestrator").inline is True
    assert mode_for_route("riskguard_assessment").inline is True
    assert mode_for_route("rag_showcase_chat").inline is False


def test_clean_pass_ships_no_audit_write():
    node = CheckerNode(
        tier1=Tier1GroundingChecker(), judge=_FixedJudge(Grounding.SUPPORTED), audit_writer=_FakeAuditWriter()
    )
    result = node.check(
        trace_id="T1", route="rag_showcase_chat", answer="The sky is blue [1].",
        retrieved={1: "The sky is blue on a clear day."},
    )
    assert result.verdict.verdict is Verdict.PASS
    assert result.blocked is False
    assert result.audit_written is False


def test_financial_route_blocks_on_ratio_fail_shadow_would_not():
    audit = _FakeAuditWriter()
    node = CheckerNode(tier1=Tier1GroundingChecker(), judge=_FixedJudge(Grounding.UNSUPPORTED), audit_writer=audit)
    # Ambiguous-band claim escalates -> scripted judge returns UNSUPPORTED for
    # every escalated claim -> ratio exceeds threshold -> FAIL, no hard-block class.
    kwargs = dict(
        answer="The vendor confirmed the shipment will arrive within two business days [1].",
        retrieved={1: "The vendor stated the shipment has been delayed indefinitely and will not arrive."},
    )
    financial = node.check(trace_id="T1", route="treasury_orchestrator", **kwargs)
    assert financial.verdict.verdict is Verdict.FAIL
    assert financial.blocked is True  # inline route blocks on ANY FAIL

    shadow_node = CheckerNode(tier1=Tier1GroundingChecker(), judge=_FixedJudge(Grounding.UNSUPPORTED), audit_writer=audit)
    shadow = shadow_node.check(trace_id="T2", route="rag_showcase_chat", **kwargs)
    assert shadow.verdict.verdict is Verdict.FAIL
    assert shadow.blocked is False  # shadow route ships ratio-only FAILs, just queues them
    assert shadow.audit_written is True


def test_contradicted_hard_blocks_even_on_shadow_route():
    audit = _FakeAuditWriter()
    node = CheckerNode(tier1=Tier1GroundingChecker(), judge=_FixedJudge(Grounding.CONTRADICTED), audit_writer=audit)
    result = node.check(
        trace_id="T3", route="rag_showcase_chat",  # NOT a financial route
        answer="The vendor confirmed the shipment will arrive within two business days [1].",
        retrieved={1: "The vendor stated the shipment has been delayed indefinitely and will not arrive."},
    )
    assert result.blocked is True  # CONTRADICTED short-circuits regardless of mode
    assert result.audit_written is True


def test_fabricated_citation_hard_blocks_on_shadow_route():
    audit = _FakeAuditWriter()
    node = CheckerNode(tier1=Tier1GroundingChecker(), judge=_FixedJudge(Grounding.SUPPORTED), audit_writer=audit)
    result = node.check(
        trace_id="T4", route="rag_showcase_chat",
        answer="Revenue grew 12% [9].", retrieved={1: "Revenue grew 12% per the filing."},
    )
    assert result.blocked is True
    assert audit.writes[0]["route"] == "rag_showcase_chat"


def test_only_ambiguous_claims_are_escalated_to_judge():
    judge = _FixedJudge(Grounding.SUPPORTED)
    node = CheckerNode(tier1=Tier1GroundingChecker(), judge=judge, audit_writer=_FakeAuditWriter())
    node.check(
        trace_id="T5", route="rag_showcase_chat",
        answer="The treasury holds 3 million USDC in reserve [1].",  # clean high-overlap -> no escalation
        retrieved={1: "The treasury holds 3 million USDC in reserve, verified by the auditor."},
    )
    assert judge.calls == 0

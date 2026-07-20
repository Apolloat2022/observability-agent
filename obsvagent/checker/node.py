"""Checker node — wires Tier-1 + Tier-2 into one verdict per HANDOFF decision 4
(Phase 3, 🟢): financial routes run inline (fail-closed, block on ANY FAIL);
every other route runs shadow (ship immediately, queue for review) EXCEPT
that CONTRADICTED and FABRICATED_CITATION claims still short-circuit to a
synchronous block on shadow routes too — those two are cheap to detect
(usually resolved by Tier-1 alone) and are never acceptable to ship
regardless of route.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..alerting.model import FINANCIAL_ROUTES
from ..interfaces import GroundingChecker, Judge, assemble_verdict
from .schema import CheckerVerdict, ClaimVerdict, Grounding, Thresholds, Verdict

_HARD_BLOCK_GROUNDINGS = (Grounding.CONTRADICTED, Grounding.FABRICATED_CITATION)


class AuditQueueWriter(Protocol):
    """Phase 7 implements the real (DB-backed) writer; tests use a fake."""

    def write(self, *, trace_id: str, route: str, verdict: CheckerVerdict) -> None: ...


@dataclass(frozen=True)
class CheckMode:
    inline: bool  # True: block synchronously on ANY FAIL verdict


def mode_for_route(route: str) -> CheckMode:
    return CheckMode(inline=route in FINANCIAL_ROUTES)


@dataclass
class CheckerResult:
    verdict: CheckerVerdict
    blocked: bool  # True: caller MUST NOT ship the response as-is
    audit_written: bool


class CheckerNode:
    def __init__(
        self,
        *,
        tier1: GroundingChecker,
        judge: Judge,
        audit_writer: AuditQueueWriter,
        thresholds: Thresholds | None = None,
    ) -> None:
        self._tier1 = tier1
        self._judge = judge
        self._audit_writer = audit_writer
        self._thresholds = thresholds or Thresholds()

    def _resolve_escalations(self, claims: list[ClaimVerdict], retrieved: dict[int, str]) -> None:
        """Tier-1 leaves ambiguous-band claims at Grounding.PARTIAL, tier=1.
        Resolve exactly those via the Tier-2 judge, in place."""
        for claim in claims:
            if claim.grounding is Grounding.PARTIAL and claim.tier == 1:
                chunks = [retrieved[c] for c in claim.cited if c in retrieved]
                resolved, rationale = self._judge.adjudicate(claim=claim.text, chunks=chunks)
                claim.grounding = resolved
                claim.rationale = rationale
                claim.tier = 2

    def check(
        self, *, trace_id: str, route: str, answer: str, retrieved: dict[int, str]
    ) -> CheckerResult:
        claims = self._tier1.check(answer=answer, retrieved=retrieved, thresholds=self._thresholds)
        self._resolve_escalations(claims, retrieved)

        verdict = assemble_verdict(trace_id, claims, self._thresholds)

        mode = mode_for_route(route)
        hard_block = any(c.grounding in _HARD_BLOCK_GROUNDINGS for c in claims)
        blocked = hard_block or (mode.inline and verdict.verdict is Verdict.FAIL)

        audit_written = False
        if verdict.verdict is not Verdict.PASS:
            self._audit_writer.write(trace_id=trace_id, route=route, verdict=verdict)
            audit_written = True

        return CheckerResult(verdict=verdict, blocked=blocked, audit_written=audit_written)

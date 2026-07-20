"""Checker verdict schema + threshold/escalation logic (Opus-owned).

This file defines WHAT a hallucination verdict is and WHEN a claim escalates
or blocks. The deterministic Tier-1 grounding check, the Tier-2 LLM judge, and
the audit-item writer (all Sonnet) consume these types and call `decide_claim`
/ `roll_up`. Sonnet must not re-invent thresholds inline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Grounding(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"          # answer conflicts with cited source
    MISSING_CITATION = "MISSING_CITATION"  # factual claim with no citation
    FABRICATED_CITATION = "FABRICATED_CITATION"  # cites a chunk id never retrieved


class Action(str, Enum):
    PASS = "pass"
    FLAG = "flag"        # file an audit item, do not block
    BLOCK = "block"      # hold/abstain the whole response (inline mode)


class Verdict(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"    # shipped but queued for human review
    FAIL = "FAIL"        # blocked (inline) or CRITICAL audit item (shadow)


@dataclass(frozen=True)
class Thresholds:
    """Per-route tunable. Reviewer decisions (§2.4) feed back to adjust these.

    tau_high / tau_low bound the Tier-1 similarity score:
        score >= tau_high            -> provisional SUPPORTED, no judge call
        score <  tau_low             -> provisional UNSUPPORTED, no judge call
        tau_low <= score < tau_high  -> ESCALATE to Tier-2 judge
    """
    tau_high: float = 0.75
    tau_low: float = 0.35
    # If unsupported+contradicted claims exceed this fraction, fail the response.
    unsupported_ratio_block: float = 0.20
    # Any single contradiction/fabrication is enough to block regardless of ratio.
    block_on_any_contradiction: bool = True
    block_on_any_fabricated_citation: bool = True


@dataclass
class ClaimVerdict:
    text: str
    cited: list[int]                 # chunk ids the claim cites (may be empty)
    grounding: Grounding
    score: float                     # Tier-1 similarity (0 if n/a)
    tier: int                        # 1 = deterministic only, 2 = judge was called
    rationale: str = ""              # judge span/explanation, for the reviewer
    action: Action = Action.PASS


@dataclass
class CheckerVerdict:
    trace_id: str
    verdict: Verdict
    claims: list[ClaimVerdict] = field(default_factory=list)
    unsupported_ratio: float = 0.0
    grounding_certificate: str | None = None  # hash of claims+verdicts when PASS

    @property
    def flags(self) -> list[str]:
        """Telemetry flags implied by this verdict (feed into schema.Flag)."""
        out: set[str] = set()
        for c in self.claims:
            if c.grounding is Grounding.UNSUPPORTED:
                out.add("unsupported_claim")
            elif c.grounding is Grounding.CONTRADICTED:
                out.add("contradicted_claim")
            elif c.grounding is Grounding.MISSING_CITATION:
                out.add("missing_citation")
            elif c.grounding is Grounding.FABRICATED_CITATION:
                out.add("fabricated_citation")
        return sorted(out)


# --- decision logic -------------------------------------------------------

_NEEDS_ESCALATION = object()


def needs_judge(score: float, t: Thresholds) -> bool:
    """True when Tier-1 is inconclusive and the Tier-2 judge should run.
    Keeps the expensive judge off the ~80-90% of claims Tier-1 resolves."""
    return t.tau_low <= score < t.tau_high


def decide_claim(grounding: Grounding, t: Thresholds) -> Action:
    """Map a resolved per-claim grounding to an action."""
    if grounding in (Grounding.SUPPORTED,):
        return Action.PASS
    if grounding is Grounding.CONTRADICTED and t.block_on_any_contradiction:
        return Action.BLOCK
    if grounding is Grounding.FABRICATED_CITATION and t.block_on_any_fabricated_citation:
        return Action.BLOCK
    # UNSUPPORTED / PARTIAL / MISSING_CITATION -> flag; ratio decides the rollup.
    return Action.FLAG


def roll_up(trace_id: str, claims: list[ClaimVerdict], t: Thresholds) -> CheckerVerdict:
    """Combine per-claim verdicts into the response-level verdict.

    - any BLOCK action                -> FAIL
    - unsupported_ratio over threshold -> FAIL
    - any FLAG                        -> REVIEW
    - otherwise                       -> PASS
    """
    factual = [c for c in claims if c.grounding is not Grounding.SUPPORTED or c.cited]
    bad = [c for c in claims if c.grounding in (Grounding.UNSUPPORTED, Grounding.CONTRADICTED)]
    ratio = (len(bad) / len(factual)) if factual else 0.0

    has_block = any(c.action is Action.BLOCK for c in claims)
    has_flag = any(c.action is Action.FLAG for c in claims)

    if has_block or ratio > t.unsupported_ratio_block:
        verdict = Verdict.FAIL
    elif has_flag:
        verdict = Verdict.REVIEW
    else:
        verdict = Verdict.PASS

    return CheckerVerdict(
        trace_id=trace_id,
        verdict=verdict,
        claims=claims,
        unsupported_ratio=round(ratio, 4),
    )

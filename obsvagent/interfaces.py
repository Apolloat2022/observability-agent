"""Interface contracts for Sonnet-built components (Opus-owned).

These Protocols pin the exact signatures the Sonnet-owned implementations must
satisfy so the pieces compose. Implement these in the phase noted; do not widen
or rename methods without flagging it as a contract change.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .checker.schema import CheckerVerdict, ClaimVerdict, Grounding, Thresholds
from .ledger import AuditRecord
from .schema import Telemetry


@runtime_checkable
class CostCalculator(Protocol):
    """Phase 0 (🟢). Reads pricing.yaml with effective-date selection."""

    def cost_usd(
        self, *, provider: str, model: str, input_tokens: int, output_tokens: int,
        cached_tokens: int = 0, at_ms: int | None = None,
    ) -> float: ...


@runtime_checkable
class LLMGateway(Protocol):
    """Phase 1 (🟡). One wrapper over Claude/Gemini/DeepSeek that funnels every
    call through cost + token + span emission. Returns the provider response
    plus a partial Telemetry to fold via telemetry_reducer."""

    def call(self, *, provider: str, model: str, request: Any) -> tuple[Any, Telemetry]: ...


@runtime_checkable
class EventSink(Protocol):
    """Phase 1/2 (🟢). O(1) append on the hot path; drained in batches by a
    background task to the OTLP exporter and Neon. MUST NOT block the request."""

    def emit(self, event: dict) -> None: ...
    async def drain(self) -> int: ...


@runtime_checkable
class GroundingChecker(Protocol):
    """Phase 3 Tier-1 (🟢). Deterministic embedding/lexical grounding +
    citation-integrity. Returns per-claim verdicts with `needs_judge` claims
    left at PARTIAL for the judge to resolve."""

    def check(
        self, *, answer: str, retrieved: dict[int, str], thresholds: Thresholds,
    ) -> list[ClaimVerdict]: ...


@runtime_checkable
class Judge(Protocol):
    """Phase 3 Tier-2 (🟡). Small-model NLI judge, called ONLY for claims where
    needs_judge() is true. Returns a resolved grounding + rationale span."""

    def adjudicate(self, *, claim: str, chunks: list[str]) -> tuple[Grounding, str]: ...


@runtime_checkable
class LedgerWriter(Protocol):
    """Phase 5 (🟡). INSERT-only, fail-closed. Holds the per-project lock so
    id order == chain order; calls ledger.seal() under that lock."""

    def append(self, record: AuditRecord) -> AuditRecord: ...   # returns sealed record
    def head_chain_hash(self, project: str) -> str: ...


@runtime_checkable
class AlertDispatcher(Protocol):
    """Phase 6 (🟢). Debounced dispatch with N-window confirmation; every alert
    carries a trace_id deep-link."""

    def dispatch(self, alert: Any) -> None: ...


# Verdict assembly helper the Checker node uses to combine Tier-1 + Tier-2.
def assemble_verdict(
    trace_id: str, claims: list[ClaimVerdict], thresholds: Thresholds,
) -> CheckerVerdict:
    """Reference wiring: resolve each claim's action, then roll up. Sonnet's
    Checker node calls this after Tier-1 (+ Tier-2 for escalated claims)."""
    from .checker.schema import decide_claim, roll_up

    for c in claims:
        c.action = decide_claim(c.grounding, thresholds)
    return roll_up(trace_id, claims, thresholds)

"""In-graph guard — step budget, (node, state_hash) cycle detection, and
cost/wall-clock ceilings (Phase 4, 🟢). This is the fail-FAST layer from
blueprint §3.2: cheap, synchronous checks that run on every node transition,
distinct from the Checker's audit-after-the-fact review (checker/node.py).

Also wires `monitoring.workflows.check_conformance` as the same kind of
post-node hook, per HANDOFF: an illegal transition -> Flag.ENTERPRISE_LOGIC_DEVIATION,
which is the CRITICAL-severity signal in alerting/model.py.

Wall-clock overage reuses Flag.STEP_BUDGET_EXCEEDED (schema.py's Flag
vocabulary is frozen and has no separate "wall clock" flag) -- the `reason`
string on GuardResult distinguishes step-count vs wall-clock overage for
anyone reading the audit trail.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..graph import state_hash
from ..schema import Flag
from .workflows import WorkflowSpec, check_conformance


@dataclass(frozen=True)
class GuardLimits:
    max_steps: int = 40
    max_wall_clock_s: float = 300.0
    max_cost_usd: float = 5.0
    max_identical_state_repeats: int = 3


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    flag: str | None = None  # a obsvagent.schema.Flag value, if violated
    reason: str = ""


class GuardViolation(RuntimeError):
    """Raised by `enforce()`. Callers catch this to append `.flag` to
    `_telemetry.flags`, abort the run, and (for ENTERPRISE_LOGIC_DEVIATION /
    LOOP_SUSPECTED) trigger the matching CRITICAL alert."""

    def __init__(self, flag: str, reason: str) -> None:
        super().__init__(reason)
        self.flag = flag
        self.reason = reason


class NodeCycleTracker:
    """Tracks (node, state_hash) visit counts for ONE run. Instantiate one
    per trace_id — do not share across concurrent runs."""

    def __init__(self) -> None:
        self._visits: dict[tuple[str, str], int] = {}

    def record(self, node: str, hashed_state: str) -> int:
        key = (node, hashed_state)
        self._visits[key] = self._visits.get(key, 0) + 1
        return self._visits[key]


def check_step_budget(node_path: list[str], limits: GuardLimits) -> GuardResult:
    if len(node_path) > limits.max_steps:
        return GuardResult(
            False, Flag.STEP_BUDGET_EXCEEDED, f"{len(node_path)} steps exceeds budget {limits.max_steps}"
        )
    return GuardResult(True)


def check_cycle(tracker: NodeCycleTracker, node: str, hashed_state: str, limits: GuardLimits) -> GuardResult:
    """A deterministic loop: the SAME node revisited with the SAME domain
    state more than `max_identical_state_repeats` times. Legitimate
    iteration (state changing each visit) is unaffected — only identical
    revisits accumulate against this limit."""
    count = tracker.record(node, hashed_state)
    if count > limits.max_identical_state_repeats:
        return GuardResult(
            False,
            Flag.LOOP_SUSPECTED,
            f"node {node!r} revisited with identical domain state {count} times",
        )
    return GuardResult(True)


def check_wall_clock(started_at: float, limits: GuardLimits, *, now: float | None = None) -> GuardResult:
    elapsed = (now if now is not None else time.time()) - started_at
    if elapsed > limits.max_wall_clock_s:
        return GuardResult(
            False,
            Flag.STEP_BUDGET_EXCEEDED,
            f"wall clock {elapsed:.1f}s exceeds budget {limits.max_wall_clock_s:.1f}s",
        )
    return GuardResult(True)


def check_cost_budget(cost_usd: float, limits: GuardLimits) -> GuardResult:
    if cost_usd > limits.max_cost_usd:
        return GuardResult(
            False, Flag.COST_BUDGET_EXCEEDED, f"cost ${cost_usd:.4f} exceeds budget ${limits.max_cost_usd:.2f}"
        )
    return GuardResult(True)


def check_enterprise_logic(spec: WorkflowSpec | None, node_path: list[str]) -> GuardResult:
    if spec is None:
        return GuardResult(True)
    result = check_conformance(spec, node_path)
    if not result.ok:
        return GuardResult(
            False, Flag.ENTERPRISE_LOGIC_DEVIATION, "; ".join(result.violations)
        )
    return GuardResult(True)


@dataclass
class GuardContext:
    """Everything a single guard evaluation needs, gathered in one place so
    call sites don't have to thread five separate arguments."""

    node_path: list[str]
    started_at: float
    cost_usd: float
    tracker: NodeCycleTracker
    limits: GuardLimits = field(default_factory=GuardLimits)
    spec: WorkflowSpec | None = None


def evaluate(ctx: GuardContext, *, node: str, domain_state: dict) -> list[GuardResult]:
    """Run every check; return only the VIOLATIONS (empty list = all clear).
    Order matches severity: cheap/local checks first, conformance last since
    it needs the full node_path including the just-appended current node."""
    hashed = state_hash(domain_state)
    checks = [
        check_step_budget(ctx.node_path, ctx.limits),
        check_cycle(ctx.tracker, node, hashed, ctx.limits),
        check_wall_clock(ctx.started_at, ctx.limits),
        check_cost_budget(ctx.cost_usd, ctx.limits),
        check_enterprise_logic(ctx.spec, ctx.node_path),
    ]
    return [c for c in checks if not c.ok]


def enforce(ctx: GuardContext, *, node: str, domain_state: dict) -> None:
    """Raise on the first violation. Use `evaluate()` instead when you want
    to collect and audit ALL violations rather than stop at the first."""
    violations = evaluate(ctx, node=node, domain_state=domain_state)
    if violations:
        first = violations[0]
        assert first.flag is not None
        raise GuardViolation(first.flag, first.reason)

"""Enterprise-logic transition specs + conformance check (Opus-owned).

Encodes, per critical workflow, which node transitions are LEGAL and which
nodes MUST have executed before a terminal/side-effecting node. The monitor
compares a run's actual node_path (from schema.Telemetry) against the spec.
An illegal transition or a missing required predecessor is an
ENTERPRISE_LOGIC_DEVIATION -> block + page (see alerting.model CRITICAL tier).

Sonnet (Phase 4) implements the in-graph guard (step/cost budgets, cycle
detection) and wires `check_conformance` as a post-node hook. Sonnet does NOT
edit the specs below — they ARE the enterprise logic; changes are an
architecture decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    # Legal directed edges. A transition (a -> b) not in this set is a deviation.
    allowed_edges: frozenset[tuple[str, str]]
    entry_nodes: frozenset[str]
    terminal_nodes: frozenset[str]
    # node -> nodes that MUST appear earlier in the path before it may run.
    requires_before: dict[str, frozenset[str]] = field(default_factory=dict)
    # Hard ceilings; the in-graph guard enforces these (Phase 4).
    max_steps: int = 40


@dataclass
class ConformanceResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def check_conformance(spec: WorkflowSpec, node_path: list[str]) -> ConformanceResult:
    """Validate an executed node_path against a workflow spec."""
    violations: list[str] = []

    if node_path and node_path[0] not in spec.entry_nodes:
        violations.append(f"illegal entry node: {node_path[0]!r}")

    if len(node_path) > spec.max_steps:
        violations.append(f"step budget exceeded: {len(node_path)} > {spec.max_steps}")

    seen: set[str] = set()
    for i, node in enumerate(node_path):
        # required predecessors
        for req in spec.requires_before.get(node, frozenset()):
            if req not in seen:
                violations.append(
                    f"node {node!r} ran without required predecessor {req!r}"
                )
        # legal edge
        if i > 0:
            edge = (node_path[i - 1], node)
            if edge not in spec.allowed_edges:
                violations.append(f"illegal transition: {edge[0]!r} -> {edge[1]!r}")
        seen.add(node)

    if node_path and node_path[-1] not in spec.terminal_nodes:
        # Not fatal on its own (run may be mid-flight); flag for review.
        violations.append(f"ended on non-terminal node: {node_path[-1]!r}")

    return ConformanceResult(ok=not violations, violations=violations)


# --- Registered workflows -------------------------------------------------
# These correspond to `route` in schema.Telemetry.

# Stablecoin Treasury Orchestrator: an execution can NEVER be reached without a
# prior risk_check AND approval. This is the rule that catches an agent that
# "deviates from enterprise logic" mechanically, not by hoping the prompt held.
TREASURY_ORCHESTRATOR = WorkflowSpec(
    name="treasury_orchestrator",
    entry_nodes=frozenset({"intake"}),
    terminal_nodes=frozenset({"execute", "reject", "abstain"}),
    allowed_edges=frozenset(
        {
            ("intake", "treasury_route"),
            ("treasury_route", "risk_check"),
            ("risk_check", "approval"),
            ("risk_check", "reject"),        # risk can short-circuit to reject
            ("approval", "execute"),
            ("approval", "reject"),
            ("treasury_route", "abstain"),   # no viable route
        }
    ),
    requires_before={
        "approval": frozenset({"risk_check"}),
        "execute": frozenset({"risk_check", "approval"}),
    },
    max_steps=25,
)

# RiskGuard assessment pipeline.
RISKGUARD_ASSESSMENT = WorkflowSpec(
    name="riskguard_assessment",
    entry_nodes=frozenset({"ingest"}),
    terminal_nodes=frozenset({"report", "escalate"}),
    allowed_edges=frozenset(
        {
            ("ingest", "retrieve"),
            ("retrieve", "assess"),
            ("assess", "checker"),
            ("checker", "report"),
            ("checker", "escalate"),   # low-confidence -> human escalation
            ("assess", "retrieve"),    # one legitimate re-retrieval loop
        }
    ),
    requires_before={
        "report": frozenset({"checker"}),
    },
    max_steps=30,
)

REGISTRY: dict[str, WorkflowSpec] = {
    TREASURY_ORCHESTRATOR.name: TREASURY_ORCHESTRATOR,
    RISKGUARD_ASSESSMENT.name: RISKGUARD_ASSESSMENT,
}


def spec_for(route: str) -> WorkflowSpec | None:
    """Look up the spec for a telemetry `route`; None = unmonitored workflow."""
    return REGISTRY.get(route)

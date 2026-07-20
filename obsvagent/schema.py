"""Telemetry state contract + LangGraph reducer (Opus-owned).

THIS IS THE CONTRACT everything in the ecosystem depends on. It defines the
one reserved key `_telemetry` that every LangGraph state carries and the
reducer semantics that make concurrent/branching nodes merge correctly
instead of clobbering each other.

Rules encoded here:
  * node_path, flags, model_versions   -> APPEND (order preserved)
  * token_usage, cost_usd              -> SUM
  * trace_id, parent_trace_id, started_at -> SET-ONCE (first writer wins)

A node returns a PARTIAL Telemetry containing only the fields it touched;
the reducer folds it into the accumulated value.
"""
from __future__ import annotations

from typing import TypedDict

from .ids import new_ulid


class Telemetry(TypedDict, total=False):
    trace_id: str                 # ULID, generated at graph entry (set-once)
    parent_trace_id: str | None   # set for sub-graphs / spawned agents
    tenant: str
    route: str                    # logical workflow name (see monitoring.workflows)
    node_path: list[str]          # ordered node visits (append-only)
    started_at: float             # epoch seconds, monotonic-checked (set-once)
    token_usage: dict[str, int]   # {"prompt": int, "completion": int} (summed)
    cost_usd: float               # running total (summed)
    model_versions: list[str]     # every model touched, in order (append-only)
    flags: list[str]              # "unsupported_claim", "loop_suspected", ... (append, deduped)


# Fields that follow set-once semantics.
_SET_ONCE = ("trace_id", "parent_trace_id", "tenant", "route", "started_at")


def telemetry_reducer(current: Telemetry | None, update: Telemetry | None) -> Telemetry:
    """LangGraph reducer for the `_telemetry` channel.

    Deterministic and commutative for the append/sum fields so parallel
    branches merge identically regardless of arrival order. Set-once fields
    keep the existing value (first writer wins) — a branch cannot overwrite
    the trace_id.
    """
    if current is None:
        current = {}
    if update is None:
        return current

    merged: Telemetry = dict(current)  # type: ignore[assignment]

    for key in _SET_ONCE:
        if key in update and key not in merged:
            merged[key] = update[key]  # type: ignore[literal-required]

    if "node_path" in update:
        merged["node_path"] = [*merged.get("node_path", []), *update["node_path"]]

    if "model_versions" in update:
        merged["model_versions"] = [*merged.get("model_versions", []), *update["model_versions"]]

    if "flags" in update:
        seen = merged.get("flags", [])
        merged["flags"] = seen + [f for f in update["flags"] if f not in seen]

    if "token_usage" in update:
        acc = dict(merged.get("token_usage", {}))
        for k, v in update["token_usage"].items():
            acc[k] = acc.get(k, 0) + v
        merged["token_usage"] = acc

    if "cost_usd" in update:
        merged["cost_usd"] = merged.get("cost_usd", 0.0) + update["cost_usd"]

    return merged


def new_telemetry(*, route: str, tenant: str, parent_trace_id: str | None = None) -> Telemetry:
    """Factory for the root telemetry object at graph entry."""
    import time

    return Telemetry(
        trace_id=new_ulid(),
        parent_trace_id=parent_trace_id,
        tenant=tenant,
        route=route,
        node_path=[],
        started_at=time.time(),
        token_usage={},
        cost_usd=0.0,
        model_versions=[],
        flags=[],
    )


# Standard flag vocabulary. Sonnet: emit only these strings so alert queries
# can filter on them reliably.
class Flag:
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONTRADICTED_CLAIM = "contradicted_claim"
    MISSING_CITATION = "missing_citation"
    FABRICATED_CITATION = "fabricated_citation"
    LOOP_SUSPECTED = "loop_suspected"
    STEP_BUDGET_EXCEEDED = "step_budget_exceeded"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    ENTERPRISE_LOGIC_DEVIATION = "enterprise_logic_deviation"

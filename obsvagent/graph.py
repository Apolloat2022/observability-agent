"""LangGraph node instrumentation — decorator that appends to node_path and
emits a transition span (Phase 1).

Dependency-free: does not import langgraph. A LangGraph "node" is just a
callable `(state) -> partial_state_update_dict` — this decorator wraps that
convention directly, so it works with any StateGraph without a langgraph
import here.

Nodes are expected to carry a `_telemetry: Telemetry` key per schema.py; the
decorator merges its own partial update (node_path append) into whatever
partial `_telemetry` update the wrapped node itself returns, via
telemetry_reducer, rather than overwriting it. LangGraph applies the same
reducer again at the graph level when folding this node's return value into
overall run state — the reducer is designed to be commutative, so folding it
twice (once here, once by LangGraph) is safe.
"""
from __future__ import annotations

import functools
import hashlib
import json
import time
from typing import Callable, Optional

from .interfaces import EventSink
from .otel import (
    OBSV_NODE_DECISION,
    OBSV_NODE_ENTRY_HASH,
    OBSV_NODE_EXIT_HASH,
    OBSV_NODE_LATENCY_MS,
    OBSV_NODE_NAME,
    OBSV_TRACE_ID,
)
from .schema import Telemetry, telemetry_reducer

NodeFn = Callable[[dict], dict]


def _state_hash(state: dict) -> str:
    """Stable hash of domain state, EXCLUDING `_telemetry` — telemetry grows
    monotonically every step (token/cost sums, node_path), so including it
    would make every visit hash-distinct and defeat Phase 4's
    (node, state_hash) cycle detection, which needs same-domain-state
    revisits to collide."""
    domain = {k: v for k, v in state.items() if k != "_telemetry"}
    canonical = json.dumps(domain, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def traced_node(name: str, *, sink: Optional[EventSink] = None) -> Callable[[NodeFn], NodeFn]:
    """Decorator for a LangGraph node function. Wraps `fn(state) -> dict`
    (LangGraph's partial-state-update convention) so every visit:
      * appends `name` to `_telemetry.node_path`
      * emits a transition span with entry/exit state hash + latency
      * preserves whatever partial `_telemetry` update `fn` itself returned
    """

    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        def wrapped(state: dict) -> dict:
            entry_hash = _state_hash(state)
            start_ns = time.time_ns()
            start_perf = time.perf_counter()

            result = fn(state) or {}

            latency_ms = (time.perf_counter() - start_perf) * 1000
            merged_state = {**state, **result}
            exit_hash = _state_hash(merged_state)
            decision = result.pop("_decision", None)

            own_update: Telemetry = {"node_path": [name]}
            existing_telemetry = result.get("_telemetry")
            result["_telemetry"] = telemetry_reducer(existing_telemetry, own_update)

            if sink is not None:
                trace_id = None
                tel = state.get("_telemetry")
                if isinstance(tel, dict):
                    trace_id = tel.get("trace_id")
                sink.emit(
                    {
                        "_span_name": f"node {name}",
                        "_start_ns": start_ns,
                        "_end_ns": time.time_ns(),
                        OBSV_TRACE_ID: trace_id,
                        OBSV_NODE_NAME: name,
                        OBSV_NODE_ENTRY_HASH: entry_hash,
                        OBSV_NODE_EXIT_HASH: exit_hash,
                        OBSV_NODE_DECISION: decision,
                        OBSV_NODE_LATENCY_MS: round(latency_ms, 3),
                    }
                )

            return result

        return wrapped

    return decorator

"""Phase 1 — graph.py tests. Verifies node_path append, state-hash stability
(telemetry excluded from the hash so cycle detection can key off it in
Phase 4), and span emission via a fake sink."""
from __future__ import annotations

from obsvagent.graph import traced_node
from obsvagent.schema import new_telemetry, telemetry_reducer


class _FakeSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)

    async def drain(self) -> int:
        return 0


def test_node_path_appended():
    @traced_node("risk_check")
    def node(state: dict) -> dict:
        return {"score": 0.5}

    tel = new_telemetry(route="riskguard_assessment", tenant="t1")
    state = {"_telemetry": tel, "input": "x"}
    result = node(state)
    assert result["_telemetry"]["node_path"] == ["risk_check"]
    assert result["score"] == 0.5


def test_repeated_visits_append_in_order():
    """Each node returns only ITS OWN delta (LangGraph convention) — the
    graph runtime accumulates across nodes by applying telemetry_reducer to
    the `_telemetry` channel between calls, per the Annotated reducer wired
    in schema.py. This test simulates that accumulation explicitly instead
    of naive dict-spread, matching real LangGraph execution."""

    @traced_node("a")
    def node_a(state: dict) -> dict:
        return {}

    @traced_node("b")
    def node_b(state: dict) -> dict:
        return {}

    tel = new_telemetry(route="r", tenant="t1")
    state = {"_telemetry": tel}
    r1 = node_a(state)
    accumulated = telemetry_reducer(state["_telemetry"], r1["_telemetry"])
    state2 = {"_telemetry": accumulated}
    r2 = node_b(state2)
    accumulated2 = telemetry_reducer(state2["_telemetry"], r2["_telemetry"])
    assert accumulated2["node_path"] == ["a", "b"]


def test_same_domain_state_same_hash_ignoring_telemetry():
    @traced_node("loop_node", sink=_FakeSink())
    def node(state: dict) -> dict:
        return {}

    sink = _FakeSink()

    @traced_node("loop_node", sink=sink)
    def node2(state: dict) -> dict:
        return {}

    tel_a = new_telemetry(route="r", tenant="t1")
    tel_b = new_telemetry(route="r", tenant="t1")  # different trace_id (ULID) but same domain fields
    state_a = {"_telemetry": tel_a, "domain_field": 1}
    state_b = {"_telemetry": tel_b, "domain_field": 1}

    node2(state_a)
    node2(state_b)

    hashes = [e["obsv.node.entry_state_hash"] for e in sink.events]
    assert hashes[0] == hashes[1]  # telemetry excluded -> identical domain state hashes identically


def test_decision_marker_extracted_and_removed():
    @traced_node("router", sink=_FakeSink())
    def node(state: dict) -> dict:
        return {"_decision": "approve", "result": "ok"}

    sink = _FakeSink()

    @traced_node("router2", sink=sink)
    def node2(state: dict) -> dict:
        return {"_decision": "approve", "result": "ok"}

    tel = new_telemetry(route="r", tenant="t1")
    result = node2({"_telemetry": tel})
    assert "_decision" not in result
    assert result["result"] == "ok"
    assert sink.events[0]["obsv.node.decision"] == "approve"


def test_state_hash_changes_when_domain_state_changes():
    sink = _FakeSink()

    @traced_node("mutator", sink=sink)
    def node(state: dict) -> dict:
        return {"counter": state.get("counter", 0) + 1}

    tel = new_telemetry(route="r", tenant="t1")
    s0 = {"_telemetry": tel, "counter": 0}
    r1 = node(s0)
    s1 = {**s0, **r1}
    node(s1)

    entry_hashes = [e["obsv.node.entry_state_hash"] for e in sink.events]
    assert entry_hashes[0] != entry_hashes[1]  # counter changed between visits

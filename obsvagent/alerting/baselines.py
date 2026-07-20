"""Baseline computation — per (model, route) rolling reference stats
(Phase 6, 🟢). Computes an `alerting.model.Baseline` from a window of raw
event rows. Row shape mirrors the OTel attribute keys emitted by
middleware.py / gateway.py / checker/node.py — see `EventRow` below. Phase
2's DAO is the intended real source of these rows; this module has no DB
dependency, so it's fully testable with in-memory lists.
"""
from __future__ import annotations

import statistics
from typing import TypedDict

from .model import Baseline


class EventRow(TypedDict, total=False):
    latency_ms: float
    completion_tokens: int
    cost_usd: float
    is_error: bool
    checker_verdict: str  # "PASS" | "FAIL" | "REVIEW"
    retrieval_score: float


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def compute_baseline(events: list[EventRow], *, model: str, route: str, window: str = "7d") -> Baseline:
    """Fields with no data in the window default conservatively: 0 for
    latency/tokens/cost/error, 1.0 (perfect) for grounding_pass_rate so a
    route with no checked claims doesn't spuriously look degraded."""
    if not events:
        raise ValueError("compute_baseline requires at least one event")

    latencies = [e["latency_ms"] for e in events if "latency_ms" in e]
    tokens = [e["completion_tokens"] for e in events if "completion_tokens" in e]
    costs = [e["cost_usd"] for e in events if "cost_usd" in e]
    errors = [e.get("is_error", False) for e in events]
    verdicts = [e["checker_verdict"] for e in events if "checker_verdict" in e]
    retrieval_scores = [e["retrieval_score"] for e in events if "retrieval_score" in e]

    return Baseline(
        model=model,
        route=route,
        p95_latency_ms=_percentile(latencies, 0.95),
        mean_completion_tokens=statistics.mean(tokens) if tokens else 0.0,
        mean_cost_usd=statistics.mean(costs) if costs else 0.0,
        error_rate=(sum(1 for e in errors if e) / len(errors)) if errors else 0.0,
        grounding_pass_rate=(sum(1 for v in verdicts if v == "PASS") / len(verdicts)) if verdicts else 1.0,
        mean_retrieval_score=statistics.mean(retrieval_scores) if retrieval_scores else 0.0,
        window=window,
    )

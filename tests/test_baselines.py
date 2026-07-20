"""Phase 6 — baselines.py tests."""
from __future__ import annotations

import pytest

from obsvagent.alerting.baselines import compute_baseline


def test_empty_events_raises():
    with pytest.raises(ValueError):
        compute_baseline([], model="claude-opus-4-8", route="riskguard_assessment")


def test_computes_p95_and_means():
    events = [
        {"latency_ms": float(i), "completion_tokens": 100, "cost_usd": 0.01, "is_error": False}
        for i in range(1, 101)
    ]
    baseline = compute_baseline(events, model="claude-opus-4-8", route="r")
    # latencies are 1.0..100.0 sorted; idx = int(100*0.95) = 95 -> sorted[95] = 96.0
    assert baseline.p95_latency_ms == 96.0
    assert baseline.mean_completion_tokens == 100.0
    assert baseline.mean_cost_usd == pytest.approx(0.01)


def test_error_rate_and_grounding_pass_rate():
    events = [
        {"is_error": True, "checker_verdict": "FAIL"},
        {"is_error": False, "checker_verdict": "PASS"},
        {"is_error": False, "checker_verdict": "PASS"},
        {"is_error": False, "checker_verdict": "PASS"},
    ]
    baseline = compute_baseline(events, model="m", route="r")
    assert baseline.error_rate == pytest.approx(0.25)
    assert baseline.grounding_pass_rate == pytest.approx(0.75)


def test_missing_checker_verdict_defaults_pass_rate_to_perfect():
    events = [{"latency_ms": 10.0}]
    baseline = compute_baseline(events, model="m", route="r")
    assert baseline.grounding_pass_rate == 1.0


def test_missing_retrieval_score_defaults_zero():
    events = [{"latency_ms": 10.0}]
    baseline = compute_baseline(events, model="m", route="r")
    assert baseline.mean_retrieval_score == 0.0


def test_window_label_passthrough():
    baseline = compute_baseline([{"latency_ms": 1.0}], model="m", route="r", window="24h")
    assert baseline.window == "24h"

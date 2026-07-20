"""Phase 6 — evaluators.py tests. One breach + one clean case per signal."""
from __future__ import annotations

from obsvagent.alerting.evaluators import (
    eval_cache_hit_collapse,
    eval_cost_per_request_spike,
    eval_embedding_drift,
    eval_error_refusal_spike,
    eval_grounding_rate_drop,
    eval_latency_regression,
    eval_ood_rate,
    eval_output_length_collapse,
    eval_retrieval_quality_drift,
    eval_routing_drift,
)
from obsvagent.alerting.model import Baseline


def _baseline(**overrides) -> Baseline:
    defaults = dict(
        model="claude-opus-4-8",
        route="riskguard_assessment",
        p95_latency_ms=100.0,
        mean_completion_tokens=200.0,
        mean_cost_usd=0.05,
        error_rate=0.01,
        grounding_pass_rate=0.98,
        mean_retrieval_score=0.8,
    )
    defaults.update(overrides)
    return Baseline(**defaults)


def test_latency_regression():
    b = _baseline(p95_latency_ms=100.0)
    assert eval_latency_regression(160.0, b) is True  # > 1.5x
    assert eval_latency_regression(120.0, b) is False


def test_error_refusal_spike_uses_floor_when_baseline_tiny():
    b = _baseline(error_rate=0.001)
    assert eval_error_refusal_spike(0.06, b) is True  # > max(0.002, 0.05)
    assert eval_error_refusal_spike(0.03, b) is False


def test_output_length_collapse():
    b = _baseline(mean_completion_tokens=200.0)
    assert eval_output_length_collapse(100.0, b) is True  # < 0.6x
    assert eval_output_length_collapse(150.0, b) is False


def test_grounding_rate_drop_absolute_sla():
    assert eval_grounding_rate_drop(0.90) is True
    assert eval_grounding_rate_drop(0.99) is False
    assert eval_grounding_rate_drop(0.80, sla=0.75) is False  # per-route override


def test_cost_per_request_spike():
    b = _baseline(mean_cost_usd=0.10)
    assert eval_cost_per_request_spike(0.20, b) is True
    assert eval_cost_per_request_spike(0.12, b) is False


def test_cache_hit_collapse():
    assert eval_cache_hit_collapse(0.2, baseline_cache_hit_ratio=0.6) is True  # < 0.5x
    assert eval_cache_hit_collapse(0.5, baseline_cache_hit_ratio=0.6) is False
    assert eval_cache_hit_collapse(0.0, baseline_cache_hit_ratio=0.0) is False  # no div-by-zero


def test_retrieval_quality_drift():
    b = _baseline(mean_retrieval_score=0.8)
    assert eval_retrieval_quality_drift(0.5, b) is True  # < 0.85x
    assert eval_retrieval_quality_drift(0.75, b) is False


def test_ood_rate():
    assert eval_ood_rate(0.20) is True
    assert eval_ood_rate(0.05) is False


def test_embedding_drift_threshold():
    assert eval_embedding_drift(0.30) is True
    assert eval_embedding_drift(0.05) is False


def test_routing_drift_threshold():
    assert eval_routing_drift(0.30) is True
    assert eval_routing_drift(0.10) is False

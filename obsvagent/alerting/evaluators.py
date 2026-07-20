"""Rolling-window signal evaluators — one `eval_<key>` pure function per
`SignalSpec.rule` in alerting/model.py's catalog (Phase 6, 🟢). Each takes
the current window's computed value(s) plus whatever reference it compares
against and returns bool (breached / not).

Coverage note: only the 8 signals below are genuinely "compare a rolling
value against a reference" evaluators. The remaining 3 in the catalog are
NOT evaluator functions here by design:
  - contradicted_claim_financial  -> fires from checker/node.py directly
  - ledger_integrity_break        -> fires from the Phase 5 verify-ledger CLI
  - enterprise_logic_deviation    -> fires from monitoring/guard.py directly
Baseline (alerting/model.py, frozen) carries only per-route scalar fields
(p95_latency_ms, mean_completion_tokens, mean_cost_usd, error_rate,
grounding_pass_rate, mean_retrieval_score) — cache_hit_collapse takes its
baseline ratio as a separate float since cache-hit-ratio isn't a Baseline
field; embedding_drift / routing_drift take an already-computed PSI score
(via drift.py) since they compare distributions, not scalars.
"""
from __future__ import annotations

from .model import Baseline

# --- Degradation signals (rules quoted from alerting/model.py SIGNALS) -----


def eval_latency_regression(current_p95_ms: float, baseline: Baseline) -> bool:
    """rule: rolling_p95_latency > baseline.p95_latency_ms * 1.5"""
    return current_p95_ms > baseline.p95_latency_ms * 1.5


def eval_error_refusal_spike(current_error_rate: float, baseline: Baseline) -> bool:
    """rule: error_rate > max(baseline.error_rate * 2, 0.05)"""
    return current_error_rate > max(baseline.error_rate * 2, 0.05)


def eval_output_length_collapse(current_mean_completion_tokens: float, baseline: Baseline) -> bool:
    """rule: mean_completion_tokens < baseline.mean_completion_tokens * 0.6"""
    if baseline.mean_completion_tokens <= 0:
        return False
    return current_mean_completion_tokens < baseline.mean_completion_tokens * 0.6


def eval_grounding_rate_drop(current_pass_rate: float, *, sla: float = 0.95) -> bool:
    """rule: grounding_pass_rate < 0.95 (per-route SLA override allowed via `sla`)"""
    return current_pass_rate < sla


def eval_cost_per_request_spike(current_mean_cost_usd: float, baseline: Baseline) -> bool:
    """rule: mean_cost_usd > baseline.mean_cost_usd * 1.5"""
    return current_mean_cost_usd > baseline.mean_cost_usd * 1.5


def eval_cache_hit_collapse(current_cache_hit_ratio: float, baseline_cache_hit_ratio: float) -> bool:
    """rule: cache_hit_ratio < baseline_cache_hit_ratio * 0.5"""
    if baseline_cache_hit_ratio <= 0:
        return False
    return current_cache_hit_ratio < baseline_cache_hit_ratio * 0.5


# --- Data / input drift signals --------------------------------------------


def eval_retrieval_quality_drift(current_mean_retrieval_score: float, baseline: Baseline) -> bool:
    """rule: rolling mean top-k similarity < baseline.mean_retrieval_score * 0.85"""
    if baseline.mean_retrieval_score <= 0:
        return False
    return current_mean_retrieval_score < baseline.mean_retrieval_score * 0.85


def eval_ood_rate(current_ood_fraction: float, *, floor: float = 0.15) -> bool:
    """rule: fraction(best_retrieval_score < floor) > 0.15"""
    return current_ood_fraction > floor


def eval_embedding_drift(psi_score: float, *, threshold: float = 0.2) -> bool:
    """rule: PSI(recent_query_embeddings, reference) > 0.2 (0.1=watch, 0.25=strong).
    `psi_score` is computed by the caller via drift.psi() over a categorical/
    binned embedding distribution."""
    return psi_score > threshold


def eval_routing_drift(psi_score: float, *, threshold: float = 0.25) -> bool:
    """rule: PSI(recent_model_mix, baseline_model_mix) > 0.25"""
    return psi_score > threshold

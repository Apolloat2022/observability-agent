"""Alert baseline model + severity taxonomy + signal catalog (Opus-owned).

Defines WHAT is normal (per-model, per-route baselines) and WHAT pages a human.
Sonnet (Phase 6) implements the rolling-window computation and the dispatch
side (Slack/PagerDuty/webhook) against these declarative specs. Sonnet does not
choose severities or invent thresholds — they live here.

Cardinal rule encoded here: every threshold is relative to a baseline scoped to
(model, route). Gemini Flash and Claude Opus have different "normal" — a global
threshold would be meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    INFO = 10      # dashboard only
    WARN = 20      # Slack / async channel
    CRITICAL = 30  # page on-call


@dataclass(frozen=True)
class Baseline:
    """A rolling reference for one (model, route) pair. Sonnet computes and
    refreshes these from obsv_events; the evaluators read them."""
    model: str
    route: str
    p95_latency_ms: float
    mean_completion_tokens: float
    mean_cost_usd: float
    error_rate: float
    grounding_pass_rate: float
    mean_retrieval_score: float
    window: str = "7d"


@dataclass(frozen=True)
class SignalSpec:
    key: str
    severity: Severity
    description: str
    # A human-readable rule; Sonnet implements the matching evaluator function
    # named `eval_<key>` in alerting/evaluators.py (Phase 6, 🟢).
    rule: str
    # Debounce: require this many consecutive breaching windows before firing.
    require_windows: int = 2


# --- Degradation signals (§5.1) ------------------------------------------
SIGNALS: tuple[SignalSpec, ...] = (
    SignalSpec(
        key="latency_regression",
        severity=Severity.WARN,
        description="Model responding materially slower than its baseline.",
        rule="rolling_p95_latency > baseline.p95_latency_ms * 1.5 for the window",
        require_windows=3,
    ),
    SignalSpec(
        key="error_refusal_spike",
        severity=Severity.CRITICAL,
        description="Provider errors / empty completions / refusals spiking.",
        rule="error_rate > max(baseline.error_rate * 2, 0.05)",
        require_windows=2,
    ),
    SignalSpec(
        key="output_length_collapse",
        severity=Severity.WARN,
        description="Completion length collapsed — often a silent model reroute/degrade.",
        rule="mean_completion_tokens < baseline.mean_completion_tokens * 0.6",
        require_windows=2,
    ),
    SignalSpec(
        key="grounding_rate_drop",
        severity=Severity.CRITICAL,
        description="Checker pass-rate below SLA — the best early hallucination warning.",
        rule="grounding_pass_rate < 0.95  (per-route SLA override allowed)",
        require_windows=1,  # grounding failures page immediately
    ),
    SignalSpec(
        key="cost_per_request_spike",
        severity=Severity.WARN,
        description="Runaway retries or prompt bloat inflating cost.",
        rule="mean_cost_usd > baseline.mean_cost_usd * 1.5",
        require_windows=3,
    ),
    SignalSpec(
        key="cache_hit_collapse",
        severity=Severity.WARN,
        description="Prompt-cache hit ratio dropped — prompt determinism likely broken.",
        rule="cache_hit_ratio < baseline_cache_hit_ratio * 0.5",
        require_windows=2,
    ),
    # --- Data / input drift signals (§5.2) -------------------------------
    SignalSpec(
        key="embedding_drift",
        severity=Severity.INFO,
        description="Query-embedding distribution shifted vs reference window.",
        rule="PSI(recent_query_embeddings, reference) > 0.2  (0.1 = watch, 0.25 = strong)",
        require_windows=2,
    ),
    SignalSpec(
        key="retrieval_quality_drift",
        severity=Severity.WARN,
        description="Retrieved-chunk relevance trending down — corpus going stale.",
        rule="rolling mean top-k similarity < baseline.mean_retrieval_score * 0.85",
        require_windows=3,
    ),
    SignalSpec(
        key="ood_rate",
        severity=Severity.INFO,
        description="Share of queries with no good source is rising.",
        rule="fraction(best_retrieval_score < floor) > 0.15",
        require_windows=2,
    ),
    SignalSpec(
        key="routing_drift",
        severity=Severity.WARN,
        description="Model-router mix swung — a routing rule or provider fallback misfired.",
        rule="PSI(recent_model_mix, baseline_model_mix) > 0.25",
        require_windows=2,
    ),
    # --- Hard compliance/logic signals (fire from other subsystems) -------
    SignalSpec(
        key="contradicted_claim_financial",
        severity=Severity.CRITICAL,
        description="A CONTRADICTED claim shipped on a financial route.",
        rule="checker.verdict == FAIL with a CONTRADICTED claim AND route is financial",
        require_windows=1,
    ),
    SignalSpec(
        key="ledger_integrity_break",
        severity=Severity.CRITICAL,
        description="Audit hash-chain failed verification.",
        rule="verify-ledger reports a broken link",
        require_windows=1,
    ),
    SignalSpec(
        key="enterprise_logic_deviation",
        severity=Severity.CRITICAL,
        description="An illegal node transition or missing required predecessor.",
        rule="monitoring.check_conformance returns not ok",
        require_windows=1,
    ),
)

SIGNALS_BY_KEY: dict[str, SignalSpec] = {s.key: s for s in SIGNALS}

# Routes treated as financial-grade (turn on inline Checker + ledger + paging).
FINANCIAL_ROUTES: frozenset[str] = frozenset({"treasury_orchestrator", "riskguard_assessment"})


@dataclass
class Alert:
    signal_key: str
    severity: Severity
    model: str
    route: str
    observed: float
    threshold: float
    trace_id: str | None = None  # deep-link into the reasoning-path view
    message: str = ""


def is_financial(route: str) -> bool:
    return route in FINANCIAL_ROUTES

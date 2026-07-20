"""PSI / KL drift computation (Phase 6, 🟢). Pure functions over discrete
frequency distributions (bucket/category -> proportion) — used for
embedding-distribution drift, model-mix routing drift, and any other
categorical drift signal in the alerting/model.py catalog. Dependency-free
(no numpy required for these; the "alerting" extra reserves numpy for a
future continuous-embedding variant).
"""
from __future__ import annotations

import math

_EPS = 1e-6  # floor to avoid div-by-zero / log(0) on buckets absent from one side


def normalize(counts: dict[str, float]) -> dict[str, float]:
    """Raw counts -> a proportion distribution summing to 1.0."""
    total = sum(counts.values())
    if total <= 0:
        return {k: 0.0 for k in counts}
    return {k: v / total for k, v in counts.items()}


def psi(reference: dict[str, float], current: dict[str, float]) -> float:
    """Population Stability Index between two proportion distributions.
    PSI = sum((cur - ref) * ln(cur / ref)) over the union of buckets.
    Conventional read: <0.1 stable, 0.1-0.25 moderate shift (watch), >0.25
    major shift (per alerting/model.py's embedding_drift rule text)."""
    keys = set(reference) | set(current)
    total = 0.0
    for k in keys:
        r = max(reference.get(k, 0.0), _EPS)
        c = max(current.get(k, 0.0), _EPS)
        total += (c - r) * math.log(c / r)
    return total


def kl_divergence(reference: dict[str, float], current: dict[str, float]) -> float:
    """KL(current || reference) — asymmetric; measures the cost of encoding
    `current` using a code optimized for `reference`."""
    keys = set(reference) | set(current)
    total = 0.0
    for k in keys:
        r = max(reference.get(k, 0.0), _EPS)
        c = current.get(k, 0.0)
        if c <= 0.0:
            continue
        total += c * math.log(c / r)
    return total

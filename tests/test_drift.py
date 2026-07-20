"""Phase 6 — drift.py tests."""
from __future__ import annotations

import pytest

from obsvagent.alerting.drift import kl_divergence, normalize, psi


def test_normalize_sums_to_one():
    dist = normalize({"a": 3, "b": 1})
    assert dist["a"] == pytest.approx(0.75)
    assert dist["b"] == pytest.approx(0.25)


def test_normalize_empty_total_returns_zeros():
    assert normalize({"a": 0, "b": 0}) == {"a": 0.0, "b": 0.0}


def test_psi_identical_distributions_is_zero():
    dist = {"claude": 0.7, "gemini": 0.2, "deepseek": 0.1}
    assert psi(dist, dist) == pytest.approx(0.0, abs=1e-9)


def test_psi_detects_shift():
    reference = {"claude": 0.7, "gemini": 0.2, "deepseek": 0.1}
    current = {"claude": 0.3, "gemini": 0.3, "deepseek": 0.4}
    score = psi(reference, current)
    assert score > 0.25  # a real mix shift should clear the routing_drift threshold


def test_psi_new_bucket_absent_from_reference():
    reference = {"claude": 1.0}
    current = {"claude": 0.5, "new_provider": 0.5}
    assert psi(reference, current) > 0.0  # must not raise on an unseen bucket


def test_kl_divergence_identical_is_zero():
    dist = {"a": 0.5, "b": 0.5}
    assert kl_divergence(dist, dist) == pytest.approx(0.0, abs=1e-9)


def test_kl_divergence_asymmetric():
    # A plain swap (p={a:.9,b:.1}, q={a:.1,b:.9}) is a degenerate case where
    # both directions land on the same two terms in different order -- use a
    # genuinely non-symmetric pair of distributions instead.
    p = {"a": 0.8, "b": 0.2}
    q = {"a": 0.5, "b": 0.5}
    assert kl_divergence(p, q) != kl_divergence(q, p)

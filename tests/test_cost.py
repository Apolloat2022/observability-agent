"""Phase 0 — cost.py tests. One case per provider plus effective-date and
cached-token edge cases."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from obsvagent.cost import CostCalculator, PricingTable, UnknownPricingError
from obsvagent.interfaces import CostCalculator as CostCalculatorProtocol


def test_implements_protocol():
    assert isinstance(CostCalculator(), CostCalculatorProtocol)


@pytest.mark.parametrize(
    "provider,model",
    [
        ("anthropic", "claude-opus-4-8"),
        ("anthropic", "claude-sonnet-5"),
        ("anthropic", "claude-haiku-4-5"),
        ("google", "gemini-flash"),
        ("deepseek", "deepseek-chat"),
    ],
)
def test_known_provider_model_prices_nonzero(provider, model):
    calc = CostCalculator()
    cost = calc.cost_usd(provider=provider, model=model, input_tokens=1000, output_tokens=1000)
    assert cost > 0


def test_cached_tokens_billed_at_cache_rate_not_input_rate():
    calc = CostCalculator()
    full_input = calc.cost_usd(
        provider="anthropic", model="claude-opus-4-8", input_tokens=1_000_000, output_tokens=0
    )
    half_cached = calc.cost_usd(
        provider="anthropic",
        model="claude-opus-4-8",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=500_000,
    )
    assert half_cached < full_input  # cache_read (1.50) << input (15.00)


def test_unknown_model_raises():
    calc = CostCalculator()
    with pytest.raises(UnknownPricingError):
        calc.cost_usd(provider="anthropic", model="does-not-exist", input_tokens=1, output_tokens=1)


def test_effective_date_selection_picks_newest_rate_not_after_call_time(tmp_path: Path):
    pricing = tmp_path / "pricing.yaml"
    pricing.write_text(
        textwrap.dedent(
            """
            anthropic:
              test-model:
                - { effective_date: "2026-01-01", input: 10.00, output: 20.00, cache_read: 1.00 }
                - { effective_date: "2026-06-01", input: 5.00,  output: 10.00, cache_read: 0.50 }
            """
        ),
        encoding="utf-8",
    )
    calc = CostCalculator(PricingTable(pricing))

    import datetime as dt

    before_change = int(dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    after_change = int(dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)

    old_cost = calc.cost_usd(
        provider="anthropic", model="test-model", input_tokens=1_000_000, output_tokens=0,
        at_ms=before_change,
    )
    new_cost = calc.cost_usd(
        provider="anthropic", model="test-model", input_tokens=1_000_000, output_tokens=0,
        at_ms=after_change,
    )
    assert old_cost == pytest.approx(10.00)
    assert new_cost == pytest.approx(5.00)


def test_call_before_earliest_effective_date_raises(tmp_path: Path):
    pricing = tmp_path / "pricing.yaml"
    pricing.write_text(
        textwrap.dedent(
            """
            anthropic:
              test-model:
                - { effective_date: "2026-06-01", input: 5.00, output: 10.00, cache_read: 0.50 }
            """
        ),
        encoding="utf-8",
    )
    calc = CostCalculator(PricingTable(pricing))
    import datetime as dt

    too_early = int(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    with pytest.raises(UnknownPricingError):
        calc.cost_usd(
            provider="anthropic", model="test-model", input_tokens=1, output_tokens=1, at_ms=too_early
        )

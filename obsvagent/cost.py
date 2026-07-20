"""Cost calculator — implements interfaces.CostCalculator over pricing.yaml.

Phase 0 (Sonnet). Reads the seeded pricing table and picks, per (provider,
model), the newest rate entry whose `effective_date <= at_ms` — so historical
cost stays accurate after a price change instead of drifting when the table
is updated.

pricing.yaml is a SEED — verify current provider pricing before relying on
this for billing (see the file's own header comment).
"""
from __future__ import annotations

import functools
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

_DEFAULT_PRICING_PATH = Path(__file__).parent / "pricing.yaml"


class UnknownPricingError(KeyError):
    """Raised when no rate exists for a (provider, model) pair or the earliest
    effective_date is still in the future relative to the call time."""


@dataclass(frozen=True)
class Rate:
    effective_date_ms: int
    input: float       # USD per 1M input tokens
    output: float       # USD per 1M output tokens
    cache_read: float   # USD per 1M cached-input tokens


def _date_to_ms(d: str) -> int:
    parsed = date.fromisoformat(d)
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc).timestamp() * 1000)


def _load_table(path: Path) -> dict[str, dict[str, list[Rate]]]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    table: dict[str, dict[str, list[Rate]]] = {}
    for provider, models in raw.items():
        table[provider] = {}
        for model, entries in models.items():
            rates = sorted(
                (
                    Rate(
                        effective_date_ms=_date_to_ms(e["effective_date"]),
                        input=float(e["input"]),
                        output=float(e["output"]),
                        cache_read=float(e.get("cache_read", 0.0)),
                    )
                    for e in entries
                ),
                key=lambda r: r.effective_date_ms,
            )
            table[provider][model] = rates
    return table


class PricingTable:
    """Loaded, queryable view of pricing.yaml. Cheap to hold in memory —
    load once per process (see `default_calculator` below)."""

    def __init__(self, path: Path | str = _DEFAULT_PRICING_PATH) -> None:
        self._path = Path(path)
        self._table = _load_table(self._path)

    def reload(self) -> None:
        """Re-read pricing.yaml from disk (e.g. after an admin edit)."""
        self._table = _load_table(self._path)

    def rate_for(self, provider: str, model: str, at_ms: int) -> Rate:
        try:
            rates = self._table[provider][model]
        except KeyError as exc:
            raise UnknownPricingError(f"no pricing entry for {provider}/{model}") from exc
        if not rates:
            raise UnknownPricingError(f"no pricing entry for {provider}/{model}")

        # Newest entry whose effective_date <= at_ms. `rates` is sorted
        # ascending by effective_date_ms, so bisect for the insertion point
        # and step back one — that's the newest entry not after at_ms.
        dates = [r.effective_date_ms for r in rates]
        idx = bisect_right(dates, at_ms) - 1
        if idx < 0:
            raise UnknownPricingError(
                f"{provider}/{model} has no pricing effective at or before the requested time"
            )
        return rates[idx]


class CostCalculator:
    """Implements interfaces.CostCalculator."""

    def __init__(self, table: PricingTable | None = None) -> None:
        self._table = table or PricingTable()

    def cost_usd(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        at_ms: int | None = None,
    ) -> float:
        at = at_ms if at_ms is not None else int(time.time() * 1000)
        rate = self._table.rate_for(provider, model, at)

        billable_input = max(input_tokens - cached_tokens, 0)
        cost = (
            billable_input * rate.input
            + cached_tokens * rate.cache_read
            + output_tokens * rate.output
        ) / 1_000_000
        return cost


@functools.lru_cache(maxsize=1)
def default_calculator() -> CostCalculator:
    """Process-wide singleton over the bundled pricing.yaml. Prefer this in
    the LLMGateway (Phase 1) over constructing a new PricingTable per call."""
    return CostCalculator()

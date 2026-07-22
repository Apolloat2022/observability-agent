"""LLMGateway — implements interfaces.LLMGateway for Anthropic/Gemini/DeepSeek (Phase 1, review gate).

Design: the gateway does NOT own provider SDK clients or make the network
call itself. `request` is a zero-arg callable the caller has already bound to
their configured client (e.g. `lambda: client.messages.create(...)`). The
gateway invokes it, times it, and extracts usage via provider-specific
duck-typed field readers — so this module has ZERO hard SDK dependency and
is fully unit-testable with fake response objects (no network, no API key).

Anthropic field names verified against the `claude-api` skill's Python
reference (Prompt Caching / Verifying Cache Hits section):
  response.usage.input_tokens
  response.usage.output_tokens
  response.usage.cache_read_input_tokens   (cache_creation_input_tokens also
                                             exists but is a write, not a
                                             billable-as-cached read — not
                                             counted as `cached_tokens` here)
  response.model                            (the model that actually served
                                             the request — may differ from
                                             the requested alias)

Gemini and DeepSeek field names are documented provider conventions
(`usage_metadata.*` / OpenAI-compatible `usage.*`) — cross-check against
their own SDK docs before wiring a real client; this file only reads
whatever object comes back from `request()`.

Groq field names verified empirically (not just from docs) against a real
`langchain_groq.ChatGroq.invoke()` response while wiring RAG-LLM-Project-
showcase, which calls Groq via LangChain rather than a raw SDK client:
  response.usage_metadata["input_tokens"]     -- LangChain's standardized
  response.usage_metadata["output_tokens"]       usage dict (a plain dict,
                                                  not an object -- unlike the
                                                  other three readers, which
                                                  all use attribute access
                                                  on a raw provider response)
  response.response_metadata["model_name"]    -- the model that actually
                                                  served the request
No cached-token concept for Groq; `cached_tokens` is always 0.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .cost import default_calculator
from .interfaces import EventSink
from .otel import (
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT,
    GEN_AI_USAGE_OUTPUT,
    OBSV_COST_USD,
    OBSV_TRACE_ID,
    PROVIDERS,
)
from .schema import Telemetry


@dataclass(frozen=True)
class UsageReading:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    response_model: str


def _read_anthropic_usage(response: Any, requested_model: str) -> UsageReading:
    usage = response.usage
    return UsageReading(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        response_model=getattr(response, "model", requested_model),
    )


def _read_google_usage(response: Any, requested_model: str) -> UsageReading:
    usage = response.usage_metadata
    return UsageReading(
        input_tokens=usage.prompt_token_count,
        output_tokens=usage.candidates_token_count,
        cached_tokens=getattr(usage, "cached_content_token_count", 0) or 0,
        response_model=getattr(response, "model_version", None) or requested_model,
    )


def _read_deepseek_usage(response: Any, requested_model: str) -> UsageReading:
    usage = response.usage
    return UsageReading(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        cached_tokens=getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
        response_model=getattr(response, "model", None) or requested_model,
    )


def _read_groq_usage(response: Any, requested_model: str) -> UsageReading:
    """Reads a LangChain `AIMessage` (langchain_groq.ChatGroq output), not a
    raw Groq SDK response -- `usage_metadata` and `response_metadata` are
    plain dicts on the message object, not nested attribute objects."""
    usage = response.usage_metadata
    return UsageReading(
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_tokens=0,
        response_model=response.response_metadata.get("model_name") or requested_model,
    )


_READERS: dict[str, Callable[[Any, str], UsageReading]] = {
    "anthropic": _read_anthropic_usage,
    "google": _read_google_usage,
    "deepseek": _read_deepseek_usage,
    "groq": _read_groq_usage,
}


class UnknownProviderError(KeyError):
    pass


class LLMGateway:
    """Implements interfaces.LLMGateway. One instance per process; safe to
    share across requests (holds no per-call state)."""

    def __init__(self, *, sink: Optional[EventSink] = None) -> None:
        self._sink = sink
        self._cost = default_calculator()

    def call(self, *, provider: str, model: str, request: Callable[[], Any]) -> tuple[Any, Telemetry]:
        if provider not in PROVIDERS:
            raise UnknownProviderError(f"unknown provider {provider!r}, expected one of {PROVIDERS}")
        reader = _READERS[provider]

        start_ns = time.time_ns()
        start_perf = time.perf_counter()
        response = request()
        latency_ms = (time.perf_counter() - start_perf) * 1000

        usage = reader(response, model)
        cost_usd = self._cost.cost_usd(
            provider=provider,
            model=usage.response_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
        )

        telemetry: Telemetry = {
            "model_versions": [usage.response_model],
            "token_usage": {"prompt": usage.input_tokens, "completion": usage.output_tokens},
            "cost_usd": cost_usd,
            "flags": [],
        }

        if self._sink is not None:
            from .middleware import current_trace_id  # local import: avoid a hard edge on middleware

            self._sink.emit(
                {
                    "_span_name": f"llm.call {provider}/{model}",
                    "_start_ns": start_ns,
                    "_end_ns": time.time_ns(),
                    OBSV_TRACE_ID: current_trace_id.get() or None,
                    GEN_AI_SYSTEM: provider,
                    GEN_AI_REQUEST_MODEL: model,
                    GEN_AI_RESPONSE_MODEL: usage.response_model,
                    GEN_AI_USAGE_INPUT: usage.input_tokens,
                    GEN_AI_USAGE_OUTPUT: usage.output_tokens,
                    OBSV_COST_USD: cost_usd,
                    "obsv.latency_ms": round(latency_ms, 3),
                }
            )

        return response, telemetry

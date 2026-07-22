"""Phase 1 — gateway.py tests. Uses fake response objects shaped like each
provider's real usage payload (no SDK dependency, no network) — this is what
lets the gateway stay import-clean without anthropic/google/openai installed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from obsvagent.gateway import LLMGateway, UnknownProviderError
from obsvagent.interfaces import LLMGateway as LLMGatewayProtocol


def test_implements_protocol():
    assert isinstance(LLMGateway(), LLMGatewayProtocol)


def test_anthropic_usage_extraction():
    fake_response = SimpleNamespace(
        model="claude-opus-4-8",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=200),
    )
    gw = LLMGateway()
    response, telemetry = gw.call(
        provider="anthropic", model="claude-opus-4-8", request=lambda: fake_response
    )
    assert response is fake_response
    assert telemetry["token_usage"] == {"prompt": 1000, "completion": 500}
    assert telemetry["model_versions"] == ["claude-opus-4-8"]
    assert telemetry["cost_usd"] > 0


def test_google_usage_extraction():
    fake_response = SimpleNamespace(
        model_version="gemini-flash",
        usage_metadata=SimpleNamespace(
            prompt_token_count=800, candidates_token_count=300, cached_content_token_count=0
        ),
    )
    gw = LLMGateway()
    _, telemetry = gw.call(provider="google", model="gemini-flash", request=lambda: fake_response)
    assert telemetry["token_usage"] == {"prompt": 800, "completion": 300}


def test_deepseek_usage_extraction():
    fake_response = SimpleNamespace(
        model="deepseek-chat",
        usage=SimpleNamespace(prompt_tokens=400, completion_tokens=100, prompt_cache_hit_tokens=50),
    )
    gw = LLMGateway()
    _, telemetry = gw.call(provider="deepseek", model="deepseek-chat", request=lambda: fake_response)
    assert telemetry["token_usage"] == {"prompt": 400, "completion": 100}


def test_groq_usage_extraction():
    # Shape matches a REAL langchain_groq.ChatGroq AIMessage response
    # (verified empirically against a live Groq call while wiring
    # RAG-LLM-Project-showcase) -- usage_metadata/response_metadata are
    # plain dicts on the message, not attribute objects like the other
    # three providers' raw SDK responses.
    fake_response = SimpleNamespace(
        usage_metadata={"input_tokens": 41, "output_tokens": 2, "total_tokens": 43},
        response_metadata={"model_name": "llama-3.3-70b-versatile", "finish_reason": "stop"},
    )
    gw = LLMGateway()
    _, telemetry = gw.call(
        provider="groq", model="llama-3.3-70b-versatile", request=lambda: fake_response
    )
    assert telemetry["token_usage"] == {"prompt": 41, "completion": 2}
    assert telemetry["model_versions"] == ["llama-3.3-70b-versatile"]
    assert telemetry["cost_usd"] > 0


def test_unknown_provider_raises():
    gw = LLMGateway()
    with pytest.raises(UnknownProviderError):
        gw.call(provider="openai", model="gpt-5", request=lambda: SimpleNamespace())


def test_cached_tokens_reduce_cost_vs_uncached():
    def make(cached: int) -> SimpleNamespace:
        return SimpleNamespace(
            model="claude-opus-4-8",
            usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=cached),
        )

    gw = LLMGateway()
    _, uncached = gw.call(provider="anthropic", model="claude-opus-4-8", request=lambda: make(0))
    _, cached = gw.call(provider="anthropic", model="claude-opus-4-8", request=lambda: make(500_000))
    assert cached["cost_usd"] < uncached["cost_usd"]

"""OpenTelemetry attribute contract (Opus-owned).

The wire format is OTel spans using GenAI semantic conventions plus a small
set of `obsv.*` extensions. Emit these EXACT keys — dashboards, the collector
pipeline, and the drift/alert queries all key off them. Adding a key is safe;
renaming one is a breaking change.

Sonnet: import these constants everywhere you set span attributes. Never
hand-type an attribute string.
"""
from __future__ import annotations

from typing import Final

# --- GenAI semantic conventions (OTel standard) ---------------------------
GEN_AI_SYSTEM: Final = "gen_ai.system"                 # "anthropic" | "google" | "deepseek"
GEN_AI_OPERATION: Final = "gen_ai.operation.name"      # "chat" | "embeddings" | ...
GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"   # requested model id
GEN_AI_RESPONSE_MODEL: Final = "gen_ai.response.model" # model id the provider actually served
GEN_AI_USAGE_INPUT: Final = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT: Final = "gen_ai.usage.output_tokens"
GEN_AI_REQUEST_TEMPERATURE: Final = "gen_ai.request.temperature"

# --- obsv.* extensions (ours) --------------------------------------------
OBSV_TRACE_ID: Final = "obsv.trace_id"                 # ULID, our canonical id
OBSV_PARENT_TRACE_ID: Final = "obsv.parent_trace_id"
OBSV_TENANT: Final = "obsv.tenant"
OBSV_ROUTE: Final = "obsv.route"                       # logical route/workflow name
OBSV_COST_USD: Final = "obsv.cost_usd"
OBSV_CACHE_HIT: Final = "obsv.cache.hit"               # bool: prompt-cache hit
OBSV_TTFT_MS: Final = "obsv.ttft_ms"                   # time to first token
OBSV_PROMPT_TEMPLATE_VERSION: Final = "obsv.prompt_template_version"

# --- node / graph attributes ---------------------------------------------
OBSV_NODE_NAME: Final = "obsv.node.name"
OBSV_NODE_ENTRY_HASH: Final = "obsv.node.entry_state_hash"
OBSV_NODE_EXIT_HASH: Final = "obsv.node.exit_state_hash"
OBSV_NODE_DECISION: Final = "obsv.node.decision"       # which edge was taken
OBSV_NODE_LATENCY_MS: Final = "obsv.node.latency_ms"

# --- checker / compliance attributes -------------------------------------
OBSV_CHECKER_VERDICT: Final = "obsv.checker.verdict"   # PASS | REVIEW | FAIL
OBSV_CHECKER_UNSUPPORTED_RATIO: Final = "obsv.checker.unsupported_ratio"
OBSV_AUDIT_ID: Final = "obsv.audit.id"
OBSV_AUDIT_CHAIN_HASH: Final = "obsv.audit.chain_hash"

# W3C traceparent header the FastAPI middleware honors on ingress and sets on egress.
TRACEPARENT_HEADER: Final = "traceparent"
TRACE_ID_RESPONSE_HEADER: Final = "X-Trace-Id"

# Provider id normalization. Sonnet: the LLMGateway maps raw SDK/system names
# to these canonical values before setting GEN_AI_SYSTEM.
#
# "groq" added when wiring the first real app (RAG-LLM-Project-showcase),
# which calls Groq (Llama 3.3 70B) via langchain-groq -- not one of the three
# originally-scoped providers. Purely additive; the original three are
# unchanged.
PROVIDERS: Final = ("anthropic", "google", "deepseek", "groq")

"""Tier-2 LLM judge — implements interfaces.Judge (Phase 3, 🟡 review gate).

Constrained NLI-style adjudication for claims Tier-1 left ambiguous
(Grounding.PARTIAL). Pinned to claude-haiku-4-5 per the HANDOFF decision —
strongest constrained-NLI / output-contract adherence of the three judge
candidates, and gives cross-family independence on Gemini/DeepSeek
generation routes. Verify the model id + current pricing against the
`claude-api` skill before wiring a real client.

Like gateway.py, this stays dependency-free by taking the actual model call
as a caller-supplied callable: `call_fn(prompt) -> raw_text`. The caller owns
the Anthropic client, retries, and auth; this class owns the prompt and the
parse — that split is what makes it unit-testable without a network call.
"""
from __future__ import annotations

import re
from typing import Callable

from .schema import Grounding

JUDGE_MODEL = "claude-haiku-4-5"

_VALID = ("CONTRADICTED", "UNSUPPORTED", "PARTIAL", "SUPPORTED")
_ANSWER_RE = re.compile(r"\b(" + "|".join(_VALID) + r")\b", re.IGNORECASE)

_PROMPT_TEMPLATE = """You are a strict grounding auditor. Decide whether CLAIM is supported by SOURCE.

SOURCE:
{sources}

CLAIM:
{claim}

Answer on the first line with EXACTLY ONE WORD: SUPPORTED, PARTIAL, UNSUPPORTED, or CONTRADICTED.
- SUPPORTED: every part of the claim is directly backed by the source.
- PARTIAL: some of the claim is backed, but part of it goes beyond the source.
- UNSUPPORTED: the source does not address the claim at all.
- CONTRADICTED: the source states something that conflicts with the claim.
On the second line, quote the specific span of SOURCE (or say "none") that your answer rests on.
Do not add any other text."""


def build_prompt(claim: str, chunks: list[str]) -> str:
    sources = "\n---\n".join(f"[{i}] {c}" for i, c in enumerate(chunks)) or "(no chunks provided)"
    return _PROMPT_TEMPLATE.format(sources=sources, claim=claim)


def parse_verdict(raw_text: str) -> tuple[Grounding, str]:
    """Robust parse: find the first valid label anywhere in the response
    (models don't always follow "first line only" exactly). If no valid
    label is found, fail toward human review (PARTIAL -> FLAG), never
    toward a silent PASS."""
    match = _ANSWER_RE.search(raw_text)
    if match is None:
        return Grounding.PARTIAL, f"unparseable judge response: {raw_text!r}"
    label = match.group(1).upper()
    rationale = raw_text[match.end():].strip() or raw_text.strip()
    return Grounding[label], rationale


class AnthropicJudge:
    """Implements interfaces.Judge."""

    def __init__(self, call_fn: Callable[[str], str], *, model: str = JUDGE_MODEL) -> None:
        self._call_fn = call_fn
        self.model = model

    def adjudicate(self, *, claim: str, chunks: list[str]) -> tuple[Grounding, str]:
        prompt = build_prompt(claim, chunks)
        raw_text = self._call_fn(prompt)
        return parse_verdict(raw_text)

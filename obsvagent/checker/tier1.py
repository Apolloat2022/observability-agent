"""Tier-1 grounding checker — implements interfaces.GroundingChecker (Phase 3, 🟢).

Deterministic, offline, no network/API calls: claim splitting, citation
extraction, citation-integrity check (fabricated ids), and a lexical
term-frequency cosine similarity against cited chunks. This is the "cheap,
first" tier from the blueprint — it resolves the ~80-90% of claims with a
clearly high or low score; the ambiguous middle band is left as PARTIAL for
the Tier-2 judge (judge.py) to resolve.

Similarity is lexical (bag-of-words cosine), not embedding-based — there is
no embedding model wired into this offline path. Swap `similarity_fn` for a
real embedding-based scorer later without touching the rest of the pipeline;
the "checker" extra (numpy) is reserved for that upgrade.
"""
from __future__ import annotations

import math
import re
from typing import Callable

from .schema import ClaimVerdict, Grounding, Thresholds, needs_judge

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CITATION_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_WORD = re.compile(r"[a-z0-9]+")

# A claim with no citation marker is only flagged MISSING_CITATION if it looks
# "factual" by this heuristic: contains a digit (quantitative claim) or is
# longer than this many words (substantive assertion, not a transition
# phrase like "In summary," or "Let's look at pricing."). Deliberately simple
# — refine per-domain if false-positive rate on transition sentences is high.
_MIN_WORDS_FOR_CITATION_WORTHY = 6


def split_claims(answer: str) -> list[str]:
    """Split an answer into atomic claims (sentence-level). Heuristic, not
    full NLP — citation markers like `[3]` never contain whitespace so they
    survive the split attached to their sentence."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(answer.strip()) if s.strip()]


def extract_citations(claim: str) -> list[int]:
    """All chunk ids referenced by `[n]` / `[n, m]` markers in a claim."""
    ids: list[int] = []
    for match in _CITATION_MARKER.finditer(claim):
        ids.extend(int(x.strip()) for x in match.group(1).split(","))
    return ids


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _tf(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return counts


def lexical_similarity(claim: str, chunk: str) -> float:
    """Term-frequency cosine similarity in [0, 1]. Cheap, deterministic,
    dependency-free — the default `similarity_fn`."""
    a, b = _tf(_tokenize(claim)), _tf(_tokenize(chunk))
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _looks_citation_worthy(claim: str) -> bool:
    words = _tokenize(claim)
    return any(ch.isdigit() for ch in claim) or len(words) > _MIN_WORDS_FOR_CITATION_WORTHY


class Tier1GroundingChecker:
    """Implements interfaces.GroundingChecker."""

    def __init__(self, similarity_fn: Callable[[str, str], float] = lexical_similarity) -> None:
        self._similarity_fn = similarity_fn

    def check(
        self, *, answer: str, retrieved: dict[int, str], thresholds: Thresholds
    ) -> list[ClaimVerdict]:
        verdicts: list[ClaimVerdict] = []

        for claim in split_claims(answer):
            cited = extract_citations(claim)

            if not cited:
                if _looks_citation_worthy(claim):
                    verdicts.append(
                        ClaimVerdict(claim, [], Grounding.MISSING_CITATION, 0.0, tier=1)
                    )
                else:
                    verdicts.append(ClaimVerdict(claim, [], Grounding.SUPPORTED, 1.0, tier=1))
                continue

            fabricated = [c for c in cited if c not in retrieved]
            if fabricated:
                verdicts.append(
                    ClaimVerdict(claim, cited, Grounding.FABRICATED_CITATION, 0.0, tier=1)
                )
                continue

            score = max(self._similarity_fn(claim, retrieved[c]) for c in cited)

            if needs_judge(score, thresholds):
                grounding = Grounding.PARTIAL  # ambiguous -> Tier-2 judge resolves
            elif score >= thresholds.tau_high:
                grounding = Grounding.SUPPORTED
            else:
                grounding = Grounding.UNSUPPORTED

            verdicts.append(ClaimVerdict(claim, cited, grounding, score, tier=1))

        return verdicts

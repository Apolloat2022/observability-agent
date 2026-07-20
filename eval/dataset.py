"""Curated Checker eval set (Phase 3 acceptance criterion).

Each case is one claim + its retrieved context, tagged with the grounding
label the FULL pipeline (Tier-1 + Tier-2) should land on. `judge_answers`
scripts a fake Tier-2 judge for cases that need escalation, keyed by claim
text — this eval proves the PIPELINE PLUMBING is correct (Tier-1 correctly
resolves the clean cases and correctly escalates the ambiguous ones; the
verdict rollup classifies correctly), not real judge-model quality. Real
judge quality requires a live Anthropic client and is a separate,
live-model evaluation gated behind the Phase 3 review (see checker/judge.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from obsvagent.checker.schema import Grounding


@dataclass(frozen=True)
class EvalCase:
    name: str
    category: str  # "supported" | "unsupported" | "contradicted" | "fabricated_citation"
    claim: str
    retrieved: dict[int, str]
    expected: Grounding


CASES: list[EvalCase] = [
    EvalCase(
        name="supported_clean_paraphrase_overlap",
        category="supported",
        claim="The treasury holds 3 million USDC in reserve [1].",
        retrieved={1: "The treasury holds 3 million USDC in reserve, verified by the auditor."},
        expected=Grounding.SUPPORTED,
    ),
    EvalCase(
        name="unsupported_clean_unrelated_chunk",
        category="unsupported",
        claim="The treasury holds 3 million USDC in reserve [1].",
        retrieved={1: "The quarterly all-hands meeting was rescheduled to next Thursday afternoon."},
        expected=Grounding.UNSUPPORTED,
    ),
    EvalCase(
        name="contradicted_delayed_shipment",
        category="contradicted",
        claim="The vendor confirmed the shipment will arrive within two business days [1].",
        retrieved={
            1: "The vendor stated the shipment has been delayed indefinitely and will not arrive as scheduled."
        },
        expected=Grounding.CONTRADICTED,
    ),
    EvalCase(
        name="fabricated_citation_id_never_retrieved",
        category="fabricated_citation",
        claim="Net revenue grew 12% year over year [7].",
        retrieved={1: "Net revenue grew 12% year over year per the audited statement."},
        expected=Grounding.FABRICATED_CITATION,
    ),
    EvalCase(
        name="unsupported_partial_overlap_off_topic_detail",
        category="unsupported",
        claim="The audit found the treasury's cold storage wallet was compromised last quarter [1].",
        retrieved={1: "The treasury's cold storage wallet holds the majority of reserve funds."},
        expected=Grounding.UNSUPPORTED,
    ),
    EvalCase(
        name="supported_partial_band_full_backing",
        category="supported",
        claim="The risk model flags transactions above the configured threshold for manual review [1].",
        retrieved={
            1: "Any transaction exceeding the configured threshold is automatically flagged by the "
            "risk model and routed to a human reviewer before settlement."
        },
        expected=Grounding.SUPPORTED,
    ),
]

# Fake Tier-2 judge answers, keyed by claim text -- for cases whose Tier-1
# lexical score lands in the ambiguous band and must escalate. Cases whose
# Tier-1 score resolves cleanly (SUPPORTED/UNSUPPORTED without escalation)
# don't need an entry here; the eval runner asserts which path each case
# actually took.
JUDGE_ANSWERS: dict[str, tuple[Grounding, str]] = {
    "The vendor confirmed the shipment will arrive within two business days [1].": (
        Grounding.CONTRADICTED,
        "Source states the shipment 'has been delayed indefinitely and will not arrive as scheduled', "
        "which directly conflicts with the claim's two-business-day arrival.",
    ),
    "The audit found the treasury's cold storage wallet was compromised last quarter [1].": (
        Grounding.UNSUPPORTED,
        "Source describes what the wallet holds; it says nothing about a compromise or any audit finding.",
    ),
    "The risk model flags transactions above the configured threshold for manual review [1].": (
        Grounding.SUPPORTED,
        "Source states the same mechanism in different words: threshold-exceeding transactions are "
        "flagged and routed to a human reviewer.",
    ),
}

"""Phase 3 — tier1.py tests."""
from __future__ import annotations

from obsvagent.checker.schema import Grounding, Thresholds
from obsvagent.checker.tier1 import (
    Tier1GroundingChecker,
    extract_citations,
    lexical_similarity,
    split_claims,
)
from obsvagent.interfaces import GroundingChecker


def test_implements_protocol():
    assert isinstance(Tier1GroundingChecker(), GroundingChecker)


def test_split_claims_basic():
    claims = split_claims("First sentence. Second sentence! Third one?")
    assert claims == ["First sentence.", "Second sentence!", "Third one?"]


def test_split_claims_preserves_citation_markers_attached():
    claims = split_claims("Revenue grew 12% [3]. Costs fell 4% [4].")
    assert claims == ["Revenue grew 12% [3].", "Costs fell 4% [4]."]


def test_extract_citations_single_and_multi():
    assert extract_citations("A claim [3].") == [3]
    assert extract_citations("A claim [3, 4].") == [3, 4]
    assert extract_citations("No citation here.") == []


def test_lexical_similarity_identical_text_is_one():
    assert lexical_similarity("the quick brown fox", "the quick brown fox") == 1.0


def test_lexical_similarity_disjoint_text_is_zero():
    assert lexical_similarity("apples oranges bananas", "quarterly meeting schedule") == 0.0


def test_fabricated_citation_detected():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(
        answer="Revenue grew 12% [9].", retrieved={1: "Revenue grew 12% per the filing."},
        thresholds=Thresholds(),
    )
    assert verdicts[0].grounding is Grounding.FABRICATED_CITATION


def test_uncited_short_claim_defaults_supported_not_flagged():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(answer="In summary.", retrieved={}, thresholds=Thresholds())
    assert verdicts[0].grounding is Grounding.SUPPORTED


def test_uncited_substantive_claim_flags_missing_citation():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(
        answer="The treasury holds three million dollars in reserve funds today.",
        retrieved={1: "unrelated chunk"},
        thresholds=Thresholds(),
    )
    assert verdicts[0].grounding is Grounding.MISSING_CITATION


def test_high_overlap_resolves_supported_without_escalation():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(
        answer="The treasury holds 3 million USDC in reserve [1].",
        retrieved={1: "The treasury holds 3 million USDC in reserve, verified by the auditor."},
        thresholds=Thresholds(),
    )
    assert verdicts[0].grounding is Grounding.SUPPORTED
    assert verdicts[0].tier == 1


def test_zero_overlap_resolves_unsupported_without_escalation():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(
        answer="The treasury holds 3 million USDC in reserve [1].",
        retrieved={1: "The quarterly meeting was rescheduled to Thursday."},
        thresholds=Thresholds(),
    )
    assert verdicts[0].grounding is Grounding.UNSUPPORTED
    assert verdicts[0].tier == 1


def test_ambiguous_band_left_partial_for_judge():
    checker = Tier1GroundingChecker()
    verdicts = checker.check(
        answer="The vendor confirmed the shipment will arrive within two business days [1].",
        retrieved={
            1: "The vendor stated the shipment has been delayed indefinitely and will not "
            "arrive as scheduled."
        },
        thresholds=Thresholds(),
    )
    assert verdicts[0].grounding is Grounding.PARTIAL
    assert verdicts[0].tier == 1

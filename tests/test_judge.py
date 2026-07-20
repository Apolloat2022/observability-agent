"""Phase 3 — judge.py tests. No network: call_fn is a fake returning
canned text, per the caller-supplied-callable design (matches gateway.py)."""
from __future__ import annotations

from obsvagent.checker.judge import JUDGE_MODEL, AnthropicJudge, build_prompt, parse_verdict
from obsvagent.checker.schema import Grounding
from obsvagent.interfaces import Judge


def test_implements_protocol():
    assert isinstance(AnthropicJudge(call_fn=lambda p: "SUPPORTED"), Judge)


def test_default_model_is_haiku_per_handoff_decision():
    assert JUDGE_MODEL == "claude-haiku-4-5"
    assert AnthropicJudge(call_fn=lambda p: "SUPPORTED").model == "claude-haiku-4-5"


def test_build_prompt_includes_claim_and_all_chunks():
    prompt = build_prompt("The sky is blue.", ["chunk one text", "chunk two text"])
    assert "The sky is blue." in prompt
    assert "chunk one text" in prompt
    assert "chunk two text" in prompt


def test_parse_verdict_first_line_clean():
    grounding, rationale = parse_verdict("SUPPORTED\nThe source directly states this.")
    assert grounding is Grounding.SUPPORTED
    assert "directly states" in rationale


def test_parse_verdict_all_four_labels():
    for label, expected in [
        ("SUPPORTED", Grounding.SUPPORTED),
        ("PARTIAL", Grounding.PARTIAL),
        ("UNSUPPORTED", Grounding.UNSUPPORTED),
        ("CONTRADICTED", Grounding.CONTRADICTED),
    ]:
        grounding, _ = parse_verdict(f"{label}\nsome rationale")
        assert grounding is expected


def test_parse_verdict_unsupported_not_confused_with_supported():
    """UNSUPPORTED contains SUPPORTED as a substring -- must not mismatch."""
    grounding, _ = parse_verdict("UNSUPPORTED\nno backing found")
    assert grounding is Grounding.UNSUPPORTED


def test_parse_verdict_unparseable_response_fails_toward_review_not_pass():
    grounding, rationale = parse_verdict("I'm not sure how to answer this one.")
    assert grounding is Grounding.PARTIAL  # -> FLAG action, never a silent PASS
    assert "unparseable" in rationale


def test_adjudicate_calls_call_fn_with_built_prompt_and_parses_result():
    seen_prompts = []

    def fake_call(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "CONTRADICTED\nThe source says the opposite."

    judge = AnthropicJudge(call_fn=fake_call)
    grounding, rationale = judge.adjudicate(claim="X happened", chunks=["Y happened, not X"])
    assert grounding is Grounding.CONTRADICTED
    assert "X happened" in seen_prompts[0]
    assert "Y happened, not X" in seen_prompts[0]

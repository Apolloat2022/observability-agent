"""Phase 3 eval runner — curated set covering supported/unsupported/
contradicted/fabricated-citation, precision/recall report.

Run: python eval/run_eval.py

Proves pipeline correctness (Tier-1 resolution + escalation + verdict
rollup), NOT real judge-model quality -- the Tier-2 judge here is scripted
(dataset.JUDGE_ANSWERS) rather than a live Anthropic call. See dataset.py's
docstring.
"""
from __future__ import annotations

import sys
from collections import Counter

from obsvagent.checker.schema import Grounding, Thresholds
from obsvagent.checker.tier1 import Tier1GroundingChecker

from dataset import CASES, JUDGE_ANSWERS


class ScriptedJudge:
    """Test double for interfaces.Judge — looks up the canned answer for a
    known eval claim instead of calling a real model."""

    def __init__(self, answers: dict[str, tuple[Grounding, str]]) -> None:
        self._answers = answers
        self.calls = 0

    def adjudicate(self, *, claim: str, chunks: list[str]) -> tuple[Grounding, str]:
        self.calls += 1
        if claim not in self._answers:
            raise KeyError(f"no scripted judge answer for eval claim: {claim!r}")
        return self._answers[claim]


def run() -> int:
    tier1 = Tier1GroundingChecker()
    judge = ScriptedJudge(JUDGE_ANSWERS)
    thresholds = Thresholds()

    results = []
    for case in CASES:
        claims = tier1.check(answer=case.claim, retrieved=case.retrieved, thresholds=thresholds)
        assert len(claims) == 1, f"{case.name}: expected exactly 1 claim, got {len(claims)}"
        claim = claims[0]

        escalated = claim.grounding is Grounding.PARTIAL and claim.tier == 1
        if escalated:
            resolved, rationale = judge.adjudicate(claim=claim.text, chunks=list(case.retrieved.values()))
            claim.grounding = resolved
            claim.rationale = rationale
            claim.tier = 2

        correct = claim.grounding is case.expected
        results.append((case, claim, escalated, correct))

    # Per-category precision/recall (predicted-label-matches-expected as the
    # only "positive" class per category; simple confusion-style report is
    # more useful than a single accuracy number on a 6-case set).
    by_category: dict[str, list[bool]] = {}
    for case, claim, escalated, correct in results:
        by_category.setdefault(case.category, []).append(correct)

    print(f"{'case':<45} {'category':<20} {'expected':<20} {'got':<20} {'tier':<5} {'ok'}")
    print("-" * 120)
    for case, claim, escalated, correct in results:
        mark = "PASS" if correct else "FAIL"
        print(
            f"{case.name:<45} {case.category:<20} {case.expected.value:<20} "
            f"{claim.grounding.value:<20} {claim.tier:<5} {mark}"
        )

    print()
    total = len(results)
    total_correct = sum(1 for *_r, correct in results if correct)
    print(f"Overall: {total_correct}/{total} correct ({total_correct / total:.0%})")
    print()
    print(f"{'category':<20} {'n':<5} {'correct':<8} {'recall'}")
    for cat, outcomes in sorted(by_category.items()):
        n = len(outcomes)
        c = sum(outcomes)
        print(f"{cat:<20} {n:<5} {c:<8} {c / n:.0%}")

    escalation_counts = Counter(escalated for *_r, escalated, _c in results)
    print(f"\nEscalated to Tier-2 judge: {escalation_counts.get(True, 0)}/{total}")

    if total_correct < total:
        print("\nFAIL: not all curated cases resolved correctly")
        return 1
    print("\nPASS: all curated cases resolved correctly")
    return 0


if __name__ == "__main__":
    sys.exit(run())

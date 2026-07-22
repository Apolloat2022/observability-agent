"""Deliberately does NOT eagerly import `.node` at package level.

`checker/node.py` imports `from ..interfaces import assemble_verdict` (a real
runtime dependency, not just a type hint). `interfaces.py` in turn imports
`from .checker.schema import ...` to build its Protocol signatures -- which
requires initializing this very `checker` package first. If this __init__
also eagerly imported `.node`, that would create:

    interfaces.py -> checker/__init__.py -> checker/node.py -> interfaces.py

a circular import that only "worked" by accident when some OTHER module
happened to fully load `obsvagent.interfaces` (or `obsvagent.checker.node`)
first, priming sys.modules before the cycle could bite -- e.g. pytest's test
collection order in this repo's own suite. A fresh process importing nothing
but `obsvagent.middleware` (exactly what a consuming app does first) hit it
immediately: `ImportError: cannot import name 'GroundingChecker' from
partially initialized module 'obsvagent.interfaces'`.

`.judge` and `.tier1` do not import `..interfaces` at all and stay eager
here. Import `CheckerNode` via `obsvagent.checker.node` directly.
"""
from .judge import JUDGE_MODEL, AnthropicJudge, build_prompt, parse_verdict
from .schema import (
    Action,
    CheckerVerdict,
    ClaimVerdict,
    Grounding,
    Thresholds,
    Verdict,
    decide_claim,
    needs_judge,
    roll_up,
)
from .tier1 import Tier1GroundingChecker, extract_citations, lexical_similarity, split_claims

__all__ = [
    "Grounding",
    "Action",
    "Verdict",
    "Thresholds",
    "ClaimVerdict",
    "CheckerVerdict",
    "needs_judge",
    "decide_claim",
    "roll_up",
    "Tier1GroundingChecker",
    "split_claims",
    "extract_citations",
    "lexical_similarity",
    "AnthropicJudge",
    "JUDGE_MODEL",
    "build_prompt",
    "parse_verdict",
]

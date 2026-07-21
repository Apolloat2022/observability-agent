"""Regression test for a real circular-import bug found while wiring the
first real consuming app: `obsvagent.middleware` (or several other common
first-imports) raised ImportError in a FRESH process, even though the
package's own pytest suite always passed -- because some OTHER test file's
import order happened to prime sys.modules first, masking the cycle.
`from obsvagent.checker.node import CheckerNode` in test_checker_node.py
(collected alphabetically before test_middleware.py) was enough to hide it
for every prior test run in this repo.

Each case below spawns a genuinely fresh Python subprocess -- no shared
sys.modules with pytest's own import history -- so this test cannot be
accidentally masked by collection order the way the bug itself was.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# Every module a real consuming app plausibly imports FIRST, in isolation.
_ENTRY_POINTS = [
    "obsvagent.middleware",
    "obsvagent.gateway",
    "obsvagent.graph",
    "obsvagent.interfaces",
    "obsvagent.checker.node",
    "obsvagent.checker.judge",
    "obsvagent.checker.tier1",
    "obsvagent.monitoring.guard",
    "obsvagent.ledger_writer",
    "obsvagent.db",
    "obsvagent.api.main",
]


@pytest.mark.parametrize("module", _ENTRY_POINTS)
def test_fresh_process_import(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"fresh-process `import {module}` failed:\n{result.stderr}"
    )

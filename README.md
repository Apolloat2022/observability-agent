# obsvagent

Shared observability, RAG-checker, and compliance-audit layer for the `C:\Workspace\Projects`
ecosystem (FastAPI · LangGraph · Neon · multi-LLM). One package every repo imports instead of
re-implementing telemetry.

- **Design:** `../OBSERVABILITY_AGENT_BLUEPRINT.md`
- **Build plan / handoff:** `HANDOFF.md`
- **Status:** Opus-owned **contracts** are complete and tested; implementation phases are
  delegated to Sonnet (see HANDOFF).

## Contracts (done, frozen)
Telemetry schema + reducer, ULID ids, OTel attribute keys, Checker verdict schema + thresholds,
enterprise transition specs, alert taxonomy, audit hash-chain. All dependency-free.

```bash
pip install -e ".[dev]"
pytest -q            # tests/test_contracts.py — must stay green
```

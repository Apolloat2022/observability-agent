# HANDOFF.md — obsvagent build handoff (Opus → Sonnet)

**Read first:** `../OBSERVABILITY_AGENT_BLUEPRINT.md` (the full strategy). This file is the
executable contract + your build order.

## What Opus already built (the contracts — do not modify without flagging)

These files are DONE, typed, dependency-free, and covered by `tests/test_contracts.py`
(7 tests, all green — run them before and after every phase; they must stay green).

| File | What it pins | Blueprint § |
|------|--------------|-------------|
| `obsvagent/ids.py` | ULID trace-id format; monotonic `new_audit_id` for the ledger | 1.2, 4.2 |
| `obsvagent/otel.py` | Exact OTel/GenAI + `obsv.*` attribute keys. **Never hand-type a key — import these.** | 1.3, 1.4 |
| `obsvagent/schema.py` | `Telemetry` state + `telemetry_reducer` (append/sum/set-once) + `Flag` vocab | 1.2 |
| `obsvagent/checker/schema.py` | Grounding enum, verdict schema, `Thresholds`, `needs_judge`/`decide_claim`/`roll_up` | 2.2, 2.3 |
| `obsvagent/monitoring/workflows.py` | Enterprise transition specs + `check_conformance` | 3.2 |
| `obsvagent/alerting/model.py` | Baseline model, `Severity`, full signal catalog, financial-route set | 5.1, 5.2 |
| `obsvagent/ledger.py` | Canonical audit record, JCS canonicalization, hash-chain + `verify_chain` | 4.1, 4.2 |
| `obsvagent/interfaces.py` | **Protocols you must implement.** Your classes must satisfy these signatures. | — |
| `obsvagent/pricing.yaml` | Seed pricing (VERIFY before billing use) | 1.4 |

**Rule:** the six Opus-owned decisions (attribute contract, reducer semantics, checker
thresholds, transition specs, alert taxonomy, canonicalization/chain formula) are frozen.
If a phase seems to need a change to one, STOP and raise it — don't edit silently.

## Environment notes
- Package targets **Python 3.11+**; contracts are import-clean on the 3.14 interpreter present here.
- Contracts have **zero runtime deps** on purpose (hot-path import stays light). Add deps only
  under the `pyproject.toml` extras (`otel`, `checker`, `db`, `alerting`, `dev`) per phase.
- `pytest` isn't installed yet — `pip install -e ".[dev]"` in Phase 0, then `pytest -q`.
- This is a fresh package, not yet a git repo. Init + first commit is a Phase 0 task.

## Your build order (each phase is independently shippable + testable)

Legend: 🟢 you own · 🟡 you build, Opus reviews before merge.

### Phase 0 — Foundations 🟢
- `pip install -e ".[dev]"`; wire ruff + mypy + pytest CI (match the conventions in
  `../riskguard-ai`). Init git, first commit.
- Build `obsvagent/cost.py` implementing `interfaces.CostCalculator` over `pricing.yaml`
  (effective-date selection: newest entry with `effective_date <= at_ms`). Unit test per provider.
- **Done when:** `pytest -q` green including a cost test; `mypy obsvagent` clean.

### Phase 1 — Telemetry capture 🟢 (🟡 for the gateway)
- **Pre-check (do first):** confirm the Tempo + Prometheus + Grafana services fit the target compose
  setups — free host ports (Tempo OTLP 4317/4318, Grafana 3000, Prometheus 9090), memory/volume
  budget, and no collision with each repo's existing `docker-compose.yml`. Report conflicts to the
  user before wiring the financial repos.
- `obsvagent/middleware.py`: FastAPI ASGI middleware — honor inbound `traceparent`, bind
  `trace_id` via `contextvars`, time with `perf_counter`, set `X-Trace-Id`, emit ONE event.
- `obsvagent/sink.py`: implement `interfaces.EventSink` — lock-free ring buffer + async
  `drain()` to an OTLP `BatchSpanProcessor` (512 batch / 5s flush), **target = self-hosted Tempo**
  (add Tempo + Prometheus + Grafana to the compose stack). Never block the request.
- `obsvagent/gateway.py` 🟡: implement `interfaces.LLMGateway` for Anthropic/Gemini/DeepSeek.
  Map raw usage fields → `otel.GEN_AI_USAGE_*`; normalize provider → `otel.PROVIDERS`.
  **Cross-check Anthropic fields against the `claude-api` skill.**
- `obsvagent/graph.py`: LangGraph node decorator/callback that appends to `node_path` and
  emits a transition span (`otel.OBSV_NODE_*`).
- **Done when:** a sample request yields a full span tree in Tempo/Grafana; benchmark shows
  **middleware p99 < 1 ms** (include the bench).

### Phase 2 — Neon schema & storage 🟡
- Migrations: `obsv_events` (day-partitioned), `obsv_traces`, `obsv_payloads` (TTL),
  `obsv_audit` (**INSERT-only; REVOKE UPDATE, DELETE from the app role** — separate scoped
  role for retention). This grant model is the review gate.
- DAO + the batched async writer that drains the ring buffer.
- **Done when:** app role cannot UPDATE/DELETE `obsv_audit` (test proves the grant); writer
  survives a backpressure burst without dropping on the hot path.

### Phase 3 — Checker Agent 🟢 (🟡 for the judge)
- `obsvagent/checker/tier1.py`: implement `interfaces.GroundingChecker` — claim splitting,
  embedding/lexical overlap vs cited chunks, citation-integrity (fabricated id → that enum).
  Leave ambiguous-band claims (`needs_judge`) at `PARTIAL`.
- `obsvagent/checker/judge.py` 🟡: implement `interfaces.Judge` using **`claude-haiku-4-5`**
  (pinned in config) — constrained NLI prompt, called ONLY for `needs_judge` claims. Robust
  parse → `Grounding` + rationale.
- `obsvagent/checker/node.py`: mode per route via `alerting.model.FINANCIAL_ROUTES` — **financial
  = inline (fail-closed), else shadow**; on shadow routes `CONTRADICTED`/`FABRICATED_CITATION`
  short-circuit to a synchronous block. Call `interfaces.assemble_verdict`; on non-PASS write an
  audit-queue item; add `verdict.flags` to telemetry.
- **Done when:** curated eval set (supported / unsupported / contradicted / fabricated-citation)
  runs with a precision/recall report. Thresholds come from `Thresholds` — don't inline numbers.

### Phase 4 — Stateful monitoring 🟢
- `obsvagent/monitoring/guard.py`: in-graph guard — step budget (`WorkflowSpec.max_steps`),
  `(node, state_hash)` cycle detection, wall-clock + `cost_usd` ceilings → set the matching
  `schema.Flag` and abort.
- Wire `workflows.check_conformance` as a post-node hook; deviation → `Flag.ENTERPRISE_LOGIC_DEVIATION`
  + CRITICAL alert.
- **Done when:** injected loop AND injected illegal transition are both caught + audited in tests.

### Phase 5 — Compliance ledger 🟡
- `obsvagent/ledger_writer.py`: implement `interfaces.LedgerWriter` — INSERT-only, **fail-closed**,
  holds the per-project lock, calls `ledger.seal()` under it (id order == chain order).
- External anchor writer: **hourly chain-head hash → locked Neon branch (distinct INSERT-only role)
  for every project; ADD an on-chain head-commit in `stablecoin-orchestrator-alpha` only.** Anchor
  the head hash, never records. Review gate.
- `obsvagent/cli/verify_ledger.py`: the `verify-ledger` entrypoint (already declared in
  `pyproject.toml`) using `ledger.verify_chain`; nightly CI + tombstone/retention job.
- **Done when:** tamper test — mutating any historical row is caught by `verify-ledger`
  (the contract test already proves the core; you add the DB-backed walk).

### Phase 6 — Alerting 🟢
- `obsvagent/alerting/baselines.py`: compute/refresh `Baseline` per (model, route) from `obsv_events`.
- `obsvagent/alerting/evaluators.py`: one `eval_<key>` pure function per `SignalSpec.rule` in the
  catalog (tests per function). PSI/KL drift in `obsvagent/alerting/drift.py`.
- `obsvagent/alerting/dispatch.py`: implement `interfaces.AlertDispatcher` — debounce +
  `require_windows` confirmation; every `Alert` carries a `trace_id` deep-link.
- **Done when:** each signal has a passing evaluator test; a synthetic latency regression fires
  exactly one WARN after `require_windows`.

### Phase 7 — Human-in-the-loop UI 🟢 (🟡 for the endpoints)
- Next.js `/observability` route: trace list, reasoning-path graph (color by latency/cost,
  red = deviation), cost/latency panels. Audit Review Queue (confirm hallucination /
  false-positive / fix-source) writing reviewer decisions back (feeds threshold tuning).
- Read-only FastAPI endpoints 🟡: authz + tenant scoping, **no raw-payload/PII leakage**. Review gate.
- **Done when:** a FAIL verdict appears in the queue and a reviewer decision persists.

## Roll-out order
Integrate into `../RAG-LLM-Project-showcase` first (best Checker testbed) → `../deep-agent-ai`
→ the financial pair `../riskguard-ai` + `../stablecoin-orchestrator-alpha` (these additionally
enable Phase 5 ledger + inline Checker).

## Decisions — resolved (build to these; don't re-open without the user)
1. **Collector — self-hosted Grafana stack (Tempo + Prometheus + Grafana), Docker services in the
   existing compose.** OTLP → Tempo natively, no adapter. Chosen for data residency: financial repos
   never ship prompts/context to a SaaS. Optionally add self-hosted Langfuse *alongside* Tempo for
   LLM-semantic debugging. **Never** managed Grafana Cloud or cloud Langfuse for financial repos.
2. **Ledger anchor — locked Neon branch for all projects; ADD on-chain head-commit for
   `stablecoin-orchestrator-alpha` only.** Anchor the hourly chain-*head hash* (32 bytes), never
   records. Neon branch uses a distinct INSERT-only role the app can't reach. No WORM store.
3. **Tier-2 judge — `claude-haiku-4-5`, pinned in config.** Strongest constrained-NLI /
   output-contract adherence of the three; gives cross-family independence on the Gemini/DeepSeek
   generation routes. Verify id + pricing against the `claude-api` skill. Fallback to Gemini Flash on
   non-financial routes only if judge volume makes cost dominate (`cost_per_request_spike`).
4. **Checker mode — financial routes inline (fail-closed); everything else shadow.** Key the flag off
   `alerting.model.FINANCIAL_ROUTES`. On shadow routes, `CONTRADICTED` and `FABRICATED_CITATION`
   still short-circuit to a synchronous block (cheap, usually Tier-1, never acceptable to ship).

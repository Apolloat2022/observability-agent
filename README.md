# obsvagent

Shared observability, RAG-hallucination-checking, and compliance-audit layer for the
`C:\Workspace\Projects` ecosystem (FastAPI · LangGraph · Neon · multi-LLM) — one package every
app imports instead of reinventing telemetry.

- **Full architecture, use cases, current status, and remaining work:** [`docs/OVERVIEW.md`](docs/OVERVIEW.md) — read this first.
- **Original design brief:** `../OBSERVABILITY_AGENT_BLUEPRINT.md`
- **Build plan (all 8 phases now complete):** [`HANDOFF.md`](HANDOFF.md)
- **Branch protection on `main`:** [`docs/BRANCH_PROTECTION.md`](docs/BRANCH_PROTECTION.md)

## Quick start

```bash
# Python package (contracts + telemetry + checker + ledger + alerting + API)
pip install -e ".[otel,checker,db,alerting,api,dev]"
pytest -q                       # 130 tests: 105 offline + 25 live-Neon integration

# Apply Neon migrations + provision least-privileged roles (needs DATABASE_URL in .env)
python scripts/apply_migrations.py

# Observability collector (Tempo + Prometheus + Grafana)
docker compose -f docker/docker-compose.observability.yml up -d

# API backend
uvicorn obsvagent.api.main:app --reload --port 8000

# Web UI
cd web && npm install && npm run dev   # http://localhost:3000/observability
```

See `docs/OVERVIEW.md` §7 for what's genuinely live vs. what's still a placeholder before
pointing this at real production traffic.

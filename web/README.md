# obsvagent web

The Phase 7 human-in-the-loop UI: trace list, reasoning-path graph, and the
Checker's Audit Review Queue. Talks to the FastAPI backend in
`../obsvagent/api/main.py`.

## Run locally

```bash
# Backend (from repo root, with the `api` + `db` extras installed):
uvicorn obsvagent.api.main:app --reload --port 8000

# Frontend:
cp .env.local.example .env.local   # then adjust if needed
npm install
npm run dev
```

Visit `http://localhost:3000/observability`.

## Pages

- `/observability` — trace list with cost/latency/token summary panels.
- `/observability/[traceId]` — the reasoning path (node chain colored by
  relative latency; red outline when the trace carries a deviation flag) and
  its raw event list.
- `/observability/review` — the Audit Review Queue: pending non-PASS Checker
  verdicts, with claim-level grounding detail and one-click reviewer
  decisions (confirm hallucination / false positive / fix source).

See `lib/api.ts` for the security note on `NEXT_PUBLIC_API_KEY` — it's a
dev-only pattern; production should proxy through a server-side route
handler instead of shipping the key to the browser.

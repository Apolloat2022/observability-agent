// API client for the obsvagent FastAPI backend (obsvagent/api/main.py).
//
// SECURITY NOTE: NEXT_PUBLIC_API_KEY, if set, is bundled into client-side JS
// and visible to anyone who opens devtools -- fine for local dev against the
// backend's own placeholder auth, NOT acceptable for production. A
// production deployment should proxy these calls through Next.js server-side
// route handlers so the real API key never reaches the browser. This mirrors
// the backend's own "auth is a placeholder, flagged for review" note.

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Trace = {
  trace_id: string;
  route: string;
  tenant: string;
  started_at: string | null;
  ended_at: string | null;
  total_cost_usd: number;
  total_tokens_prompt: number;
  total_tokens_completion: number;
  node_path: string[];
  flags: string[];
  checker_verdict: string | null;
};

export type TraceEvent = {
  id: string;
  span_name: string;
  start_ns: number | null;
  end_ns: number | null;
  latency_ms: number | null;
  attributes: Record<string, unknown>;
};

export type ReviewClaim = {
  text: string;
  cited: number[];
  grounding: string;
  score: number;
  tier: number;
  rationale: string;
  action: string;
};

export type ReviewItem = {
  id: string;
  trace_id: string;
  route: string;
  tenant: string | null;
  verdict: string;
  unsupported_ratio: number;
  claims: ReviewClaim[];
  created_at: string;
};

export type Decision = "confirmed_hallucination" | "false_positive" | "fixed_source";

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API error ${status}: ${detail}`);
  }
}

function buildHeaders(tenant?: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (tenant) h["X-Tenant-Id"] = tenant;
  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) h["X-API-Key"] = apiKey;
  return h;
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON -- keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchTraces(tenant: string, route?: string): Promise<Trace[]> {
  const url = new URL(`${API_BASE}/api/traces`);
  if (route) url.searchParams.set("route", route);
  const res = await fetch(url, { headers: buildHeaders(tenant), cache: "no-store" });
  return unwrap<Trace[]>(res);
}

export async function fetchTrace(tenant: string, traceId: string): Promise<Trace> {
  const res = await fetch(`${API_BASE}/api/traces/${encodeURIComponent(traceId)}`, {
    headers: buildHeaders(tenant),
    cache: "no-store",
  });
  return unwrap<Trace>(res);
}

export async function fetchTraceEvents(tenant: string, traceId: string): Promise<TraceEvent[]> {
  const res = await fetch(`${API_BASE}/api/traces/${encodeURIComponent(traceId)}/events`, {
    headers: buildHeaders(tenant),
    cache: "no-store",
  });
  return unwrap<TraceEvent[]>(res);
}

export async function fetchReviewQueue(route?: string): Promise<ReviewItem[]> {
  const url = new URL(`${API_BASE}/api/review-queue`);
  if (route) url.searchParams.set("route", route);
  const res = await fetch(url, { headers: buildHeaders(), cache: "no-store" });
  return unwrap<ReviewItem[]>(res);
}

export async function submitDecision(itemId: string, decision: Decision, actor: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/review-queue/${encodeURIComponent(itemId)}/decision`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify({ decision, actor }),
  });
  await unwrap<{ status: string }>(res);
}

export { ApiError };

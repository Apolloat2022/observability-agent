"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiError, fetchTrace, fetchTraceEvents, type Trace, type TraceEvent } from "../../../lib/api";

/** Latency -> color on a green -> amber -> red gradient, relative to the
 * slowest node in this trace (so the coloring is meaningful per-trace
 * regardless of absolute latency scale across different routes). */
function latencyColor(latencyMs: number | null, maxLatencyMs: number): string {
  if (latencyMs === null || maxLatencyMs <= 0) return "var(--border)";
  const t = Math.min(latencyMs / maxLatencyMs, 1);
  if (t < 0.5) return "var(--green)";
  if (t < 0.8) return "var(--amber)";
  return "var(--red)";
}

const DEVIATION_FLAGS = new Set(["enterprise_logic_deviation", "loop_suspected"]);

export default function TraceDetailPage() {
  const params = useParams<{ traceId: string }>();
  const traceId = decodeURIComponent(params.traceId);
  const [tenant, setTenant] = useState("default");
  const [trace, setTrace] = useState<Trace | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([fetchTrace(tenant, traceId), fetchTraceEvents(tenant, traceId)])
      .then(([t, e]) => {
        if (!cancelled) {
          setTrace(t);
          setEvents(e);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.detail : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant, traceId]);

  const nodeEventByName = useMemo(() => {
    const map = new Map<string, TraceEvent>();
    for (const e of events) {
      const match = /^node (.+)$/.exec(e.span_name);
      if (match) map.set(match[1], e);
    }
    return map;
  }, [events]);

  const maxLatency = useMemo(
    () => Math.max(0, ...events.map((e) => e.latency_ms ?? 0)),
    [events],
  );

  const isDeviated = trace?.flags?.some((f) => DEVIATION_FLAGS.has(f)) ?? false;

  return (
    <div>
      <p>
        <Link href="/observability">&larr; Traces</Link>
      </p>
      <h1 style={{ wordBreak: "break-all" }}>{traceId}</h1>

      <label style={{ display: "block", marginBottom: 16 }}>
        Tenant: <input type="text" value={tenant} onChange={(e) => setTenant(e.target.value)} />
      </label>

      {loading && <p style={{ color: "var(--text-dim)" }}>Loading…</p>}
      {error && <p style={{ color: "var(--red)" }}>Error: {error}</p>}

      {trace && (
        <>
          <div className="stat-row">
            <div className="panel stat-tile">
              <div className="label">Route</div>
              <div className="value" style={{ fontSize: 16 }}>
                {trace.route}
              </div>
            </div>
            <div className="panel stat-tile">
              <div className="label">Cost</div>
              <div className="value">${(trace.total_cost_usd ?? 0).toFixed(4)}</div>
            </div>
            <div className="panel stat-tile">
              <div className="label">Tokens</div>
              <div className="value">
                {(trace.total_tokens_prompt ?? 0) + (trace.total_tokens_completion ?? 0)}
              </div>
            </div>
            <div className="panel stat-tile">
              <div className="label">Verdict</div>
              <div className="value" style={{ fontSize: 16 }}>
                {trace.checker_verdict ?? "—"}
              </div>
            </div>
          </div>

          {isDeviated && (
            <div className="panel" style={{ borderColor: "var(--red)", marginBottom: 20 }}>
              <strong style={{ color: "var(--red)" }}>Deviation detected:</strong>{" "}
              {trace.flags.filter((f) => DEVIATION_FLAGS.has(f)).join(", ")}
            </div>
          )}

          <h2>Reasoning path</h2>
          <p style={{ color: "var(--text-dim)" }}>
            Node chips are colored by relative latency within this trace (green = fast, red = slow).
            A red outline marks a node inside a flagged loop or an illegal transition.
          </p>
          <div className="panel" style={{ display: "flex", flexWrap: "wrap", alignItems: "center" }}>
            {trace.node_path.length === 0 && <span style={{ color: "var(--text-dim)" }}>No nodes recorded.</span>}
            {trace.node_path.map((node, i) => {
              const event = nodeEventByName.get(node);
              const latency = event?.latency_ms ?? null;
              return (
                <span key={`${node}-${i}`} style={{ display: "flex", alignItems: "center" }}>
                  <span
                    className="node-chip"
                    style={{
                      borderColor: isDeviated ? "var(--red)" : undefined,
                      boxShadow: `inset 0 -3px 0 0 ${latencyColor(latency, maxLatency)}`,
                    }}
                    title={latency !== null ? `${latency.toFixed(1)} ms` : "no timing data"}
                  >
                    {node}
                    {latency !== null && (
                      <span style={{ color: "var(--text-dim)", marginLeft: 6 }}>
                        {latency.toFixed(0)}ms
                      </span>
                    )}
                  </span>
                  {i < trace.node_path.length - 1 && <span className="node-arrow">&rarr;</span>}
                </span>
              );
            })}
          </div>

          <h2 style={{ marginTop: 32 }}>Events</h2>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th>Span</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td>{e.span_name}</td>
                    <td>{e.latency_ms !== null ? `${e.latency_ms.toFixed(1)} ms` : "—"}</td>
                  </tr>
                ))}
                {events.length === 0 && (
                  <tr>
                    <td colSpan={2} style={{ color: "var(--text-dim)" }}>
                      No events recorded for this trace.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ApiError, fetchTraces, type Trace } from "../../lib/api";

function verdictBadgeClass(verdict: string | null): string {
  if (verdict === "PASS") return "badge badge-pass";
  if (verdict === "REVIEW") return "badge badge-review";
  if (verdict === "FAIL") return "badge badge-fail";
  return "badge";
}

export default function ObservabilityPage() {
  const [tenant, setTenant] = useState("default");
  const [route, setRoute] = useState("");
  const [traces, setTraces] = useState<Trace[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTraces(tenant, route || undefined)
      .then((data) => {
        if (!cancelled) setTraces(data);
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
  }, [tenant, route]);

  const totals = useMemo(() => {
    const totalCost = traces.reduce((sum, t) => sum + (t.total_cost_usd ?? 0), 0);
    const totalTokens = traces.reduce(
      (sum, t) => sum + (t.total_tokens_prompt ?? 0) + (t.total_tokens_completion ?? 0),
      0,
    );
    const flagged = traces.filter((t) => t.flags?.length > 0).length;
    return { totalCost, totalTokens, flagged, count: traces.length };
  }, [traces]);

  return (
    <div>
      <h1>Traces</h1>

      <div style={{ display: "flex", gap: 12, marginBottom: 20, alignItems: "center" }}>
        <label>
          Tenant:{" "}
          <input type="text" value={tenant} onChange={(e) => setTenant(e.target.value)} />
        </label>
        <label>
          Route filter:{" "}
          <input
            type="text"
            value={route}
            placeholder="(all routes)"
            onChange={(e) => setRoute(e.target.value)}
          />
        </label>
      </div>

      <div className="stat-row">
        <div className="panel stat-tile">
          <div className="label">Traces</div>
          <div className="value">{totals.count}</div>
        </div>
        <div className="panel stat-tile">
          <div className="label">Total cost</div>
          <div className="value">${totals.totalCost.toFixed(4)}</div>
        </div>
        <div className="panel stat-tile">
          <div className="label">Total tokens</div>
          <div className="value">{totals.totalTokens.toLocaleString()}</div>
        </div>
        <div className="panel stat-tile">
          <div className="label">Flagged</div>
          <div className="value" style={{ color: totals.flagged > 0 ? "var(--red)" : undefined }}>
            {totals.flagged}
          </div>
        </div>
      </div>

      {error && <p style={{ color: "var(--red)" }}>Error: {error}</p>}
      {loading && <p style={{ color: "var(--text-dim)" }}>Loading…</p>}

      {!loading && !error && traces.length === 0 && (
        <p style={{ color: "var(--text-dim)" }}>
          No traces found for tenant &quot;{tenant}&quot;{route ? ` / route "${route}"` : ""}.
        </p>
      )}

      {traces.length > 0 && (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Trace</th>
                <th>Route</th>
                <th>Started</th>
                <th>Cost</th>
                <th>Tokens</th>
                <th>Nodes</th>
                <th>Flags</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <tr key={t.trace_id}>
                  <td>
                    <Link href={`/observability/${encodeURIComponent(t.trace_id)}`}>{t.trace_id}</Link>
                  </td>
                  <td>{t.route}</td>
                  <td>{t.started_at ? new Date(t.started_at).toLocaleString() : "—"}</td>
                  <td>${(t.total_cost_usd ?? 0).toFixed(4)}</td>
                  <td>{(t.total_tokens_prompt ?? 0) + (t.total_tokens_completion ?? 0)}</td>
                  <td>{t.node_path?.length ?? 0}</td>
                  <td>
                    {t.flags?.length > 0 ? (
                      <span style={{ color: "var(--red)" }}>{t.flags.join(", ")}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <span className={verdictBadgeClass(t.checker_verdict)}>
                      {t.checker_verdict ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, fetchReviewQueue, submitDecision, type Decision, type ReviewItem } from "../../../lib/api";

function verdictBadgeClass(verdict: string): string {
  if (verdict === "PASS") return "badge badge-pass";
  if (verdict === "REVIEW") return "badge badge-review";
  return "badge badge-fail";
}

function groundingColor(grounding: string): string {
  if (grounding === "SUPPORTED") return "var(--green)";
  if (grounding === "CONTRADICTED" || grounding === "FABRICATED_CITATION") return "var(--red)";
  return "var(--amber)";
}

const DECISIONS: { key: Decision; label: string }[] = [
  { key: "confirmed_hallucination", label: "Confirm hallucination" },
  { key: "false_positive", label: "False positive" },
  { key: "fixed_source", label: "Fix source" },
];

export default function ReviewQueuePage() {
  const [route, setRoute] = useState("");
  const [actor, setActor] = useState("reviewer@example.com");
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [justResolved, setJustResolved] = useState<{ id: string; decision: Decision } | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    fetchReviewQueue(route || undefined)
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.detail : String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route]);

  async function handleDecision(itemId: string, decision: Decision) {
    setSubmittingId(itemId);
    setError(null);
    try {
      await submitDecision(itemId, decision, actor);
      setJustResolved({ id: itemId, decision });
      setItems((prev) => prev.filter((i) => i.id !== itemId));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setSubmittingId(null);
    }
  }

  return (
    <div>
      <h1>Audit Review Queue</h1>
      <p style={{ color: "var(--text-dim)" }}>
        Non-PASS Checker verdicts land here for human review. A decision here feeds back into
        threshold tuning (blueprint §2.4).
      </p>

      <div style={{ display: "flex", gap: 12, marginBottom: 20, alignItems: "center" }}>
        <label>
          Route filter: <input type="text" value={route} placeholder="(all routes)" onChange={(e) => setRoute(e.target.value)} />
        </label>
        <label>
          Reviewer: <input type="text" value={actor} onChange={(e) => setActor(e.target.value)} />
        </label>
        <button onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {justResolved && (
        <div className="panel" style={{ borderColor: "var(--green)", marginBottom: 16 }}>
          Recorded <strong>{justResolved.decision}</strong> for item {justResolved.id}. It has left the pending
          queue.
        </div>
      )}
      {error && <p style={{ color: "var(--red)" }}>Error: {error}</p>}
      {loading && <p style={{ color: "var(--text-dim)" }}>Loading…</p>}
      {!loading && !error && items.length === 0 && (
        <p style={{ color: "var(--text-dim)" }}>Nothing pending review.</p>
      )}

      {items.map((item) => (
        <div key={item.id} className="panel" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <span className={verdictBadgeClass(item.verdict)}>{item.verdict}</span>{" "}
              <Link href={`/observability/${encodeURIComponent(item.trace_id)}`}>{item.trace_id}</Link>
              <span style={{ color: "var(--text-dim)" }}> · {item.route}</span>
            </div>
            <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
              unsupported ratio: {(item.unsupported_ratio * 100).toFixed(0)}%
            </span>
          </div>

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Grounding</th>
                <th>Score</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {item.claims
                .filter((c) => c.grounding !== "SUPPORTED")
                .map((c, i) => (
                  <tr key={i}>
                    <td style={{ whiteSpace: "normal", maxWidth: 320 }}>{c.text}</td>
                    <td style={{ color: groundingColor(c.grounding) }}>{c.grounding}</td>
                    <td>{c.score.toFixed(2)}</td>
                    <td style={{ whiteSpace: "normal", maxWidth: 320, color: "var(--text-dim)" }}>
                      {c.rationale || "—"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            {DECISIONS.map((d) => (
              <button key={d.key} disabled={submittingId === item.id} onClick={() => handleDecision(item.id, d.key)}>
                {submittingId === item.id ? "Submitting…" : d.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

"""DAO layer over the obsv schema (Phase 2, 🟡). Sync psycopg — used for
one-off queries (alerting/baselines consumers, the Phase 5 verify-ledger
CLI, Phase 7 read endpoints) and by the migration/provisioning scripts. The
batched async hot-path writer is db/writer.py, which uses its own async
connection.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from ..alerting.baselines import EventRow
from ..ledger import AuditRecord
from ..schema import Telemetry


class EventDAO:
    @staticmethod
    def fetch_window(
        conn: psycopg.Connection, *, route: str, since_iso: str, until_iso: str
    ) -> list[EventRow]:
        """Rows shaped for alerting.baselines.compute_baseline. Reads only
        the columns that map to EventRow fields, out of `attributes` jsonb."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    latency_ms,
                    (attributes->>'gen_ai.usage.output_tokens')::float AS completion_tokens,
                    (attributes->>'obsv.cost_usd')::float AS cost_usd,
                    COALESCE((attributes->>'http.status_code')::int >= 500, false) AS is_error,
                    attributes->>'obsv.checker.verdict' AS checker_verdict
                FROM obsv.obsv_events
                WHERE route = %s AND created_at >= %s AND created_at < %s
                """,
                (route, since_iso, until_iso),
            )
            rows: list[EventRow] = []
            for latency_ms, completion_tokens, cost_usd, is_error, checker_verdict in cur.fetchall():
                row: EventRow = {}
                if latency_ms is not None:
                    row["latency_ms"] = latency_ms
                if completion_tokens is not None:
                    row["completion_tokens"] = int(completion_tokens)
                if cost_usd is not None:
                    row["cost_usd"] = cost_usd
                row["is_error"] = bool(is_error)
                if checker_verdict is not None:
                    row["checker_verdict"] = checker_verdict
                rows.append(row)
            return rows


class TraceDAO:
    @staticmethod
    def upsert_from_telemetry(conn: psycopg.Connection, telemetry: Telemetry) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obsv.obsv_traces
                    (trace_id, route, tenant, started_at, total_cost_usd,
                     total_tokens_prompt, total_tokens_completion, node_path, flags, updated_at)
                VALUES (%s, %s, %s, to_timestamp(%s), %s, %s, %s, %s, %s, now())
                ON CONFLICT (trace_id) DO UPDATE SET
                    total_cost_usd = EXCLUDED.total_cost_usd,
                    total_tokens_prompt = EXCLUDED.total_tokens_prompt,
                    total_tokens_completion = EXCLUDED.total_tokens_completion,
                    node_path = EXCLUDED.node_path,
                    flags = EXCLUDED.flags,
                    updated_at = now()
                """,
                (
                    telemetry.get("trace_id"),
                    telemetry.get("route"),
                    telemetry.get("tenant"),
                    telemetry.get("started_at"),
                    telemetry.get("cost_usd", 0.0),
                    telemetry.get("token_usage", {}).get("prompt", 0),
                    telemetry.get("token_usage", {}).get("completion", 0),
                    telemetry.get("node_path", []),
                    telemetry.get("flags", []),
                ),
            )
        conn.commit()


class PayloadDAO:
    @staticmethod
    def insert(
        conn: psycopg.Connection,
        *,
        payload_id: str,
        trace_id: str,
        kind: str,
        content: str,
        content_hash: str,
        expires_at_iso: str | None = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obsv.obsv_payloads (id, trace_id, kind, content, content_hash, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (payload_id, trace_id, kind, content, content_hash, expires_at_iso),
            )
        conn.commit()

    @staticmethod
    def tombstone(conn: psycopg.Connection, payload_id: str) -> None:
        """Requires the obsv_retention role's UPDATE grant. Nulls `content`
        while keeping `content_hash` -- the record a claim was made stays
        provable without retaining the raw (possibly PII-bearing) text."""
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE obsv.obsv_payloads SET content = NULL, tombstoned_at = now() WHERE id = %s",
                (payload_id,),
            )
        conn.commit()

    @staticmethod
    def expired_ids(conn: psycopg.Connection) -> list[str]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM obsv.obsv_payloads WHERE expires_at < now() AND tombstoned_at IS NULL"
            )
            return [row[0] for row in cur.fetchall()]


_AUDIT_COLUMNS = (
    "audit_id", "trace_id", "project", "route", "actor", "logical_timestamp",
    "request_hash", "request_ptr", "context_hashes", "context_scores",
    "model", "model_version", "prompt_template_version", "parameters",
    "completion_hash", "completion_ptr", "checker_verdict", "final_decision",
    "payload_hash", "prev_chain_hash", "chain_hash",
)


def _audit_row_values(record: AuditRecord) -> tuple:
    return (
        record.audit_id, record.trace_id, record.project, record.route, record.actor,
        record.timestamp, record.request_hash, record.request_ptr,
        record.context_hashes, record.context_scores,
        record.model, record.model_version, record.prompt_template_version, Jsonb(record.parameters),
        record.completion_hash, record.completion_ptr, record.checker_verdict, record.final_decision,
        record.payload_hash, record.prev_chain_hash, record.chain_hash,
    )


@dataclass
class AuditDAO:
    """INSERT-only against obsv_audit -- by construction (no update/delete
    method exists here) as well as by DB grant (see migrations.py 0005)."""

    @staticmethod
    def insert(conn: psycopg.Connection, record: AuditRecord) -> None:
        columns = ", ".join(_AUDIT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_AUDIT_COLUMNS))
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO obsv.obsv_audit ({columns}) VALUES ({placeholders})",
                _audit_row_values(record),
            )
        conn.commit()

    @staticmethod
    def fetch_ordered(conn: psycopg.Connection, project: str) -> list[AuditRecord]:
        """Ordered by audit_id (monotonic ULID -- see ids.new_audit_id), the
        same order the hash chain was built in. Used by verify-ledger."""
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {", ".join(_AUDIT_COLUMNS)}
                FROM obsv.obsv_audit WHERE project = %s ORDER BY audit_id ASC
                """,
                (project,),
            )
            records = []
            for row in cur.fetchall():
                d = dict(zip(_AUDIT_COLUMNS, row))
                d["timestamp"] = d.pop("logical_timestamp").isoformat()
                records.append(AuditRecord(**d))
            return records

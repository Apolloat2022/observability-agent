"""Neon schema migrations (Phase 2, 🟡 review gate — grant model).

Everything lives under a dedicated `obsv` schema, namespaced away from
whatever else may be in the database. Two roles:

  obsv_app        - the running application. SELECT+INSERT on obsv_events,
                    obsv_traces (+UPDATE for rollup upserts), obsv_payloads.
                    On obsv_audit: SELECT+INSERT ONLY -- UPDATE/DELETE/TRUNCATE
                    are explicitly revoked. This is the security boundary the
                    hash-chain's tamper-evidence depends on.
  obsv_retention  - the (rare) retention/tombstone job. SELECT+DELETE on
                    obsv_events, SELECT+UPDATE on obsv_payloads (tombstone =
                    null out `content`, keep the hash). NO grants on
                    obsv_audit at all -- retention never touches the ledger;
                    audit rows are immutable forever, not just app-immutable.

obsv_events is day-partitioned via native Postgres declarative partitioning.
Partitions are created lazily by `ensure_events_partition()` (called from
db/writer.py before each day's first insert) rather than via pg_cron, since
pg_cron may not be enabled on every Postgres target -- this stays portable.
"""
from __future__ import annotations

import psycopg

Migration = tuple[str, str]

_MIGRATIONS: list[Migration] = [
    (
        "0001_schema_and_roles",
        """
        CREATE SCHEMA IF NOT EXISTS obsv;

        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'obsv_app') THEN
                CREATE ROLE obsv_app LOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'obsv_retention') THEN
                CREATE ROLE obsv_retention LOGIN;
            END IF;
        END $$;

        GRANT USAGE ON SCHEMA obsv TO obsv_app, obsv_retention;
        """,
    ),
    (
        "0002_obsv_events",
        """
        CREATE TABLE IF NOT EXISTS obsv.obsv_events (
            id text NOT NULL,
            trace_id text NOT NULL,
            route text,
            tenant text,
            span_name text NOT NULL,
            start_ns bigint,
            end_ns bigint,
            latency_ms double precision,
            attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);

        CREATE INDEX IF NOT EXISTS obsv_events_trace_id_idx ON obsv.obsv_events (trace_id);
        CREATE INDEX IF NOT EXISTS obsv_events_route_created_at_idx ON obsv.obsv_events (route, created_at);

        CREATE OR REPLACE FUNCTION obsv.ensure_events_partition(for_date date)
        RETURNS void AS $BODY$
        DECLARE
            partition_name text := 'obsv_events_' || to_char(for_date, 'YYYY_MM_DD');
            start_ts timestamptz := for_date::timestamptz;
            end_ts timestamptz := (for_date + 1)::timestamptz;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'obsv' AND c.relname = partition_name
            ) THEN
                EXECUTE format(
                    'CREATE TABLE obsv.%I PARTITION OF obsv.obsv_events FOR VALUES FROM (%L) TO (%L)',
                    partition_name, start_ts, end_ts
                );
            END IF;
        END;
        -- SECURITY DEFINER: obsv_app has only USAGE on schema obsv, not
        -- CREATE, so partition creation must run with the function owner's
        -- (neondb_owner's) privileges. `search_path` is pinned to prevent a
        -- SECURITY DEFINER search-path hijack.
        $BODY$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = obsv, pg_temp;

        GRANT SELECT, INSERT ON obsv.obsv_events TO obsv_app;
        GRANT EXECUTE ON FUNCTION obsv.ensure_events_partition(date) TO obsv_app;
        GRANT SELECT, DELETE ON obsv.obsv_events TO obsv_retention;
        """,
    ),
    (
        "0003_obsv_traces",
        """
        CREATE TABLE IF NOT EXISTS obsv.obsv_traces (
            trace_id text PRIMARY KEY,
            route text,
            tenant text,
            started_at timestamptz,
            ended_at timestamptz,
            total_cost_usd double precision NOT NULL DEFAULT 0,
            total_tokens_prompt integer NOT NULL DEFAULT 0,
            total_tokens_completion integer NOT NULL DEFAULT 0,
            node_path text[] NOT NULL DEFAULT '{}',
            flags text[] NOT NULL DEFAULT '{}',
            checker_verdict text,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS obsv_traces_route_idx ON obsv.obsv_traces (route);

        GRANT SELECT, INSERT, UPDATE ON obsv.obsv_traces TO obsv_app;
        """,
    ),
    (
        "0004_obsv_payloads",
        """
        CREATE TABLE IF NOT EXISTS obsv.obsv_payloads (
            id text PRIMARY KEY,
            trace_id text NOT NULL,
            kind text NOT NULL,
            content text,
            content_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz,
            tombstoned_at timestamptz
        );
        CREATE INDEX IF NOT EXISTS obsv_payloads_trace_id_idx ON obsv.obsv_payloads (trace_id);
        CREATE INDEX IF NOT EXISTS obsv_payloads_expires_at_idx
            ON obsv.obsv_payloads (expires_at) WHERE tombstoned_at IS NULL;

        GRANT SELECT, INSERT ON obsv.obsv_payloads TO obsv_app;
        GRANT SELECT, UPDATE ON obsv.obsv_payloads TO obsv_retention;
        """,
    ),
    (
        "0005_obsv_audit",
        """
        CREATE TABLE IF NOT EXISTS obsv.obsv_audit (
            audit_id text PRIMARY KEY,
            trace_id text NOT NULL,
            project text NOT NULL,
            route text NOT NULL,
            actor text NOT NULL,
            logical_timestamp timestamptz NOT NULL,
            request_hash text NOT NULL,
            request_ptr text NOT NULL,
            context_hashes text[] NOT NULL DEFAULT '{}',
            context_scores double precision[] NOT NULL DEFAULT '{}',
            model text NOT NULL,
            model_version text NOT NULL,
            prompt_template_version text NOT NULL,
            parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
            completion_hash text NOT NULL,
            completion_ptr text NOT NULL,
            checker_verdict text NOT NULL,
            final_decision text NOT NULL,
            payload_hash text NOT NULL,
            prev_chain_hash text NOT NULL,
            chain_hash text NOT NULL,
            inserted_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS obsv_audit_project_idx ON obsv.obsv_audit (project, inserted_at);
        CREATE INDEX IF NOT EXISTS obsv_audit_trace_id_idx ON obsv.obsv_audit (trace_id);

        GRANT SELECT, INSERT ON obsv.obsv_audit TO obsv_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON obsv.obsv_audit FROM obsv_app;
        REVOKE ALL ON obsv.obsv_audit FROM obsv_retention;
        """,
    ),
]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every not-yet-applied migration, in order, each in its own
    transaction. Returns the ids of migrations actually applied this call
    (empty if the schema was already up to date)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obsv_schema_migrations (
                id text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()

        cur.execute("SELECT id FROM obsv_schema_migrations")
        already_applied = {row[0] for row in cur.fetchall()}

    applied_now: list[str] = []
    for migration_id, sql in _MIGRATIONS:
        if migration_id in already_applied:
            continue
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("INSERT INTO obsv_schema_migrations (id) VALUES (%s)", (migration_id,))
        conn.commit()
        applied_now.append(migration_id)

    return applied_now

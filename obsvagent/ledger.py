"""Immutable audit-ledger contract (Opus-owned schema; writer is Sonnet+review).

Defines the canonical audit record and the tamper-evident hash-chain formula.
For financial-grade routes this subsystem is FAIL-CLOSED: if the audit write
fails, the decision does not ship.

Sonnet (Phase 5, 🟡) implements:
  * the INSERT-only Neon writer holding a per-project lock (id order == chain
    order — see ids.new_audit_id),
  * the external anchor (WORM / locked Neon branch / on-chain notary),
  * the `verify-ledger` CLI that re-walks the chain.
Sonnet does NOT change the canonicalization or the chain formula below — a change
there invalidates every historical record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

GENESIS_CHAIN_HASH = "0" * 64  # prev.chain_hash for the first record in a project


@dataclass
class AuditRecord:
    """One LLM interaction, binding request + context + model + decision.

    Raw payloads are NOT stored inline — only content hashes + pointers, so PII
    can be tombstoned later without breaking the chain (payload deleted, hash
    retained)."""
    audit_id: str            # monotonic ULID (ids.new_audit_id)
    trace_id: str
    project: str
    route: str
    actor: str               # user / tenant id
    timestamp: str           # UTC ISO-8601, monotonic-verified by the writer
    request_hash: str
    request_ptr: str         # object-store / obsv_payloads pointer
    context_hashes: list[str]        # retrieved chunk hashes, in ranked order
    context_scores: list[float]
    model: str
    model_version: str       # EXACT served build id (gen_ai.response.model)
    prompt_template_version: str
    parameters: dict         # temperature, top_p, ...
    completion_hash: str
    completion_ptr: str
    checker_verdict: str     # PASS | REVIEW | FAIL
    final_decision: str      # domain outcome (execute/reject/report/...)
    # chain fields (filled by the writer)
    payload_hash: str = ""
    prev_chain_hash: str = ""
    chain_hash: str = ""


def canonical_json(obj: dict) -> bytes:
    """RFC 8785 (JCS)-style canonical form: sorted keys, no whitespace, UTF-8.

    The same content hashes identically across Python and the TS client, so the
    ledger can be verified from either language.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _body(rec: AuditRecord) -> dict:
    """Record body EXCLUDING the chain fields (those derive from it)."""
    d = asdict(rec)
    for k in ("payload_hash", "prev_chain_hash", "chain_hash"):
        d.pop(k, None)
    return d


def payload_hash(rec: AuditRecord) -> str:
    return hashlib.sha256(canonical_json(_body(rec))).hexdigest()


def chain_hash(prev_chain_hash: str, this_payload_hash: str) -> str:
    """chain_hash = SHA-256(prev.chain_hash || payload_hash). Any retroactive
    edit or deletion breaks every subsequent link and is detectable."""
    return hashlib.sha256((prev_chain_hash + this_payload_hash).encode("ascii")).hexdigest()


def seal(rec: AuditRecord, prev_chain_hash: str) -> AuditRecord:
    """Compute and attach the chain fields. Called by the writer under lock."""
    rec.payload_hash = payload_hash(rec)
    rec.prev_chain_hash = prev_chain_hash
    rec.chain_hash = chain_hash(prev_chain_hash, rec.payload_hash)
    return rec


@dataclass
class ChainVerification:
    ok: bool
    checked: int = 0
    first_broken_id: str | None = None
    reason: str = ""


def verify_chain(records: list[AuditRecord]) -> ChainVerification:
    """Re-walk an ordered list of records and report the first broken link.
    Backs the `verify-ledger` CLI and the nightly CI integrity check."""
    prev = GENESIS_CHAIN_HASH
    for i, rec in enumerate(records):
        expected_payload = payload_hash(rec)
        if rec.payload_hash != expected_payload:
            return ChainVerification(False, i, rec.audit_id, "payload_hash mismatch (record edited)")
        if rec.prev_chain_hash != prev:
            return ChainVerification(False, i, rec.audit_id, "prev_chain_hash mismatch (record removed/reordered)")
        if rec.chain_hash != chain_hash(prev, rec.payload_hash):
            return ChainVerification(False, i, rec.audit_id, "chain_hash mismatch")
        prev = rec.chain_hash
    return ChainVerification(True, checked=len(records))

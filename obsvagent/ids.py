"""ULID generation — the trace-id format for the whole ecosystem.

CONTRACT (Opus-owned). Do not change the format without a migration:
every trace_id / audit id in obsv_events, obsv_traces, obsv_audit is a
26-char Crockford base32 ULID. ULIDs are lexicographically sortable by
creation time, so Neon range-scans by time need no separate index.

Dependency-free on purpose: this file is imported by the hot path.
"""
from __future__ import annotations

import os
import time

# Crockford base32 (no I, L, O, U).
_ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_LEN = 10   # 48-bit ms timestamp -> 10 chars
_RAND_LEN = 16   # 80-bit randomness  -> 16 chars


def new_ulid(now_ms: int | None = None) -> str:
    """Return a new 26-char ULID. Monotonic within a process is NOT
    guaranteed here; for the audit ledger use `new_audit_id` which the
    ledger writer serializes under its own lock (see checker/monitoring docs)."""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits

    out = bytearray(26)
    for i in range(_TIME_LEN - 1, -1, -1):
        out[i] = ord(_ENCODING[ts & 0x1F])
        ts >>= 5
    for i in range(25, _TIME_LEN - 1, -1):
        out[i] = ord(_ENCODING[rand & 0x1F])
        rand >>= 5
    return out.decode("ascii")


def ulid_time_ms(ulid: str) -> int:
    """Decode the millisecond timestamp embedded in a ULID."""
    ts = 0
    for ch in ulid[:_TIME_LEN]:
        ts = (ts << 5) | _ENCODING.index(ch.upper())
    return ts


# The audit ledger requires strictly increasing ids so the hash-chain order
# is unambiguous. Sonnet: the ledger writer (Phase 5) MUST call this under the
# same lock that appends to the chain, so id order == chain order.
_last_audit_ms = 0


def new_audit_id() -> str:
    """Monotonic ULID for audit records. NOT thread-safe by itself —
    callers hold the ledger lock (see obsvagent/ledger contract in HANDOFF.md)."""
    global _last_audit_ms
    now = int(time.time() * 1000)
    if now <= _last_audit_ms:
        now = _last_audit_ms + 1
    _last_audit_ms = now
    return new_ulid(now)

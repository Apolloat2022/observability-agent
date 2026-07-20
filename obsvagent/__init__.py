"""obsvagent — shared observability layer for the Projects ecosystem.

Opus-owned CONTRACTS (ids, schema, otel, checker.schema, monitoring.workflows,
alerting.model, ledger, interfaces) are frozen; build against them. Everything
else is implemented per the phased build order in HANDOFF.md.
"""
from __future__ import annotations

from .cost import CostCalculator, PricingTable, default_calculator
from .ids import new_audit_id, new_ulid, ulid_time_ms
from .schema import Flag, Telemetry, new_telemetry, telemetry_reducer

__all__ = [
    "new_ulid",
    "new_audit_id",
    "ulid_time_ms",
    "Telemetry",
    "telemetry_reducer",
    "new_telemetry",
    "Flag",
    "CostCalculator",
    "PricingTable",
    "default_calculator",
]

__version__ = "0.1.0"

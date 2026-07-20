"""AlertDispatcher — debounce + N-window confirmation (Phase 6, 🟢).
Implements interfaces.AlertDispatcher. `transport` is caller-supplied (a
Slack webhook POST, PagerDuty API call, generic HTTP send) — this module
owns only the debounce/confirmation state machine, no hard dependency on any
specific alerting service SDK (same pattern as gateway.py / judge.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .model import Alert, SignalSpec


@dataclass
class _IncidentState:
    consecutive_breaches: int = 0
    already_fired: bool = False


class Dispatcher:
    """Implements interfaces.AlertDispatcher (`dispatch`), plus `observe` —
    the actual debounce entry point. One instance per process; state is
    keyed by (signal_key, model, route) so different routes/models don't
    interfere with each other's streaks."""

    def __init__(self, transport: Callable[[Alert], None]) -> None:
        self._transport = transport
        self._state: dict[tuple[str, str, str], _IncidentState] = {}

    def observe(
        self,
        *,
        spec: SignalSpec,
        breached: bool,
        model: str,
        route: str,
        observed: float,
        threshold: float,
        trace_id: str | None = None,
        message: str = "",
    ) -> Alert | None:
        """Feed one window's evaluator result. Returns the Alert if THIS
        window caused a dispatch (require_windows consecutive breaches
        reached, and not already firing for this incident), else None.

        A clean (non-breaching) window resets the streak AND re-arms the
        incident, so the next breach streak fires again — classic hysteresis
        debounce, not a one-shot latch."""
        key = (spec.key, model, route)
        state = self._state.setdefault(key, _IncidentState())

        if not breached:
            state.consecutive_breaches = 0
            state.already_fired = False
            return None

        state.consecutive_breaches += 1
        if state.consecutive_breaches >= spec.require_windows and not state.already_fired:
            state.already_fired = True
            alert = Alert(
                signal_key=spec.key,
                severity=spec.severity,
                model=model,
                route=route,
                observed=observed,
                threshold=threshold,
                trace_id=trace_id,
                message=message or spec.description,
            )
            self.dispatch(alert)
            return alert
        return None

    def dispatch(self, alert: Alert) -> None:
        self._transport(alert)

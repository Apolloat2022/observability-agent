"""Phase 6 — dispatch.py tests. Includes the HANDOFF acceptance criterion:
a synthetic latency regression fires exactly one WARN after require_windows."""
from __future__ import annotations

from obsvagent.alerting.dispatch import Dispatcher
from obsvagent.alerting.model import SIGNALS_BY_KEY, Alert, Severity
from obsvagent.interfaces import AlertDispatcher


def test_implements_protocol():
    assert isinstance(Dispatcher(transport=lambda a: None), AlertDispatcher)


def test_synthetic_latency_regression_fires_exactly_once_after_require_windows():
    fired: list[Alert] = []
    dispatcher = Dispatcher(transport=fired.append)
    spec = SIGNALS_BY_KEY["latency_regression"]
    assert spec.require_windows == 3

    results = []
    for _ in range(5):  # 5 consecutive breaching windows
        results.append(
            dispatcher.observe(
                spec=spec, breached=True, model="claude-opus-4-8", route="riskguard_assessment",
                observed=200.0, threshold=150.0, trace_id="01TRACE",
            )
        )

    # Windows 1-2: not yet confirmed. Window 3: fires. Windows 4-5: already firing, suppressed.
    assert results == [None, None, results[2], None, None]
    assert len(fired) == 1
    assert fired[0].signal_key == "latency_regression"
    assert fired[0].severity is Severity.WARN
    assert fired[0].trace_id == "01TRACE"


def test_clean_window_resets_streak_and_rearms():
    fired: list[Alert] = []
    dispatcher = Dispatcher(transport=fired.append)
    spec = SIGNALS_BY_KEY["latency_regression"]

    for _ in range(3):
        dispatcher.observe(spec=spec, breached=True, model="m", route="r", observed=1, threshold=1)
    assert len(fired) == 1

    dispatcher.observe(spec=spec, breached=False, model="m", route="r", observed=1, threshold=1)  # resolves

    for _ in range(3):
        dispatcher.observe(spec=spec, breached=True, model="m", route="r", observed=1, threshold=1)
    assert len(fired) == 2  # new incident fires again


def test_single_confirmation_signal_fires_immediately():
    fired: list[Alert] = []
    dispatcher = Dispatcher(transport=fired.append)
    spec = SIGNALS_BY_KEY["grounding_rate_drop"]
    assert spec.require_windows == 1

    result = dispatcher.observe(spec=spec, breached=True, model="m", route="riskguard_assessment", observed=0.8, threshold=0.95)
    assert result is not None
    assert result.severity is Severity.CRITICAL


def test_different_routes_have_independent_streaks():
    fired: list[Alert] = []
    dispatcher = Dispatcher(transport=fired.append)
    spec = SIGNALS_BY_KEY["latency_regression"]

    for _ in range(2):
        dispatcher.observe(spec=spec, breached=True, model="m", route="route_a", observed=1, threshold=1)
    dispatcher.observe(spec=spec, breached=True, model="m", route="route_b", observed=1, threshold=1)

    assert fired == []  # route_a needs one more window; route_b just started

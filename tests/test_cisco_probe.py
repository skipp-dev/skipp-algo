"""Unit tests for the Cisco AI Defense inspection-key self-probe.

Covers the outcome classification (a BLOCKED decision proves the key works;
only unavailable/config states fail), the prober thread lifecycle, the boot
sentinel, and the serve-path wiring in open_prep/realtime_signals.py.
"""
from __future__ import annotations

import time
from pathlib import Path

import cisco_ai_defense
from cisco_ai_defense import (
    AIDefenseBlockedError,
    AIDefenseConfigurationError,
    AIDefenseUnavailableError,
)
from open_prep.cisco_probe import (
    SENTINEL_AGE_SECONDS,
    CiscoKeyProber,
    probe_once,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# probe_once outcome classification
# ---------------------------------------------------------------------------

def test_probe_once_allow_decision_is_ok(monkeypatch) -> None:
    monkeypatch.setattr(cisco_ai_defense, "inspect_messages", lambda *a, **k: object())
    assert probe_once() == (True, "")


def test_probe_once_blocked_decision_is_ok(monkeypatch) -> None:
    def _blocked(*_a, **_k):
        raise AIDefenseBlockedError("policy block")

    monkeypatch.setattr(cisco_ai_defense, "inspect_messages", _blocked)
    assert probe_once() == (True, "AIDefenseBlockedError")


def test_probe_once_unavailable_is_failure(monkeypatch) -> None:
    def _unavailable(*_a, **_k):
        raise AIDefenseUnavailableError("no decision")

    monkeypatch.setattr(cisco_ai_defense, "inspect_messages", _unavailable)
    assert probe_once() == (False, "AIDefenseUnavailableError")


def test_probe_once_configuration_error_is_failure(monkeypatch) -> None:
    def _config(*_a, **_k):
        raise AIDefenseConfigurationError("key missing")

    monkeypatch.setattr(cisco_ai_defense, "inspect_messages", _config)
    assert probe_once() == (False, "AIDefenseConfigurationError")


def test_probe_once_sends_content_free_request_phase(monkeypatch) -> None:
    captured: dict = {}

    def _capture(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cisco_ai_defense, "inspect_messages", _capture)
    probe_once()
    assert captured["phase"] == "request"
    assert captured["source"] == "cisco-self-probe"
    assert captured["messages"] == [{"role": "user", "content": "ping"}]


# ---------------------------------------------------------------------------
# CiscoKeyProber lifecycle
# ---------------------------------------------------------------------------

def _wait_for(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_prober_first_probe_runs_immediately_and_updates_state() -> None:
    prober = CiscoKeyProber(interval_s=3600.0, probe_fn=lambda: (True, ""))
    try:
        prober.start()
        assert _wait_for(lambda: prober.attempts >= 1)
        assert prober.last_ok is True
        assert prober.consecutive_failures == 0
        assert prober.last_success_epoch > 0
    finally:
        prober.stop()


def test_prober_failure_updates_counters_and_survives_raising_probe_fn() -> None:
    def _raising():
        raise RuntimeError("probe implementation bug")

    prober = CiscoKeyProber(interval_s=3600.0, probe_fn=_raising)
    try:
        prober.start()
        assert _wait_for(lambda: prober.attempts >= 1)
        assert prober.last_ok is False
        assert prober.failures == 1
        assert prober.consecutive_failures == 1
        assert prober.last_error_type == "RuntimeError"
        assert prober._thread is not None and prober._thread.is_alive()
    finally:
        prober.stop()


def test_prober_start_is_idempotent() -> None:
    prober = CiscoKeyProber(interval_s=3600.0, probe_fn=lambda: (True, ""))
    try:
        prober.start()
        first_thread = prober._thread
        prober.start()
        assert prober._thread is first_thread
    finally:
        prober.stop()


def test_prober_interval_floor_is_300s() -> None:
    prober = CiscoKeyProber(interval_s=1.0, probe_fn=lambda: (True, ""))
    assert prober._interval == 300.0


def test_metrics_lines_export_sentinel_age_before_first_success() -> None:
    prober = CiscoKeyProber(interval_s=3600.0, probe_fn=lambda: (False, "AIDefenseUnavailableError"))
    lines = prober.metrics_lines("signals_producer")
    body = "\n".join(lines)
    assert f"signals_producer_cisco_probe_last_success_age_seconds {SENTINEL_AGE_SECONDS:.1f}" in body
    assert "signals_producer_cisco_probe_ok 0" in body


# ---------------------------------------------------------------------------
# Serve-path wiring: the daemon must actually start the prober
# ---------------------------------------------------------------------------

def test_serve_path_starts_cisco_probe() -> None:
    source = (_REPO_ROOT / "open_prep" / "realtime_signals.py").read_text(encoding="utf-8")
    assert "def start_cisco_probe(" in source
    assert "engine.start_cisco_probe(" in source
    assert "RT_CISCO_PROBE_SECS" in source

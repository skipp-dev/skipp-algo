"""The OPRA definition bootstrap must survive an outage and a UTC session roll.

Two measured production facts drive this module:

* **2026-08-04** — Databento Historical answered 504 for hours. The daemon's
  bootstrap is fail-open (log and continue), so the replica that started
  during the outage ran the rest of the trading day with no definitions at
  all: every print stayed ``unknown`` until a human restarted it.
* ``OpraShadowState._roll_session`` **clears** ``_definitions`` when the UTC
  day changes. A long-lived replica therefore loses its whole definition set
  at midnight UTC and only re-learns the symbols that happen to print again,
  because nothing re-runs the bootstrap for the new session.

Both are the same missing mechanism: the bootstrap must be re-attempted while
it is not satisfied, with a bounded backoff so an outage is retried without
hammering the gateway.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from services.opra_live_daemon import feed
from services.opra_live_daemon.definitions import BootstrapPlanner
from tests.test_opra_live_daemon import (
    _config,
    _definition,
    _FakeLive,
    _patch_feed,
    _run_watched,
    _state,
)


def _planner(**kwargs: Any) -> BootstrapPlanner:
    return BootstrapPlanner(retry_seconds=30.0, max_retry_seconds=900.0, **kwargs)


def test_the_first_bootstrap_is_due_immediately() -> None:
    planner = _planner()

    assert planner.due(0.0, session_date=None, definition_count=0) is True


def test_a_failed_attempt_is_not_retried_before_the_backoff_elapses() -> None:
    planner = _planner()
    planner.record_attempt(0.0, ok=False, session_date=None)

    assert planner.due(29.0, session_date=None, definition_count=0) is False
    assert planner.due(30.0, session_date=None, definition_count=0) is True


def test_the_backoff_grows_with_consecutive_failures_and_is_capped() -> None:
    planner = _planner()
    planner.record_attempt(0.0, ok=False, session_date=None)
    planner.record_attempt(30.0, ok=False, session_date=None)

    # Second failure doubles the wait: due at 30 + 60, not at 30 + 30.
    assert planner.due(89.0, session_date=None, definition_count=0) is False
    assert planner.due(90.0, session_date=None, definition_count=0) is True

    at = 90.0
    for _ in range(20):
        planner.record_attempt(at, ok=False, session_date=None)
        at += 900.0
    planner.record_attempt(at, ok=False, session_date=None)
    assert planner.due(at + 900.0, session_date=None, definition_count=0) is True


def test_a_successful_bootstrap_settles_the_planner() -> None:
    planner = _planner()
    planner.record_attempt(0.0, ok=True, session_date="2026-08-05")

    assert planner.due(10_000.0, session_date="2026-08-05", definition_count=40_180) is False


def test_a_success_that_produced_no_definitions_stays_due() -> None:
    """Zero definitions is a broken bootstrap, whatever the call returned."""
    planner = _planner()
    planner.record_attempt(0.0, ok=True, session_date="2026-08-05")

    assert planner.due(30.0, session_date="2026-08-05", definition_count=0) is True


def test_the_utc_session_roll_makes_the_bootstrap_due_again() -> None:
    """The roll clears state's definitions; a partially re-learned set is not
    a bootstrap. Definitions present must NOT mask the new session."""
    planner = _planner()
    planner.record_attempt(0.0, ok=True, session_date="2026-08-05")

    assert planner.due(86_400.0, session_date="2026-08-06", definition_count=17) is True


def test_a_success_after_failures_resets_the_backoff() -> None:
    planner = _planner()
    planner.record_attempt(0.0, ok=False, session_date=None)
    planner.record_attempt(30.0, ok=False, session_date=None)
    planner.record_attempt(90.0, ok=True, session_date="2026-08-05")

    # New session one tick later: back to the base delay, not the grown one.
    assert planner.due(120.0, session_date="2026-08-06", definition_count=0) is True


# ---- feed.run wiring: the outage and the roll, end to end -------------------


class _RecoveringProvider:
    """A definition source that fails like Databento did on 2026-08-04."""

    def __init__(self, failures: int, records: list[Any]) -> None:
        self.remaining_failures = failures
        self.records = records
        self.calls = 0

    def __call__(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("504 Gateway Time-out")
        return list(self.records)


def _patch_definition_source(
    monkeypatch: pytest.MonkeyPatch, provider: _RecoveringProvider
) -> None:
    """Route the bootstrap at this provider and retry without real waiting."""
    import databento_provider

    monkeypatch.setattr(databento_provider, "DabentoProvider", lambda _key: object())
    monkeypatch.setattr(feed, "bootstrap_definitions", provider)
    monkeypatch.setattr(feed, "_BOOTSTRAP_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(feed, "_BOOTSTRAP_MAX_RETRY_SECONDS", 0.0)


def test_run_retries_a_failed_bootstrap_and_loads_the_definitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _RecoveringProvider(failures=1, records=[_definition()])
    stop = threading.Event()
    state = _state()
    _FakeLive.reset(scripts=[[]], stay_connected=True, on_iter=stop.set)
    _patch_feed(monkeypatch)
    _patch_definition_source(monkeypatch, provider)

    def _watch() -> None:
        for _ in range(500):
            if state.build_snapshot()["metrics"]["definition_count"] > 0:
                break
            stop.wait(0.01)
        stop.set()

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    _run_watched(_config(tmp_path), state, stop)
    watcher.join(timeout=5.0)

    assert provider.calls >= 2, "the failed bootstrap was never retried"
    assert state.build_snapshot()["metrics"]["definition_count"] == 1


def test_run_rebootstraps_after_a_utc_session_roll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _RecoveringProvider(failures=0, records=[_definition()])
    stop = threading.Event()
    state = _state()
    _FakeLive.reset(scripts=[[]], stay_connected=True, on_iter=stop.set)
    _patch_feed(monkeypatch)
    _patch_definition_source(monkeypatch, provider)

    def _roll_then_stop() -> None:
        for _ in range(500):
            if provider.calls >= 1:
                break
            stop.wait(0.01)
        # Midnight UTC, plus the live stream immediately re-learning ONE
        # instrument. Definitions are therefore non-zero, so only the session
        # change itself can make the bootstrap due again — without this the
        # test would pass on the zero-definitions clause and never touch the
        # mechanism it is named for.
        state.session_date = "2026-08-06"
        assert state.definition_count > 0
        for _ in range(500):
            if provider.calls >= 2:
                break
            stop.wait(0.01)
        stop.set()

    roller = threading.Thread(target=_roll_then_stop, daemon=True)
    roller.start()
    _run_watched(_config(tmp_path), state, stop)
    roller.join(timeout=5.0)

    assert provider.calls >= 2, "the session roll did not trigger a re-bootstrap"
    assert state.build_snapshot()["metrics"]["definition_count"] == 1


def test_the_backoff_survives_a_week_of_failures() -> None:
    """The delay is capped; the FAILURE COUNT must be too.

    Unbounded counting overflows the doubling at ~1025 consecutive failures,
    and `due()` runs outside the caller's try — the feed would take the
    OverflowError for a connection fault and churn reconnects forever without
    ever bootstrapping again. Ten days of continuous failure gets there.
    """
    planner = _planner()
    last = 0.0
    for i in range(1200):
        last = i * 900.0
        planner.record_attempt(last, ok=False, session_date=None)

    assert planner.due(last + 899.0, session_date=None, definition_count=0) is False
    assert planner.due(last + 900.0, session_date=None, definition_count=0) is True


def test_definitions_the_state_rejects_are_not_a_successful_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Success means state HOLDS definitions, not that rows came back.

    `add_definition` drops anything outside the hotlist, so counting returned
    rows would let a schema drift (empty `underlying`) reset the backoff on
    every attempt while the daemon sits at zero definitions — a permanent
    30 s poll the growing delay could never engage against.
    """
    off_hotlist = replace(_definition(), underlying="NOTINHOTLIST")
    provider = _RecoveringProvider(failures=0, records=[off_hotlist])
    state = _state()
    _patch_definition_source(monkeypatch, provider)
    monkeypatch.setattr(feed, "_BOOTSTRAP_RETRY_SECONDS", 30.0)
    monkeypatch.setattr(feed, "_BOOTSTRAP_MAX_RETRY_SECONDS", 900.0)
    planner = feed.BootstrapPlanner(retry_seconds=30.0, max_retry_seconds=900.0)

    feed._bootstrap_if_due(planner, lambda: object(), state, symbols=["AAPL.OPT"])
    feed._bootstrap_if_due(planner, lambda: object(), state, symbols=["AAPL.OPT"])

    assert state.definition_count == 0
    assert provider.calls == 1, "the second attempt ran before the backoff elapsed"
    # The discriminator: a recorded SUCCESS would leave the planner satisfied,
    # so it would answer False here once definitions exist. It must not be.
    now = time.monotonic()
    assert planner.due(now + 31.0, session_date="2026-08-05", definition_count=5) is True


def test_definition_count_reports_what_the_state_holds() -> None:
    state = _state()
    assert state.definition_count == 0

    state.add_definition(_definition(), ts_ns=500_000_000)

    assert state.definition_count == 1
    assert state.definition_count == state.build_snapshot()["metrics"]["definition_count"]

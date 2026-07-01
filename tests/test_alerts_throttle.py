from __future__ import annotations

import threading
from collections.abc import Generator

import pytest

from open_prep import alerts


@pytest.fixture(autouse=True)
def _clear_throttle_state() -> Generator[None, None, None]:
    with alerts._throttle_lock:
        alerts._last_sent.clear()
    yield
    with alerts._throttle_lock:
        alerts._last_sent.clear()


def _config() -> dict:
    return {
        "enabled": True,
        "min_confidence_tier": "HIGH_CONVICTION",
        "throttle_seconds": 600,
        "targets": [
            {"name": "slack", "url": "https://hooks.example.com/slack", "type": "generic"},
        ],
    }


def _ranked() -> list[dict]:
    return [
        {
            "symbol": "AAA",
            "confidence_tier": "HIGH_CONVICTION",
            "gap_pct": 2.0,
            "score": 9.0,
        }
    ]


def test_check_and_mark_is_atomic_for_concurrent_callers() -> None:
    worker_count = 32
    barrier = threading.Barrier(worker_count)
    result_lock = threading.Lock()
    results: list[bool] = []

    def worker() -> None:
        barrier.wait(timeout=5)
        allowed = alerts._check_and_mark("AAA", 600, target_scope="AAA::slack")
        with result_lock:
            results.append(allowed)

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == worker_count
    assert results.count(True) == 1
    assert results.count(False) == worker_count - 1
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::slack") is True


def test_dispatch_alerts_rolls_back_target_throttle_when_send_fails(monkeypatch) -> None:
    monkeypatch.setattr(alerts, "_send_webhook", lambda *_args, **_kwargs: {"status": 503})

    results = alerts.dispatch_alerts(_ranked(), regime="RISK_ON", config=_config())

    assert results == [{"symbol": "AAA", "target": "slack", "status": 503}]
    assert alerts._is_throttled("AAA", 600) is False
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::slack") is False


def test_dispatch_alerts_rolls_back_target_throttle_when_send_raises(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("send failed")

    monkeypatch.setattr(alerts, "_send_webhook", _boom)

    results = alerts.dispatch_alerts(_ranked(), regime="RISK_ON", config=_config())

    assert results == [{"symbol": "AAA", "target": "slack", "status": 0}]
    assert alerts._is_throttled("AAA", 600) is False
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::slack") is False


def test_dispatch_alerts_skips_non_dict_candidates(monkeypatch, caplog) -> None:
    calls: list[str] = []

    def _fake_send(url: str, _payload, _headers=None):
        calls.append(url)
        return {"status": 200}

    monkeypatch.setattr(alerts, "_send_webhook", _fake_send)
    ranked: list[object] = [None, "BAD", _ranked()[0]]

    with caplog.at_level("WARNING", logger="open_prep.alerts"):
        results = alerts.dispatch_alerts(ranked, regime="RISK_ON", config=_config())  # type: ignore[arg-type]

    assert results == [{"symbol": "AAA", "target": "slack", "status": 200}]
    assert calls == ["https://hooks.example.com/slack"]
    assert "Skipping invalid candidate at index 0" in caplog.text
    assert "Skipping invalid candidate at index 1" in caplog.text


def test_dispatch_alerts_warns_on_unknown_min_confidence_tier(monkeypatch, caplog) -> None:
    monkeypatch.setattr(alerts, "_send_webhook", lambda *_args, **_kwargs: {"status": 200})
    config = _config()
    config["min_confidence_tier"] = "STANDARD_"

    with caplog.at_level("WARNING", logger="open_prep.alerts"):
        results = alerts.dispatch_alerts(_ranked(), regime="RISK_ON", config=config)

    assert results == [{"symbol": "AAA", "target": "slack", "status": 200}]
    assert "Unknown min_confidence_tier='STANDARD_'; defaulting to HIGH_CONVICTION" in caplog.text


def test_prune_stale_entries_clears_when_throttle_non_positive() -> None:
    with alerts._throttle_lock:
        alerts._last_sent.update({"A": 1.0, "B": 2.0})

    alerts._prune_stale_entries(throttle_seconds=0)

    assert alerts._last_sent == {}


def test_dispatch_alerts_allows_only_one_in_flight_send_per_target(monkeypatch) -> None:
    send_started = threading.Event()
    release_send = threading.Event()
    calls: list[str] = []

    def slow_send(url: str, _payload, _headers=None):
        calls.append(url)
        send_started.set()
        assert release_send.wait(timeout=5)
        return {"status": 200}

    monkeypatch.setattr(alerts, "_send_webhook", slow_send)

    first = threading.Thread(
        target=alerts.dispatch_alerts,
        args=(_ranked(),),
        kwargs={"regime": "RISK_ON", "config": _config()},
    )
    first.start()
    assert send_started.wait(timeout=5)

    second_results = alerts.dispatch_alerts(_ranked(), regime="RISK_ON", config=_config())
    release_send.set()
    first.join(timeout=5)

    assert second_results == []
    assert calls == ["https://hooks.example.com/slack"]
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::slack") is True


def _multi_target_config() -> dict:
    return {
        "enabled": True,
        "min_confidence_tier": "HIGH_CONVICTION",
        "throttle_seconds": 600,
        "targets": [
            {"name": "slack", "url": "https://hooks.example.com/slack", "type": "generic"},
            {"name": "discord", "url": "https://hooks.example.com/discord", "type": "generic"},
        ],
    }


def test_concurrent_dispatch_for_same_symbol_does_not_double_fan_out(monkeypatch) -> None:
    """Two concurrent dispatch calls for one symbol with multiple targets must
    not both fan out: only one call reserves the symbol slot, the other is a
    no-op, and no target is ever alerted more than once."""
    call_lock = threading.Lock()
    calls: list[str] = []
    ready = threading.Barrier(2, timeout=5)

    def recording_send(url: str, _payload, _headers=None):
        with call_lock:
            calls.append(url)
        return {"status": 200}

    monkeypatch.setattr(alerts, "_send_webhook", recording_send)

    results: list[list[dict]] = []
    results_lock = threading.Lock()

    def worker() -> None:
        ready.wait(timeout=5)
        out = alerts.dispatch_alerts(_ranked(), regime="RISK_ON", config=_multi_target_config())
        with results_lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    # Exactly one dispatch call proceeded; the concurrent one was a no-op.
    non_empty = [r for r in results if r]
    assert len(non_empty) == 1
    # No target received more than one webhook for the symbol.
    assert sorted(calls) == [
        "https://hooks.example.com/discord",
        "https://hooks.example.com/slack",
    ]
    assert alerts._is_throttled("AAA", 600) is True

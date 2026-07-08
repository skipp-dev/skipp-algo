"""Tests for the opt-in near-A0 fast-lane re-poller (open_prep.realtime_signals).

The re-poller re-polls the A1/A2 warm set faster than the full cycle and pushes a
fresh A0 early. These tests pin the safety-critical behaviour with fakes (no real
FMP / threads): warm-set = A1/A2 only, only A0 is pushed, off-hours / empty warm
set skip the fetch entirely, and delivery flows through rt_notify's dedup.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from open_prep import realtime_signals as rs
from open_prep.realtime_signals import NearA0Repoller


def _sig(symbol: str, level: str, direction: str = "LONG") -> Any:
    return SimpleNamespace(
        symbol=symbol, level=level, direction=direction, price=100.0,
        volume_ratio=3.5, change_pct=2.1, news_score=0.0, news_category="",
        news_headline="",
    )


class _FakeRegime:
    def adjusted_thresholds(self) -> dict[str, float]:
        return {"volume_ratio_min": 3.0}


class _FakeEngine:
    """Minimal engine surface the re-poller reads."""

    def __init__(self, active: list[Any], detect_map: dict[str, Any]) -> None:
        self._active = active
        self._detect_map = detect_map
        self._watchlist = [{"symbol": s} for s in ("AAPL", "NVDA", "PLTR", "AMZN")]
        self._volume_regime = _FakeRegime()
        self._async_newsstack: Any = None

    def get_active_signals(self) -> list[Any]:
        return list(self._active)

    def _detect_signal(self, symbol: str, quote: dict[str, Any], wl_entry: dict[str, Any],
                       *, regime_thresholds: Any = None,
                       expected_volume_fraction: Any = None) -> Any:
        return self._detect_map.get(symbol)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        self.calls.append(list(symbols))
        return [{"symbol": s, "price": 101.0, "previousClose": 99.0} for s in symbols]


@pytest.fixture(autouse=True)
def _open_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)


def _repoller(engine: _FakeEngine, client: _FakeClient) -> NearA0Repoller:
    return NearA0Repoller(engine, interval=5.0, client_factory=lambda: client)


def test_warm_set_is_a1_a2_only() -> None:
    active = [_sig("AAPL", "A0"), _sig("NVDA", "A1"), _sig("PLTR", "A2"), _sig("AMZN", "A1")]
    r = _repoller(_FakeEngine(active, {}), _FakeClient())
    assert sorted(r._warm_set()) == ["AMZN", "NVDA", "PLTR"]  # A0 excluded


def test_only_fresh_a0_is_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[list[Any]] = []
    monkeypatch.setattr(
        "open_prep.rt_notify.notify_fresh_signals",
        lambda sigs, **kw: (pushed.append(list(sigs)), [f"{s.symbol} {s.direction} {s.level}" for s in sigs])[1],
    )
    active = [_sig("NVDA", "A1"), _sig("PLTR", "A2"), _sig("AMZN", "A1")]
    # NVDA escalates to A0; PLTR stays A1 (not pushed); AMZN no signal.
    detect_map = {"NVDA": _sig("NVDA", "A0"), "PLTR": _sig("PLTR", "A1"), "AMZN": None}
    client = _FakeClient()
    r = _repoller(_FakeEngine(active, detect_map), client)
    r._tick()
    # Fetched exactly the warm set, pushed exactly the one A0.
    assert client.calls == [["NVDA", "PLTR", "AMZN"]]
    assert len(pushed) == 1 and [s.symbol for s in pushed[0]] == ["NVDA"]
    assert r.metrics()["a0_pushed"] == 1


def test_market_closed_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: False)
    client = _FakeClient()
    r = _repoller(_FakeEngine([_sig("NVDA", "A1")], {"NVDA": _sig("NVDA", "A0")}), client)
    r._tick()
    assert client.calls == []  # no FMP call off-hours


def test_empty_warm_set_skips_fetch() -> None:
    client = _FakeClient()
    r = _repoller(_FakeEngine([_sig("AAPL", "A0")], {}), client)  # only A0 active → warm set empty
    r._tick()
    assert client.calls == []


def test_news_enrichment_on_early_push(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine([_sig("NVDA", "A1")], {"NVDA": _sig("NVDA", "A0")})
    engine._async_newsstack = SimpleNamespace(
        latest=lambda: {"NVDA": {"news_score": 0.9, "category": "M&A", "headline": "deal"}}
    )
    fresh = _repoller(engine, _FakeClient())._detect_fresh_a0(
        {"NVDA": {"symbol": "NVDA", "price": 101.0}}
    )
    assert len(fresh) == 1 and fresh[0].news_score == 0.9 and fresh[0].news_category == "M&A"


def test_loop_is_fail_soft_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
            raise RuntimeError("FMP down")

    r = NearA0Repoller(
        _FakeEngine([_sig("NVDA", "A1")], {}), interval=0.01,
        client_factory=lambda: _BoomClient(),
    )
    # Run the loop body exactly once: the end-of-iteration wait flips stop so the
    # while-guard exits, and the client error must be swallowed + counted, not raised.
    r._stop.wait = lambda _t: r._stop.set()  # type: ignore[assignment]
    r._loop()
    assert r.metrics()["poll_errors"] >= 1

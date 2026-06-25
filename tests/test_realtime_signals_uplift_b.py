"""Second-wave coverage uplift for `open_prep.realtime_signals` (Bucket B).

Targets surfaces still uncovered after `test_realtime_signals_uplift.py`:

- `AsyncNewsstackPoller` start/stop lifecycle, `latest()`, idempotent start,
  background `_loop` happy path + exception path (with stop-event injection).
- `RealtimeSignal.to_dict` / `is_expired` boundary semantics.
- `TechnicalScorer` extra branches: cache-fresh hit, fetch-returned-None,
  `result.error` short-circuit, `_extract_and_score` permutations across the
  RSI/MACD/MA/ADX/summary axes, MA/oscillator name aliasing, eviction sweep
  by TTL and by raw size cap.

Out of scope (RealtimeEngine + main()) — left for a later bucket.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_prep import realtime_signals as rs
from open_prep.realtime_signals import (
    AsyncNewsstackPoller,
    RealtimeSignal,
    TechnicalScorer,
)

# ---------------------------------------------------------------------------
# AsyncNewsstackPoller
# ---------------------------------------------------------------------------


def test_async_newsstack_poller_latest_empty_before_start() -> None:
    p = AsyncNewsstackPoller(poll_interval=10.0)
    assert p.latest() == {}


def test_async_newsstack_poller_interval_floor_is_5_seconds() -> None:
    p = AsyncNewsstackPoller(poll_interval=0.1)
    # The constructor clamps the interval to a 5-second floor.
    assert p._interval == 5.0


def test_async_newsstack_poller_start_then_stop_runs_thread() -> None:
    p = AsyncNewsstackPoller(poll_interval=5.0)
    # Use a thread that exits as soon as the stop event is set.
    p._loop = lambda: p._stop.wait(0.05)  # type: ignore[method-assign]
    p.start()
    assert p._thread is not None
    assert p._thread.is_alive()
    p.stop(timeout=2.0)
    assert not p._thread.is_alive()


def test_async_newsstack_poller_start_is_idempotent_when_already_alive() -> None:
    p = AsyncNewsstackPoller(poll_interval=5.0)
    p._loop = lambda: p._stop.wait(0.5)  # type: ignore[method-assign]
    p.start()
    first_thread = p._thread
    p.start()  # second call must be a no-op
    assert p._thread is first_thread
    p.stop(timeout=2.0)


def test_async_newsstack_poller_loop_caches_top_score_per_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_loop` must dedupe by ticker, keeping the highest news_score."""

    p = AsyncNewsstackPoller(poll_interval=5.0)

    candidates = [
        {"ticker": "aapl", "news_score": 0.4, "headline": "low"},
        {"ticker": "AAPL", "news_score": 0.9, "headline": "high"},
        {"ticker": "msft", "news_score": 0.5, "headline": "msft-only"},
        {"ticker": "", "news_score": 0.99, "headline": "skipped"},  # empty ticker → skipped
    ]

    fake_pipeline = type("M", (), {"poll_once": staticmethod(lambda _cfg: candidates)})
    fake_config = type("C", (), {"Config": type("Cfg", (), {})})
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.pipeline", fake_pipeline)
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.config", fake_config)

    # Stop the loop after the first iteration so we don't block forever.
    iterations = {"n": 0}

    real_wait = p._stop.wait

    def stop_after_one(_timeout: float) -> bool:
        iterations["n"] += 1
        if iterations["n"] >= 1:
            p._stop.set()
        return real_wait(0.0)

    monkeypatch.setattr(p._stop, "wait", stop_after_one)
    p._loop()

    latest = p.latest()
    assert set(latest) == {"AAPL", "MSFT"}
    assert latest["AAPL"]["news_score"] == 0.9
    assert latest["MSFT"]["headline"] == "msft-only"


def test_async_newsstack_poller_loop_swallows_pipeline_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    p = AsyncNewsstackPoller(poll_interval=5.0)

    def boom(_cfg: Any) -> list[dict[str, Any]]:
        raise RuntimeError("pipeline down")

    fake_pipeline = type("M", (), {"poll_once": staticmethod(boom)})
    fake_config = type("C", (), {"Config": type("Cfg", (), {})})
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.pipeline", fake_pipeline)
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.config", fake_config)

    # Run exactly one iteration.
    real_wait = p._stop.wait

    def stop_after_one(_timeout: float) -> bool:
        p._stop.set()
        return real_wait(0.0)

    monkeypatch.setattr(p._stop, "wait", stop_after_one)
    with caplog.at_level("DEBUG", logger="open_prep.realtime_signals"):
        p._loop()

    # Latest stays empty when pipeline errors out, and no exception bubbles up.
    assert p.latest() == {}


def test_async_newsstack_poller_stop_without_start_is_safe() -> None:
    p = AsyncNewsstackPoller(poll_interval=5.0)
    # No thread was ever started — stop() must remain a no-op.
    p.stop(timeout=0.1)


def test_async_newsstack_poller_metrics_initially_zero() -> None:
    """ANP-6: telemetry counters start at zero before any poll runs."""
    p = AsyncNewsstackPoller(poll_interval=5.0)
    metrics = p.metrics()
    assert metrics["poll_count"] == 0
    assert metrics["poll_errors"] == 0
    assert metrics["last_poll_duration"] == 0.0
    assert metrics["last_success_at"] is None
    assert metrics["last_error_at"] is None
    assert metrics["last_error_msg"] is None
    assert metrics["cached_tickers_count"] == 0


def test_async_newsstack_poller_metrics_after_successful_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANP-6: successful poll updates counters and timestamp."""
    p = AsyncNewsstackPoller(poll_interval=5.0)
    candidates = [{"ticker": "aapl", "news_score": 0.5, "headline": "h"}]

    fake_pipeline = type("M", (), {"poll_once": staticmethod(lambda _cfg: candidates)})
    fake_config = type("C", (), {"Config": type("Cfg", (), {})})
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.pipeline", fake_pipeline)
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.config", fake_config)

    real_wait = p._stop.wait

    def stop_after_one(_timeout: float) -> bool:
        p._stop.set()
        return real_wait(0.0)

    monkeypatch.setattr(p._stop, "wait", stop_after_one)
    p._loop()

    metrics = p.metrics()
    assert metrics["poll_count"] == 1
    assert metrics["poll_errors"] == 0
    assert metrics["last_success_at"] is not None
    assert metrics["last_error_msg"] is None
    assert metrics["cached_tickers_count"] == 1


def test_async_newsstack_poller_metrics_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANP-6: failed poll records error telemetry."""
    p = AsyncNewsstackPoller(poll_interval=5.0)

    def boom(_cfg: Any) -> list[dict[str, Any]]:
        raise RuntimeError("pipeline down")

    fake_pipeline = type("M", (), {"poll_once": staticmethod(boom)})
    fake_config = type("C", (), {"Config": type("Cfg", (), {})})
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.pipeline", fake_pipeline)
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.config", fake_config)

    real_wait = p._stop.wait

    def stop_after_one(_timeout: float) -> bool:
        p._stop.set()
        return real_wait(0.0)

    monkeypatch.setattr(p._stop, "wait", stop_after_one)
    p._loop()

    metrics = p.metrics()
    assert metrics["poll_count"] == 0
    assert metrics["poll_errors"] == 1
    assert metrics["last_error_at"] is not None
    assert "pipeline down" in metrics["last_error_msg"]


def test_async_newsstack_poller_loop_respects_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANP-5: a long-blocking poll_once can be abandoned via stop_event."""
    p = AsyncNewsstackPoller(poll_interval=5.0)
    started = __import__("threading").Event()
    unblock = __import__("threading").Event()

    def blocking_poll(_cfg: Any) -> list[dict[str, Any]]:
        started.set()
        unblock.wait()
        return [{"ticker": "aapl", "news_score": 0.5, "headline": "h"}]

    fake_pipeline = type("M", (), {"poll_once": staticmethod(blocking_poll)})
    fake_config = type("C", (), {"Config": type("Cfg", (), {})})
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.pipeline", fake_pipeline)
    monkeypatch.setitem(__import__("sys").modules, "newsstack_fmp.config", fake_config)

    p.start()
    assert started.wait(timeout=1.0)
    p.stop(timeout=1.0)
    unblock.set()
    # The poller must not block on the long poll; stop returns promptly.
    assert not p._thread.is_alive()


# ---------------------------------------------------------------------------
# RealtimeSignal
# ---------------------------------------------------------------------------


def _make_signal(**overrides: Any) -> RealtimeSignal:
    base: dict[str, Any] = dict(
        symbol="AAPL",
        level="A0",
        direction="LONG",
        pattern="HHHL",
        price=190.0,
        prev_close=188.5,
        change_pct=0.79,
        volume_ratio=2.4,
        score=0.81,
        confidence_tier="HIGH",
        atr_pct=1.2,
        freshness=0.8,
        fired_at="2026-04-23T13:30:00+00:00",
        fired_epoch=time.time(),
    )
    base.update(overrides)
    return RealtimeSignal(**base)


def test_realtime_signal_to_dict_round_trip_contains_all_fields() -> None:
    sig = _make_signal()
    d = sig.to_dict()
    # Spot-check a few critical fields preserved.
    for key in (
        "symbol", "level", "direction", "pattern", "price", "prev_close",
        "change_pct", "volume_ratio", "score", "confidence_tier", "atr_pct",
        "freshness", "fired_at", "fired_epoch", "details", "symbol_regime",
        "news_score", "news_category", "news_headline", "news_warn_flags",
        "technical_score", "technical_signal", "rsi", "macd_signal",
    ):
        assert key in d, f"missing key {key} in to_dict() output"


def test_realtime_signal_is_expired_false_when_fresh() -> None:
    sig = _make_signal(fired_epoch=time.time())
    assert sig.is_expired() is False


def test_realtime_signal_is_expired_true_after_max_age() -> None:
    sig = _make_signal(fired_epoch=time.time() - rs.MAX_SIGNAL_AGE_SECONDS - 5)
    assert sig.is_expired() is True


def test_realtime_signal_is_expired_uses_supplied_now_epoch() -> None:
    epoch = 1_000_000.0
    sig = _make_signal(fired_epoch=epoch)
    assert sig.is_expired(now_epoch=epoch + rs.MAX_SIGNAL_AGE_SECONDS - 1) is False
    assert sig.is_expired(now_epoch=epoch + rs.MAX_SIGNAL_AGE_SECONDS + 1) is True


def test_realtime_signal_defaults_have_neutral_technical_state() -> None:
    sig = _make_signal()
    assert sig.technical_score == pytest.approx(0.5)
    assert sig.technical_signal == "NEUTRAL"
    assert sig.rsi is None
    assert sig.macd_signal == ""
    assert sig.news_warn_flags == []


# ---------------------------------------------------------------------------
# TechnicalScorer — fast paths and scoring permutations
# ---------------------------------------------------------------------------


@dataclass
class _FakeTechnicalResult:
    """Minimal stand-in for `TechnicalResult` used by `_extract_and_score`."""

    osc_detail: list[dict[str, Any]] = field(default_factory=list)
    ma_detail: list[dict[str, Any]] = field(default_factory=list)
    ma_buy: int = 0
    ma_sell: int = 0
    ma_neutral: int = 0
    summary_signal: str = ""
    summary_buy: int = 0
    summary_sell: int = 0
    summary_neutral: int = 0
    error: str = ""


def _fresh_scorer() -> TechnicalScorer:
    s = TechnicalScorer()
    # Pre-arm the scorer so it never hits the rate-limit guard.
    s._last_call_ts = 0.0
    return s


def test_technical_scorer_returns_cached_data_when_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _fresh_scorer()
    cached_payload = {"technical_score": 0.77, "technical_signal": "BUY"}
    s._cache["AAPL:1D"] = (time.time(), cached_payload)

    # Fetch must not be called when cache is fresh.
    s._fetch_fn = MagicMock(side_effect=AssertionError("fetch should not be called"))

    out = s.get_technical_data("AAPL", "1D")
    assert out is cached_payload


def test_technical_scorer_handles_fetch_returning_none(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _fresh_scorer()
    s._fetch_fn = lambda *_a, **_k: None
    out = s.get_technical_data("AAPL")
    assert out["error"] == "fetch returned None"
    assert out["technical_score"] == 0.5
    assert out["technical_signal"] == "NEUTRAL"


def test_technical_scorer_handles_result_with_error_attribute() -> None:
    s = _fresh_scorer()
    s._fetch_fn = lambda *_a, **_k: _FakeTechnicalResult(error="429 rate limited")
    out = s.get_technical_data("AAPL")
    assert out["error"] == "429 rate limited"
    assert out["technical_score"] == 0.5


def test_technical_scorer_handles_fetch_exception() -> None:
    s = _fresh_scorer()

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("network gone")

    s._fetch_fn = boom
    out = s.get_technical_data("AAPL")
    assert "network gone" in out["error"]
    assert out["technical_score"] == 0.5


def test_technical_scorer_clear_drops_all_entries() -> None:
    s = _fresh_scorer()
    s._cache["AAPL:1D"] = (time.time(), {"technical_score": 0.6})
    s._cache["MSFT:1D"] = (time.time(), {"technical_score": 0.4})
    s.clear()
    assert s._cache == {}


def test_technical_scorer_evicts_via_ttl_when_over_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _fresh_scorer()
    # Pack the cache with stale entries (older than 3 × TTL) plus one fresh entry.
    now = time.time()
    stale_ts = now - (TechnicalScorer._CACHE_TTL * 4)
    for i in range(TechnicalScorer._CACHE_MAX + 1):
        s._cache[f"S{i}:1D"] = (stale_ts, {"technical_score": 0.5})
    s._cache["FRESH:1D"] = (now, {"technical_score": 0.5})

    s._fetch_fn = lambda *_a, **_k: _FakeTechnicalResult(summary_signal="NEUTRAL")
    s.get_technical_data("NEW", "1D")

    # All stale entries must have been swept; FRESH and NEW survive.
    assert "FRESH:1D" in s._cache
    assert "NEW:1D" in s._cache
    assert all(not k.startswith("S") for k in s._cache)


def test_technical_scorer_evicts_oldest_when_all_entries_recent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _fresh_scorer()
    now = time.time()
    # Fill cache with recent entries at strictly increasing timestamps.
    for i in range(TechnicalScorer._CACHE_MAX + 5):
        s._cache[f"R{i}:1D"] = (now - (1000 - i), {"technical_score": 0.5})

    s._fetch_fn = lambda *_a, **_k: _FakeTechnicalResult(summary_signal="NEUTRAL")
    s.get_technical_data("LAST", "1D")

    # Cache must be clamped to _CACHE_MAX entries.
    assert len(s._cache) <= TechnicalScorer._CACHE_MAX
    assert "LAST:1D" in s._cache
    # The earliest-timestamp entries (R0, R1, …) should be the ones evicted first.
    assert "R0:1D" not in s._cache


def test_technical_scorer_returns_cached_under_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    s = TechnicalScorer()
    s._last_call_ts = time.time()  # force rate-limit guard to fire
    cached_payload = {"technical_score": 0.61, "technical_signal": "BUY"}
    # Stale cache (older than TTL) so the fast path doesn't return early.
    s._cache["AAPL:1D"] = (time.time() - TechnicalScorer._CACHE_TTL - 5, cached_payload)
    s._fetch_fn = MagicMock(side_effect=AssertionError("fetch should not be called"))

    out = s.get_technical_data("AAPL", "1D")
    assert out is cached_payload


def test_technical_scorer_returns_empty_under_rate_limit_without_cache() -> None:
    s = TechnicalScorer()
    s._last_call_ts = time.time()  # rate-limit guard active, no cache present
    s._fetch_fn = MagicMock(side_effect=AssertionError("fetch should not be called"))

    out = s.get_technical_data("AAPL", "1D")
    assert "rate limited" in out["error"]
    assert out["technical_score"] == 0.5


# -- _extract_and_score permutations --------------------------------------


def test_extract_and_score_strong_buy_when_oversold_rsi_and_buy_macd() -> None:
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[
            {"name": "RSI (14)", "value": 18.0, "action": "BUY"},
            {"name": "MACD Level (12, 26)", "value": 0.0, "action": "BUY"},
            {"name": "ADX (14)", "value": 35.0},
            {"name": "Williams %R (14)", "value": -90.0},
        ],
        ma_buy=10,
        ma_sell=0,
        ma_neutral=2,
        summary_signal="STRONG_BUY",
    )
    out = s._extract_and_score(res)
    assert out["technical_signal"] in {"STRONG_BUY", "BUY"}
    assert out["technical_score"] >= 0.6
    assert out["rsi"] == pytest.approx(18.0)
    assert out["macd_signal"] == "BUY"
    assert out["adx"] == pytest.approx(35.0)
    assert out["williams"] == pytest.approx(-90.0)


def test_extract_and_score_strong_sell_when_overbought_rsi_and_sell_macd() -> None:
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[
            {"name": "RSI (14)", "value": 82.0, "action": "SELL"},
            {"name": "MACD Level (12, 26)", "value": 0.0, "action": "SELL"},
            {"name": "ADX (14)", "value": 40.0},
        ],
        ma_buy=0,
        ma_sell=10,
        ma_neutral=2,
        summary_signal="STRONG_SELL",
    )
    out = s._extract_and_score(res)
    assert out["technical_signal"] in {"STRONG_SELL", "SELL"}
    assert out["technical_score"] <= 0.4


def test_extract_and_score_neutral_when_no_indicators_present() -> None:
    s = _fresh_scorer()
    out = s._extract_and_score(_FakeTechnicalResult())
    assert out["technical_signal"] == "NEUTRAL"
    assert out["technical_score"] == pytest.approx(0.5)
    assert out["rsi"] is None
    assert out["macd_signal"] is None


def test_extract_and_score_skips_oscillators_with_none_value() -> None:
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[
            {"name": "RSI (14)", "value": None, "action": "NEUTRAL"},
            {"name": "ADX (14)", "value": None},
        ],
    )
    out = s._extract_and_score(res)
    assert out["rsi"] is None
    assert out["adx"] is None


@pytest.mark.parametrize(
    "rsi,expected_band",
    [
        (15.0, "lt_20"),
        (25.0, "lt_30"),
        (35.0, "lt_40"),
        (50.0, "neutral"),
        (65.0, "gt_60"),
        (75.0, "gt_70"),
        (85.0, "gt_80"),
    ],
)
def test_extract_and_score_rsi_bands_monotonic(rsi: float, expected_band: str) -> None:
    s = _fresh_scorer()
    out = s._extract_and_score(
        _FakeTechnicalResult(osc_detail=[{"name": "RSI (14)", "value": rsi}])
    )
    score = out["technical_score"]
    if expected_band == "lt_20":
        assert score > 0.65
    elif expected_band in {"lt_30", "lt_40"}:
        assert score > 0.5
    elif expected_band == "neutral":
        assert score == pytest.approx(0.5)
    elif expected_band == "gt_60":
        assert score < 0.5
    else:
        assert score < 0.45


def test_extract_and_score_williams_alias_short_prefix_recognised() -> None:
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[{"name": "Will %R", "value": -25.0}],
    )
    out = s._extract_and_score(res)
    assert out["williams"] == pytest.approx(-25.0)


def test_extract_and_score_macd_neutral_does_not_shift_score() -> None:
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[{"name": "MACD Level (12, 26)", "value": 0.0, "action": "NEUTRAL"}],
    )
    out = s._extract_and_score(res)
    assert out["macd_signal"] == "NEUTRAL"
    assert out["technical_score"] == pytest.approx(0.5)


def test_extract_and_score_adx_amplifies_existing_directional_bias() -> None:
    s = _fresh_scorer()
    base = s._extract_and_score(
        _FakeTechnicalResult(
            osc_detail=[{"name": "RSI (14)", "value": 25.0}],
            ma_buy=8, ma_sell=0, ma_neutral=2,
        )
    )
    amplified = s._extract_and_score(
        _FakeTechnicalResult(
            osc_detail=[
                {"name": "RSI (14)", "value": 25.0},
                {"name": "ADX (14)", "value": 45.0},
            ],
            ma_buy=8, ma_sell=0, ma_neutral=2,
        )
    )
    # ADX should increase the (already bullish) score, not flip it.
    assert amplified["technical_score"] > base["technical_score"]


def test_extract_and_score_summary_signal_unknown_string_treated_as_neutral() -> None:
    s = _fresh_scorer()
    out = s._extract_and_score(_FakeTechnicalResult(summary_signal="WHO_KNOWS"))
    assert out["technical_score"] == pytest.approx(0.5)


def test_extract_and_score_macd_stochastic_is_ignored() -> None:
    """The MACD branch must not match `Stochastic MACD`-style names."""
    s = _fresh_scorer()
    res = _FakeTechnicalResult(
        osc_detail=[
            {"name": "Stochastic MACD", "value": 0.5, "action": "BUY"},
        ],
    )
    out = s._extract_and_score(res)
    # No real MACD entry → macd_signal stays None and score stays neutral.
    assert out["macd_signal"] is None
    assert out["technical_score"] == pytest.approx(0.5)

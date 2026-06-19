"""Additional reproduction and property tests for live_overlay_daemon.

No code changes — only document demonstrable bugs.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


class TestNewsScoreFalsyZeroBug:
    """BUG: sentiment_score=0 was treated as 'falsy' and replaced by news_score."""

    def test_zero_sentiment_score_is_not_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.config as cfg

        snapshot_path = tmp_path / "news.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "stories": [
                        {"tickers": ["AAPL"], "sentiment_score": 0.0, "news_score": 0.9}
                    ]
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})
        monkeypatch.setattr(cfg, "news_cache_ttl_secs", lambda: 0)

        with patch.object(compute.config, "news_snapshot_path", return_value=snapshot_path):
            fields = compute._get_news_fields("AAPL")

        # Expected: sentiment_score=0 => avg=0 => news_strength=0, news_bias=NEUTRAL
        # Actual bug path: 0.0 is falsy, so news_score=0.9 would be used.
        assert fields["news_strength"] == 0.0, (
            f"BUG: zero sentiment_score was ignored due to 'or' falsiness. "
            f"expected news_strength=0.0, got {fields['news_strength']!r}"
        )
        assert fields["news_bias"] == "NEUTRAL"


class TestRunFullComputeCycleEmptyCacheBug:
    """BUG: When the bar cache is cleared, the stale overlay is preserved."""

    def test_empty_bar_cache_does_not_preserve_stale_overlay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute

        # Set old overlay
        cache_mod.set_overlay({"AAPL": {"symbol": "AAPL", "stale": False}})
        old_overlay = cache_mod.get_overlay("AAPL")
        assert old_overlay is not None

        # Bar cache is empty
        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(compute.config, "max_stale_secs", lambda: 3600)

        # Reset news cache
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        count = compute.run_full_compute_cycle()

        assert count == 0
        # Expected: overlay should be cleared because no symbols are available any more
        # Actual (pre-fix): stale overlay persisted
        current = cache_mod.get_overlay("AAPL")
        assert current is None, (
            "BUG: stale overlay persisted after all bars were removed. "
            f"expected None, got {current!r}"
        )


class TestRecordToBarMissingFieldsBug:
    """BUG: _record_to_bar defaulted missing fields to 0.0 instead of None."""

    def test_missing_close_defaults_to_none(self) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        record = type(
            "FakeRecord",
            (),
            {
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                # close missing
                "volume": 100,
                "ts_event": 123,
            },
        )()

        bar = feed_mod._record_to_bar(record)
        assert bar is not None
        assert bar.get("close") is None, (
            f"BUG: missing close should be None, got {bar.get('close')!r}"
        )

    def test_missing_open_defaults_to_none(self) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        record = type(
            "FakeRecord",
            (),
            {
                # open missing
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "ts_event": 123,
            },
        )()

        bar = feed_mod._record_to_bar(record)
        assert bar is not None
        assert bar.get("open") is None, (
            f"BUG: missing open should be None, got {bar.get('open')!r}"
        )


class TestVIXNonePropagationBug:
    """BUG: When _record_to_bar returns close=None, cache.set_vix must not be called."""

    def test_vix_with_none_close_is_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.feed as feed_mod

        calls: list[Any] = []
        monkeypatch.setattr(cache_mod, "set_vix", calls.append)

        bar = {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": None,
            "volume": 100,
            "ts_event": 0,
        }

        feed_mod._maybe_cache_vix("VIX", bar)

        assert calls == [], f"VIX with close=None should not be cached, got {calls}"


class TestFeedReadinessRaceCondition:
    """Concurrency stress test: _last_bar_at read/write remains stable under lock."""

    def test_last_bar_at_race_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        feed_mod._feed_ready.set()
        feed_mod._last_bar_at = time.monotonic()

        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(1000):
                    with feed_mod._last_bar_lock:
                        feed_mod._last_bar_at = time.monotonic()
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(1000):
                    feed_mod.is_ready()
                    feed_mod.last_bar_age_secs()
            except Exception as exc:
                errors.append(exc)

        writers = [threading.Thread(target=writer) for _ in range(5)]
        readers = [threading.Thread(target=reader) for _ in range(5)]
        for t in writers + readers:
            t.start()
        for t in writers + readers:
            t.join()

        assert not errors, f"Race on _last_bar_at raised: {errors[:3]}"
        age = feed_mod.last_bar_age_secs()
        assert age is None or age >= 0.0


class TestStartStopThreadLifecycleBug:
    """BUG: start() overwrites thread variables even when old threads have died."""

    def test_start_after_thread_death_creates_new_threads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        # Simulate a dead thread still held in the module-level variable.
        dead_thread = type("DeadThread", (), {"is_alive": lambda self: False})()
        monkeypatch.setattr(feed_mod, "_feed_thread", dead_thread)
        monkeypatch.setattr(feed_mod, "_refresh_thread", None)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)

        created: list[str] = []

        def fake_thread(name: str) -> threading.Thread:
            created.append(name)
            return type("FakeThread", (), {
                "start": lambda self: None,
                "is_alive": lambda self: True,
            })()

        monkeypatch.setattr(
            feed_mod.threading,
            "Thread",
            lambda *args, name=None, **kwargs: fake_thread(name),
        )

        feed_mod.start()

        assert "live-feed" in created
        assert "overlay-refresh" in created
        assert "flow-refresh" in created


class TestVolumeTypeDriftRobustness:
    """Compute cycle must tolerate non-ideal volume types without crashing."""

    def test_string_volumes_are_coerced_in_flow_and_ats(self) -> None:
        import services.live_overlay_daemon.compute as compute

        bars = [
            {
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": str(100 + i * 10),
            }
            for i in range(5)
        ]

        flow = compute.compute_flow_fields(bars)
        ats = compute.compute_ats_fields(bars)

        assert flow["flow_rel_vol"] == pytest.approx(140.0 / 115.0, rel=1e-4)
        assert flow["flow_delta_proxy_pct"] is not None
        assert ats["ats_zscore"] is not None

    def test_run_full_compute_cycle_skips_invalid_volume_types_without_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_overlay", {})
        monkeypatch.setattr(cache_mod, "_overlay_computed_at", 0.0)
        monkeypatch.setattr(compute.config, "max_stale_secs", lambda: 3600)
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_load_news_snapshot", lambda: {})

        for i in range(5):
            cache_mod.push_bar(
                "AAPL",
                {
                    "open": 100.0 + i,
                    "high": 101.0 + i,
                    "low": 99.0 + i,
                    "close": 100.5 + i,
                    "volume": {"bad": 1} if i == 4 else 100,
                    "ts_event": i,
                },
            )

        n = compute.run_full_compute_cycle()
        payload = cache_mod.get_overlay("AAPL")

        assert n == 1
        assert payload is not None
        assert payload["flow_rel_vol"] is None
        assert payload["ats_zscore"] is None

    def test_read_paths_explicitly_take_last_bar_lock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        class _ProbeLock:
            def __init__(self) -> None:
                self.enters = 0

            def __enter__(self) -> _ProbeLock:
                self.enters += 1
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        probe = _ProbeLock()
        monkeypatch.setattr(feed_mod, "_last_bar_lock", probe)
        monkeypatch.setattr(feed_mod, "_last_bar_at", time.monotonic())
        feed_mod._feed_ready.set()

        feed_mod.is_ready()
        feed_mod.last_bar_age_secs()

        assert probe.enters >= 2, "Expected read paths to acquire _last_bar_lock"

    def test_flow_patch_cycle_clears_stale_rel_vol_when_last_volume_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute_mod

        cache_mod.set_overlay(
            {
                "AAPL": {
                    "flow_rel_vol": 2.5,
                    "flow_delta_proxy_pct": 1.0,
                    "vix_level": 20.0,
                }
            }
        )

        monkeypatch.setattr(
            cache_mod,
            "get_all_symbols_snapshot",
            lambda: {
                "AAPL": [
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 110},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 130},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": -1},
                ]
            },
        )
        monkeypatch.setattr(cache_mod, "get_vix", lambda: 21.0)

        compute_mod.run_flow_patch_cycle()

        payload = cache_mod.get_overlay("AAPL")
        assert payload is not None
        assert payload["flow_rel_vol"] is None
        assert payload["flow_delta_proxy_pct"] == 0.5
        assert payload["vix_level"] == 21.0

    def test_flow_patch_cycle_clears_stale_delta_when_last_open_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute_mod

        cache_mod.set_overlay(
            {
                "AAPL": {
                    "flow_rel_vol": 2.5,
                    "flow_delta_proxy_pct": 1.0,
                }
            }
        )

        monkeypatch.setattr(
            cache_mod,
            "get_all_symbols_snapshot",
            lambda: {
                "AAPL": [
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 110},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120},
                    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 130},
                    {"open": None, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 140},
                ]
            },
        )
        monkeypatch.setattr(cache_mod, "get_vix", lambda: None)

        compute_mod.run_flow_patch_cycle()

        payload = cache_mod.get_overlay("AAPL")
        assert payload is not None
        assert payload["flow_rel_vol"] == pytest.approx(140.0 / 115.0, rel=1e-4)
        assert payload["flow_delta_proxy_pct"] is None

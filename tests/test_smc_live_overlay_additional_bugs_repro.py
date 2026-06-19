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

        # Erwartet: sentiment_score=0 => avg=0 => news_strength=0, news_bias=NEUTRAL
        # Tatsaechlich: 0.0 ist falsy, also wird news_score=0.9 genommen
        assert fields["news_strength"] == 0.0, (
            f"BUG: zero sentiment_score was ignored due to 'or' falsiness. "
            f"expected news_strength=0.0, got {fields['news_strength']!r}"
        )
        assert fields["news_bias"] == "NEUTRAL"


class TestRunFullComputeCycleEmptyCacheBug:
    """BUG: Wenn der bar cache leer wird, bleibt das alte Overlay erhalten."""

    def test_empty_bar_cache_does_not_preserve_stale_overlay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute

        # Altes Overlay setzen
        cache_mod.set_overlay({"AAPL": {"symbol": "AAPL", "stale": False}})
        old_overlay = cache_mod.get_overlay("AAPL")
        assert old_overlay is not None

        # Bar cache leer
        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(compute.config, "max_stale_secs", lambda: 3600)

        # Reset news cache
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        count = compute.run_full_compute_cycle()

        assert count == 0
        # Erwartet: Overlay sollte geleert werden, weil keine Symbole mehr verfuegbar
        # Tatsaechlich: altes Overlay bleibt erhalten
        current = cache_mod.get_overlay("AAPL")
        assert current is None, (
            "BUG: stale overlay persisted after all bars were removed. "
            f"expected None, got {current!r}"
        )


class TestRecordToBarMissingFieldsBug:
    """BUG: _record_to_bar defaultet fehlende Felder auf 0.0 statt None."""

    def test_missing_close_defaults_to_none(self) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        record = type(
            "FakeRecord",
            (),
            {
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                # close fehlt
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
                # open fehlt
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
    """BUG: Wenn _record_to_bar close=None liefert, darf cache.set_vix nicht None setzen."""

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
    """RACE RISK: _last_bar_at was written and read without a lock."""

    def test_last_bar_at_race_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        feed_mod._feed_ready.set()
        feed_mod._last_bar_at = time.monotonic()

        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(1000):
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

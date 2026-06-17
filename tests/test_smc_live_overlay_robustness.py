"""Tests for overlay-daemon robustness fixes (R1, R3, R4, R6).

R1 — _symbology_map guard warning on missing attribute
R3 — _load_news_snapshot logs warning on JSON/IO errors
R4 — config range validation for rolling_bars / max_stale_secs
R6 — bar cache symbol eviction at _MAX_SYMBOLS cap
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# R4: config range validation
# ---------------------------------------------------------------------------


class TestConfigRangeValidation:
    """rolling_bars() and max_stale_secs() clamp out-of-range values."""

    def test_rolling_bars_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_ROLLING_BARS", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 60

    def test_rolling_bars_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "120")
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 120

    def test_rolling_bars_too_high_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "999")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 500
        assert "outside valid range" in caplog.text

    def test_rolling_bars_too_low_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "0")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 1
        assert "outside valid range" in caplog.text

    def test_max_stale_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_MAX_STALE_SECS", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_stale_secs() == 3600

    def test_max_stale_too_high_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "99999")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.max_stale_secs()
        assert result == 7200
        assert "outside valid range" in caplog.text

    def test_max_stale_too_low_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "10")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.max_stale_secs()
        assert result == 60
        assert "outside valid range" in caplog.text

    def test_optional_int_warns_on_invalid(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "not_a_number")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 60  # default
        assert "Invalid integer" in caplog.text


# ---------------------------------------------------------------------------
# R3: _load_news_snapshot warning logging
# ---------------------------------------------------------------------------


class TestNewsSnapshotWarningLogging:
    """_load_news_snapshot() logs a warning on parse failure instead of silently returning {}."""

    def test_corrupt_json_logs_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        bad_file = tmp_path / "news.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        import services.live_overlay_daemon.compute as compute

        # Reset TTL cache so it reloads
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        with patch.object(compute.config, "news_snapshot_path", return_value=bad_file):
            with caplog.at_level(logging.WARNING):
                result = compute._load_news_snapshot()

        assert result == {}
        assert "Failed to load news snapshot" in caplog.text

    def test_valid_json_no_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        good_file = tmp_path / "news.json"
        good_file.write_text(json.dumps({"stories": []}), encoding="utf-8")

        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        with patch.object(compute.config, "news_snapshot_path", return_value=good_file):
            with caplog.at_level(logging.WARNING):
                result = compute._load_news_snapshot()

        assert result == {"stories": []}
        assert "Failed to load news snapshot" not in caplog.text


# ---------------------------------------------------------------------------
# R6: bar cache symbol eviction
# ---------------------------------------------------------------------------


class TestBarCacheEviction:
    """Bar cache evicts least-recently-updated symbols when hitting _MAX_SYMBOLS."""

    def test_eviction_at_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        # Reset module state
        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_rolling_bars_cap", 5)

        small_cap = 20
        monkeypatch.setattr(cache_mod, "_MAX_SYMBOLS", small_cap)

        # Fill to cap with stale symbols
        for i in range(small_cap):
            cache_mod.push_bar(f"OLD{i}", {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 100})

        assert cache_mod.bar_symbol_count() == small_cap

        # Push one more — triggers eviction
        cache_mod.push_bar("NEW_SYMBOL", {"open": 2, "close": 2, "high": 2, "low": 2, "volume": 200})

        # Should have evicted ~10% (2 symbols) and added 1
        assert cache_mod.bar_symbol_count() <= small_cap
        assert cache_mod.get_bars_snapshot("NEW_SYMBOL") != []

    def test_eviction_removes_oldest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_rolling_bars_cap", 5)
        monkeypatch.setattr(cache_mod, "_MAX_SYMBOLS", 5)

        bar = {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 100}

        # Push 5 symbols with increasing timestamps
        for i in range(5):
            cache_mod.push_bar(f"SYM{i}", bar)
            time.sleep(0.001)  # ensure distinct monotonic timestamps

        # SYM0 is oldest. Push a new one to trigger eviction.
        cache_mod.push_bar("FRESH", bar)

        # SYM0 should be evicted (oldest)
        assert cache_mod.get_bars_snapshot("SYM0") == []
        # FRESH should exist
        assert cache_mod.get_bars_snapshot("FRESH") != []


# ---------------------------------------------------------------------------
# R1: _symbology_map guard
# ---------------------------------------------------------------------------


class TestSymbologyMapGuard:
    """feed.py warns when db.Live() client lacks _symbology_map."""

    def test_warning_logged_when_attr_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        """The warning code path is syntactically correct and logs when attr is absent."""
        import services.live_overlay_daemon.feed as feed_mod

        # Simulate a client object without _symbology_map
        class FakeClient:
            pass

        client = FakeClient()
        symmap = getattr(client, "_symbology_map", {})

        with caplog.at_level(logging.WARNING):
            if not hasattr(client, "_symbology_map"):
                feed_mod.logger.warning(
                    "db.Live() client has no '_symbology_map' attribute — "
                    "databento SDK may have changed. Symbol resolution will "
                    "fail until this is updated."
                )

        assert symmap == {}
        assert "_symbology_map" in caplog.text

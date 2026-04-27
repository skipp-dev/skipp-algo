"""Pin the contract: when zoneinfo + dateutil are unavailable, the
timezone resolvers must raise RuntimeError instead of silently using
a fixed UTC offset (which would drift 1h every winter)."""
from __future__ import annotations

import sys

import pytest


def _block_tz(monkeypatch):
    """Force `import zoneinfo` and `import dateutil*` to fail."""
    # Drop any cached entries first.
    for name in list(sys.modules):
        if name == "zoneinfo" or name == "dateutil" or name.startswith("dateutil."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    # Poison the import system: setting sys.modules[name] = None makes
    # subsequent `import name` raise ImportError per the import protocol.
    monkeypatch.setitem(sys.modules, "zoneinfo", None)
    monkeypatch.setitem(sys.modules, "dateutil", None)
    monkeypatch.setitem(sys.modules, "dateutil.tz", None)


class TestNotificationsLoudFail:
    def test_is_market_hours_raises_when_no_tz_lib(self, monkeypatch):
        import terminal_notifications as mod

        _block_tz(monkeypatch)
        with pytest.raises(RuntimeError, match="America/New_York"):
            mod._is_market_hours()


class TestFeedLifecycleLoudFail:
    def test_now_et_raises_when_no_tz_lib(self, monkeypatch):
        import terminal_feed_lifecycle as mod

        _block_tz(monkeypatch)
        with pytest.raises(RuntimeError, match="America/New_York"):
            mod._now_et()


class TestRealtimeSignalsLoudFail:
    def test_is_within_market_hours_raises_when_no_tz_lib(self, monkeypatch):
        from open_prep import realtime_signals as mod

        _block_tz(monkeypatch)
        with pytest.raises(RuntimeError, match="America/New_York"):
            mod._is_within_market_hours()

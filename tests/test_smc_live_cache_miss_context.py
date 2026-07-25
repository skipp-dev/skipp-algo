"""Cache-miss path must still serve non-cache-derived context (SC-LIB-001).

Observed on the live system 2026-07-22: minutes after a daemon redeploy the
per-symbol overlay cache was still warming, so ``/smc_live`` took the
cache-miss branch and returned an all-null payload. The sidecar's
"Chart-Kontext" card therefore read "keine Daten" and every value showed "—"
— although BOTH the library context (a file on disk) and VIX (a market-wide
poll) were known at that moment. Neither depends on the per-symbol cache, so
a cache miss must not blank them.

Endpoint functions are invoked directly (repo convention — no TestClient).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import services.live_overlay_daemon.main as main_mod

_TOKEN = "test-token"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "spec" / "smc_live_overlay.schema.json"
)

_LIBRARY_CONTEXT = {
    "universe_member": True,
    "universe_size": 6929,
    "library_asof_date": "2026-07-22",
    "library_asof_time": "2026-07-22T16:40:00Z",
    "provider_trust_status": "ok",
    "provider_stale_list": None,
}


@pytest.fixture
def cache_miss(monkeypatch: pytest.MonkeyPatch):
    """Daemon with a warm VIX + library file but no cached overlay for the symbol."""
    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: _TOKEN)
    monkeypatch.setattr(main_mod.cache, "get_overlay", lambda _sym: None)
    monkeypatch.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: [])
    monkeypatch.setattr(main_mod.cache, "get_vix", lambda: 16.8123)
    monkeypatch.setattr(
        main_mod.library_context_bridge,
        "context_for_symbol",
        lambda _sym: dict(_LIBRARY_CONTEXT),
    )
    return monkeypatch


def _get(symbol: str = "NVDA", tf: str = "5m") -> dict[str, Any]:
    return json.loads(main_mod.smc_live(token=_TOKEN, symbol=symbol, tf=tf).body)


def test_cache_miss_still_serves_library_context(cache_miss) -> None:
    payload = _get()
    assert payload["stale"] is True  # the symbol data genuinely IS missing…
    # …but the repo-derived library context is not, and must be served.
    for key, expected in _LIBRARY_CONTEXT.items():
        assert payload[key] == expected, key


def test_cache_miss_still_serves_market_wide_vix(cache_miss) -> None:
    """VIX is a market-wide FMP poll, not per-symbol cache state."""
    assert _get()["vix_level"] == 16.8123


def test_cache_miss_library_enrichment_matches_strict_wire_schema(cache_miss) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=_get(), schema=schema)


def test_cache_miss_keeps_symbol_fields_null(cache_miss) -> None:
    """The fix must not fabricate symbol data: everything that genuinely
    depends on the missing per-symbol cache stays null/neutral."""
    payload = _get()
    for key in (
        "flow_rel_vol",
        "flow_delta_proxy_pct",
        "squeeze_on",
        "ats_state",
        "ats_zscore",
        "signal_level",
        "trade_entry",
    ):
        assert payload[key] is None, key
    assert payload["event_provider_status"] == "unknown"
    assert payload["market_event_blocked"] is None
    assert payload["symbol_event_blocked"] is None


def test_cache_miss_envelope_is_not_overwritten_by_context(cache_miss) -> None:
    """Context is merged UNDER the envelope — a stray key in the bridge must
    never shadow schema/symbol/tf/stale."""
    poisoned = dict(_LIBRARY_CONTEXT) | {"schema": "evil", "symbol": "EVIL", "stale": False}
    cache_miss.setattr(
        main_mod.library_context_bridge, "context_for_symbol", lambda _sym: poisoned
    )
    payload = _get(symbol="NVDA")
    assert payload["schema"] == "smc-live-overlay/1"
    assert payload["symbol"] == "NVDA"
    assert payload["stale"] is True


def test_missing_vix_stays_null(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: _TOKEN)
    monkeypatch.setattr(main_mod.cache, "get_overlay", lambda _sym: None)
    monkeypatch.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: [])
    monkeypatch.setattr(main_mod.cache, "get_vix", lambda: None)
    assert _get()["vix_level"] is None

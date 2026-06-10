"""Tests for silent-substitution audit fixes, round 2 (Issue #2670).

W1: opra_uoa premium uses only ``size`` (no volume substitution, no falsy-or)
W2: open_prep regime_source discloses ATR-proxy synthesis
W3: TechnicalResult.source discloses TV / FMP-fallback / stale-cache
W4: premarket freshness_source + price_source disclosure
W5: opra_uoa ts_source discloses ts_event vs ts_recv
W6: measurement_evidence forwards bias_verdict.source
W7: live_news_snapshot asof_source discloses published_ts vs generated_at
W8: live story state published_ts_source discloses provider vs ingest_now
W9: DataStatusResult.timestamp_substitutions discloses cross-phase backfill
W10: smc_fmp_client get_silent_failure_counts() quantifies swallowed errors
W12: plan_2_8 history snapshots disclose captured_at_source
(W11 was already satisfied on main: all S/R catch-alls log with exc_info.)
"""
from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ────────────────────────────────────────────────────────────────────
# W1 + W5 — opra_uoa premium / timestamp provenance
# ────────────────────────────────────────────────────────────────────

from newsstack_fmp.opra_uoa import _premium_of, detect_unusual_options_activity


def _defn(instrument_id: int = 1) -> dict:
    return {
        "instrument_id": instrument_id,
        "underlying": "AAPL",
        "strike_price": 200.0,
        "expiration": "2026-06-21",
        "instrument_class": "C",
        "raw_symbol": "AAPL_200C",
    }


def test_w1_premium_ignores_volume_field() -> None:
    """A record carrying only ``volume`` (wrong schema) must NOT produce premium."""
    row = {"price": 5.0, "volume": 50_000}  # cumulative session total, no size
    assert _premium_of(row) == 0.0


def test_w1_size_zero_does_not_fall_through_to_volume() -> None:
    """size=0 is data (zero contracts), not 'missing' — no volume substitution."""
    row = {"price": 5.0, "size": 0, "volume": 50_000}
    assert _premium_of(row) == 0.0


def test_w1_premium_from_size_unchanged() -> None:
    row = {"price": 5.0, "size": 1000}
    assert _premium_of(row) == 5.0 * 1000 * 100


def test_w1_output_does_not_cross_fill_volume_from_size() -> None:
    trades = [{
        "instrument_id": 1,
        "ts_event": 1_700_000_000_000 * 1_000_000,
        "price": 5.0,
        "size": 1000,
        "side": "A",
        "publisher_id": 1,
    }]
    out = detect_unusual_options_activity(trades, [_defn()])
    assert len(out) == 1
    assert out[0]["size"] == 1000
    assert out[0]["volume"] is None  # OPRA trades carry no session volume


def test_w5_ts_source_discloses_ts_event() -> None:
    trades = [{
        "instrument_id": 1,
        "ts_event": 1_700_000_000_000 * 1_000_000,
        "price": 5.0,
        "size": 1000,
        "side": "A",
        "publisher_id": 1,
    }]
    out = detect_unusual_options_activity(trades, [_defn()])
    assert out[0]["ts_source"] == "ts_event"


def test_w5_ts_source_discloses_ts_recv_fallback() -> None:
    trades = [{
        "instrument_id": 1,
        "ts_recv": 1_700_000_000_000 * 1_000_000,  # no ts_event
        "price": 5.0,
        "size": 1000,
        "side": "A",
        "publisher_id": 1,
    }]
    out = detect_unusual_options_activity(trades, [_defn()])
    assert out[0]["ts_source"] == "ts_recv"
    assert out[0]["time"]  # clustering timestamp still populated


# ────────────────────────────────────────────────────────────────────
# W2 — regime_source disclosure (source-level: site lives inside the
# generate_open_prep_result orchestrator, not separately callable)
# ────────────────────────────────────────────────────────────────────


def test_w2_regime_source_written_alongside_symbol_regime() -> None:
    """Every row that gets symbol_regime must also get regime_source."""
    src = Path("open_prep/run_open_prep.py").read_text(encoding="utf-8")
    assert 'row["regime_source"] = regime_source' in src
    assert 'regime_source = "atr_proxy"' in src
    assert 'regime_source = "no_data"' in src
    # The disclosure must sit in the same block as the regime assignment.
    sym_idx = src.index('row["symbol_regime"] = sym_regime')
    src_idx = src.index('row["regime_source"] = regime_source')
    assert 0 < src_idx - sym_idx < 500


# ────────────────────────────────────────────────────────────────────
# W3 — TechnicalResult.source provenance
# ────────────────────────────────────────────────────────────────────

import terminal_technicals
from terminal_technicals import TechnicalResult


def test_w3_default_source_is_tradingview() -> None:
    result = TechnicalResult(symbol="AAPL", interval="1D")
    assert result.source == "tradingview"


def test_w3_fmp_fallback_sets_source(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_payload = {
        "symbol": "AAPL",
        "interval": "1D",
        "summary_signal": "BUY",
    }
    fake_module = MagicMock()
    fake_module.fetch_fmp_technicals.return_value = fake_payload
    monkeypatch.setitem(
        __import__("sys").modules, "terminal_fmp_technicals", fake_module
    )
    result = terminal_technicals._fmp_fallback("AAPL", "1D", time.time())
    assert result is not None
    assert result.source == "fmp_fallback"


def test_w3_stale_cache_served_during_cooldown_discloses_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sym, interval = "W3STALE", "1D"
    key = terminal_technicals._cache_key(sym, interval)
    cached = TechnicalResult(
        symbol=sym, interval=interval,
        ts=time.time() - 10_000,  # well past _CACHE_TTL_S
        summary_signal="BUY",
    )
    with terminal_technicals._cache_lock:
        terminal_technicals._cache[key] = cached
    monkeypatch.setattr(
        terminal_technicals, "_tv_is_cooling_down", lambda: True
    )
    try:
        result = terminal_technicals.fetch_technicals(sym, interval)
        assert result.source == "stale_cache"
        assert result.summary_signal == "BUY"
        # The cache entry itself must NOT be mutated.
        with terminal_technicals._cache_lock:
            assert terminal_technicals._cache[key].source == "tradingview"
    finally:
        with terminal_technicals._cache_lock:
            terminal_technicals._cache.pop(key, None)


# ────────────────────────────────────────────────────────────────────
# W4 — premarket freshness_source / price_source
# ────────────────────────────────────────────────────────────────────


def _run_premarket(mock_client: MagicMock) -> dict[str, dict[str, Any]]:
    from open_prep.run_open_prep import _fetch_premarket_context

    with patch("open_prep.run_open_prep._build_mover_seed", return_value=[]):
        premarket, _err = _fetch_premarket_context(
            client=mock_client,
            symbols=["AAPL"],
            today=date.today(),
            run_dt_utc=datetime.now(UTC),
            mover_seed_max_symbols=10,
            analyst_catalyst_limit=0,
        )
    return premarket


def test_w4_trade_data_yields_trade_sources() -> None:
    now_ms = time.time() * 1000.0
    mock_client = MagicMock()
    mock_client.get_batch_aftermarket_quote.return_value = [
        {"symbol": "AAPL", "bidPrice": 184.0, "askPrice": 186.0,
         "volume": 1000, "timestamp": now_ms},
    ]
    mock_client.get_batch_aftermarket_trade.return_value = [
        {"symbol": "AAPL", "price": 185.0, "tradeSize": 500, "timestamp": now_ms},
    ]
    mock_client.get_batch_quotes.return_value = [
        {"symbol": "AAPL", "previousClose": 180.0, "avgVolume": 50_000_000},
    ]
    premarket = _run_premarket(mock_client)
    assert premarket["AAPL"]["premarket_freshness_source"] == "trade"
    assert premarket["AAPL"]["premarket_price_source"] == "trade"


def test_w4_quote_only_discloses_quote_and_mid_sources() -> None:
    now_ms = time.time() * 1000.0
    mock_client = MagicMock()
    mock_client.get_batch_aftermarket_quote.return_value = [
        {"symbol": "AAPL", "bidPrice": 184.0, "askPrice": 186.0,
         "volume": 1000, "timestamp": now_ms},
    ]
    mock_client.get_batch_aftermarket_trade.return_value = []  # no prints
    mock_client.get_batch_quotes.return_value = [
        {"symbol": "AAPL", "previousClose": 180.0, "avgVolume": 50_000_000},
    ]
    premarket = _run_premarket(mock_client)
    # Freshness came from the QUOTE clock, price from the MID — both disclosed.
    assert premarket["AAPL"]["premarket_freshness_source"] == "quote"
    assert premarket["AAPL"]["premarket_price_source"] == "mid"
    assert premarket["AAPL"]["premarket_price"] == pytest.approx(185.0)


# ────────────────────────────────────────────────────────────────────
# W6 — bias_verdict.source forwarded into measurement-evidence details
# ────────────────────────────────────────────────────────────────────


def test_w6_bias_source_written_next_to_bias_direction() -> None:
    src = Path("smc_integration/measurement_evidence.py").read_text(encoding="utf-8")
    assert 'details["bias_source"] = bias_verdict.source' in src
    dir_idx = src.index('details["bias_direction"]')
    src_idx = src.index('details["bias_source"]')
    assert 0 < src_idx - dir_idx < 400


def test_w6_merge_bias_source_values() -> None:
    from smc_core.bias_merge import merge_bias

    verdict = merge_bias(None, None)
    assert verdict.source == "NONE"


# ────────────────────────────────────────────────────────────────────
# W7 — asof_source in live news snapshot meta input
# ────────────────────────────────────────────────────────────────────


def _w7_load(monkeypatch: pytest.MonkeyPatch, payload: dict) -> dict:
    from smc_integration.sources import live_news_snapshot_json as mod

    monkeypatch.setattr(mod, "_load_payload", lambda: payload)
    return mod.load_raw_meta_input("AAPL", "1D")


def test_w7_asof_source_published_ts(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "generated_at": "2026-06-10T10:00:00Z",
        "stories": [
            {
                "tickers": ["AAPL"],
                "headline": "x",
                "summary": "y",
                "published_ts": 1_765_000_000.0,
                "provider_names": ["p"],
            },
        ],
    }
    result = _w7_load(monkeypatch, payload)
    assert result["asof_source"] == "published_ts"
    assert result["asof_ts"] == pytest.approx(1_765_000_000.0)


def test_w7_asof_source_generated_at_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "generated_at": "2026-06-10T10:00:00Z",
        "stories": [],  # no matching articles → generated_at substitute
    }
    result = _w7_load(monkeypatch, payload)
    assert result["asof_source"] == "generated_at"


def test_w7_now_strategy_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "generated_at": "2026-06-10T10:00:00Z",
        "asof_strategy": "now",
        "stories": [],
    }
    from smc_integration.sources import live_news_snapshot_json as mod

    monkeypatch.setattr(mod, "_load_payload", lambda: payload)
    result = mod.load_raw_meta_input("AAPL", "1D", reference_time=1_765_000_000.0)
    assert result["asof_source"] == "now_strategy"


# ────────────────────────────────────────────────────────────────────
# W8 — published_ts_source in live story state
# ────────────────────────────────────────────────────────────────────


def test_w8_provider_timestamp_disclosed() -> None:
    from terminal_live_story_state import _build_state_entry

    item = {
        "ticker": "AAPL",
        "headline": "Something happened",
        "provider": "benzinga",
        "published_ts": 1_765_000_000.0,
    }
    entry = _build_state_entry(
        item, story_key="k1", now=1_765_000_100.0, ttl_s=600.0,
        cooldown_s=60.0, action="alert",
    )
    assert entry["published_ts_source"] == "provider"
    assert entry["published_ts"] == pytest.approx(1_765_000_000.0)


def test_w8_missing_timestamp_discloses_ingest_substitute() -> None:
    from terminal_live_story_state import _build_state_entry

    item = {"ticker": "AAPL", "headline": "No timestamp", "provider": "x"}
    now = 1_765_000_100.0
    entry = _build_state_entry(
        item, story_key="k2", now=now, ttl_s=600.0,
        cooldown_s=60.0, action="alert",
    )
    assert entry["published_ts_source"] == "ingest_now"
    assert entry["published_ts"] == pytest.approx(now)


# ────────────────────────────────────────────────────────────────────
# W9 — DataStatusResult.timestamp_substitutions
# ────────────────────────────────────────────────────────────────────


def test_w9_cross_phase_backfill_disclosed(tmp_path: Path) -> None:
    from databento_volatility_screener import build_data_status_result

    manifest = {
        # No export_generated_at, no intraday_fetched_at → both backfilled.
        "premarket_fetched_at": "2026-06-10T11:00:00+00:00",
        "dataset": "EQUS.MINI",
    }
    (tmp_path / "databento_test_manifest.json").write_text(json.dumps(manifest))
    status = build_data_status_result(tmp_path)
    assert "intraday_fetched_at<-premarket_fetched_at" in status.timestamp_substitutions
    assert "export_generated_at<-premarket_fetched_at" in status.timestamp_substitutions
    assert status.intraday_fetched_at == "2026-06-10T11:00:00+00:00"


def test_w9_native_timestamps_have_no_substitutions(tmp_path: Path) -> None:
    from databento_volatility_screener import build_data_status_result

    manifest = {
        "export_generated_at": "2026-06-10T11:00:00+00:00",
        "intraday_fetched_at": "2026-06-10T10:59:00+00:00",
        "dataset": "EQUS.MINI",
    }
    (tmp_path / "databento_test_manifest.json").write_text(json.dumps(manifest))
    status = build_data_status_result(tmp_path)
    assert status.timestamp_substitutions == ()


# ────────────────────────────────────────────────────────────────────
# W10 — smc_fmp_client silent-failure counter
# ────────────────────────────────────────────────────────────────────


def test_w10_silent_failure_counts_quantify_swallowed_errors() -> None:
    from scripts import smc_fmp_client as mod

    endpoint = "/stable/test-w10-counter"
    with mod._silent_failure_lock:
        mod._SILENT_FAILURE_COUNTS.pop(endpoint, None)
        mod._LOGGED_SILENT_FAILURES.discard((endpoint, "RuntimeError"))
    try:
        mod._log_endpoint_failure_once(endpoint, RuntimeError("boom 1"))
        mod._log_endpoint_failure_once(endpoint, RuntimeError("boom 2"))
        counts = mod.get_silent_failure_counts()
        # Counter counts EVERY swallow, not just the first logged one.
        assert counts[endpoint] == 2
    finally:
        with mod._silent_failure_lock:
            mod._SILENT_FAILURE_COUNTS.pop(endpoint, None)
            mod._LOGGED_SILENT_FAILURES.discard((endpoint, "RuntimeError"))


def test_w10_counts_snapshot_is_a_copy() -> None:
    from scripts import smc_fmp_client as mod

    snap = mod.get_silent_failure_counts()
    snap["/synthetic"] = 999
    assert mod.get_silent_failure_counts().get("/synthetic") is None


# ────────────────────────────────────────────────────────────────────
# W12 — captured_at_source in plan_2_8 history snapshots
# ────────────────────────────────────────────────────────────────────


def test_w12_original_capture_time_disclosed(tmp_path: Path) -> None:
    from scripts.plan_2_8_history_archive import append_snapshot

    result = append_snapshot(
        rollup={"scoring_root": "r1", "files_scanned": 1, "per_tf": {}},
        history_path=tmp_path / "history.jsonl",
        captured_at="2026-06-01T00:00:00Z",
    )
    snap = result["snapshot"]
    assert snap["captured_at_source"] == "original"
    assert snap["captured_at"] == "2026-06-01T00:00:00Z"


def test_w12_backfill_discloses_archival_substitute(tmp_path: Path) -> None:
    from scripts.plan_2_8_history_archive import append_snapshot

    result = append_snapshot(
        rollup={"scoring_root": "r2", "files_scanned": 1, "per_tf": {}},
        history_path=tmp_path / "history.jsonl",
    )
    snap = result["snapshot"]
    assert snap["captured_at_source"] == "archival_backfill"
    assert snap["captured_at"]  # still stamped

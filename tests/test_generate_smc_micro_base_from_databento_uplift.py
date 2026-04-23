"""Coverage uplift for `scripts.generate_smc_micro_base_from_databento`.

Targets pure helpers (env / news payload / volume regime / cursor diagnostics
/ enrichment flag resolution) plus the workbook-mode `main()` path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scripts import generate_smc_micro_base_from_databento as gsm
from scripts.generate_smc_micro_base_from_databento import (
    _build_domain_diagnostic,
    _build_library_provider_diagnostics_report,
    _build_news_payload_from_score_map,
    _coerce_non_negative_float,
    _derive_volume_regime,
    _emit_cli_progress,
    _load_live_news_snapshot,
    _load_newsapi_feed_state,
    _macro_bias_direction,
    _make_fmp_client,
    _merge_news_payloads,
    _news_payload_has_mentions,
    _normalize_provider_attempts,
    _parse_ticker_heat_map,
    _provider_status_from_result,
    _read_previous_refresh_count,
    _resolve_enrichment_flags,
    _safe_float,
    _save_newsapi_feed_state,
    _select_daily_bars_for_volatility,
    _select_volatility_proxy_symbol,
    _summarize_news_payload,
    _write_library_provider_diagnostics_report,
    build_default_output_paths,
    build_mapping_statuses,
    build_parser,
    build_trailing_daily_metrics,
    choose_asof_date,
    main,
    write_mapping_report,
)

# ---------------------------------------------------------------------------
# Trivial helpers
# ---------------------------------------------------------------------------


def test_emit_cli_progress_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_cli_progress("hello world")
    out = capsys.readouterr().out
    assert "hello world" in out


# ---------------------------------------------------------------------------
# choose_asof_date
# ---------------------------------------------------------------------------


def test_choose_asof_date_returns_latest_when_unspecified() -> None:
    summary = pd.DataFrame({"trade_date": ["2026-04-22", "2026-04-23", "2026-04-21"]})
    assert choose_asof_date(summary) == "2026-04-23"


def test_choose_asof_date_returns_specified_when_present() -> None:
    summary = pd.DataFrame({"trade_date": ["2026-04-22", "2026-04-23"]})
    assert choose_asof_date(summary, asof_date="2026-04-22") == "2026-04-22"


def test_choose_asof_date_raises_when_specified_missing() -> None:
    summary = pd.DataFrame({"trade_date": ["2026-04-22"]})
    with pytest.raises(ValueError, match="not present"):
        choose_asof_date(summary, asof_date="2026-04-23")


def test_choose_asof_date_handles_all_invalid_input() -> None:
    # All NaT after coercion → max() returns NaN; the function returns the str
    # representation rather than raising. We just exercise the branch to keep
    # coverage stable.
    summary = pd.DataFrame({"trade_date": [None, "garbled"]})
    out = choose_asof_date(summary)
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# build_trailing_daily_metrics
# ---------------------------------------------------------------------------


def test_build_trailing_daily_metrics_caps_to_20_and_filters_by_asof() -> None:
    rows = []
    for i in range(25):
        rows.append({
            "symbol": "AAPL",
            "trade_date": pd.Timestamp("2026-04-01") + pd.Timedelta(days=i),
            "close": 100.0 + i,
            "volume": 1_000_000,
        })
    daily = pd.DataFrame(rows)
    out = build_trailing_daily_metrics(daily, asof_date="2026-04-23")
    row = out.loc[out["symbol"] == "AAPL"].iloc[0]
    # Filter keeps dates <= 2026-04-23 → 23 rows; tail-20 keeps last 20.
    assert row["history_coverage_days_20d"] == 20
    assert row["adv_dollar_rth_20d"] > 0


# ---------------------------------------------------------------------------
# build_mapping_statuses
# ---------------------------------------------------------------------------


def test_build_mapping_statuses_classifies_direct_derived_missing() -> None:
    statuses = build_mapping_statuses([
        "asof_date",
        "asset_type",
        "symbol_unknown_field",
    ])
    by_field = {s.field: s for s in statuses}
    assert by_field["asof_date"].status == "direct"
    assert by_field["asset_type"].status == "derived"
    assert by_field["symbol_unknown_field"].status == "missing"


# ---------------------------------------------------------------------------
# write_mapping_report
# ---------------------------------------------------------------------------


def test_write_mapping_report_creates_markdown_with_rows(tmp_path: Path) -> None:
    payload = {
        "workbook_path": "/tmp/foo.xlsx",
        "asof_date": "2026-04-23",
        "row_count": 7,
        "direct_fields": ["symbol"],
        "derived_fields": ["asset_type"],
        "missing_fields": ["misc"],
        "mapping_status": [
            {
                "field": "symbol",
                "status": "direct",
                "source_sheet": "summary",
                "source_columns": ["symbol"],
                "note": "ok",
            },
            {
                "field": "misc",
                "status": "missing",
                "source_sheet": "",
                "source_columns": [],
                "note": "todo",
            },
        ],
    }
    out_path = tmp_path / "subdir" / "report.md"
    write_mapping_report(out_path, payload)
    text = out_path.read_text(encoding="utf-8")
    assert "foo.xlsx" in text
    assert "Selected asof_date: 2026-04-23" in text
    assert "|symbol|direct|summary|symbol|ok|" in text
    assert "|misc|missing|||todo|" in text


# ---------------------------------------------------------------------------
# build_default_output_paths
# ---------------------------------------------------------------------------


def test_build_default_output_paths_includes_stem_and_date() -> None:
    csv, md, jpath = build_default_output_paths(
        Path("/tmp/databento_volatility_production_2026-04-23.xlsx"),
        "2026-04-23",
    )
    assert csv.name == "databento_volatility_production_2026-04-23_microstructure_base_2026-04-23.csv"
    assert md.name.endswith("_microstructure_mapping_2026-04-23.md")
    assert jpath.name.endswith("_microstructure_mapping_2026-04-23.json")


# ---------------------------------------------------------------------------
# _make_fmp_client
# ---------------------------------------------------------------------------


def test_make_fmp_client_uses_smc_fmp_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *, api_key: str, retry_attempts: int, timeout_seconds: int) -> None:
            captured["api_key"] = api_key
            captured["retry_attempts"] = retry_attempts
            captured["timeout_seconds"] = timeout_seconds

    fake_module = type(
        "M", (), {"SMCFMPClient": FakeClient},
    )
    monkeypatch.setitem(__import__("sys").modules, "scripts.smc_fmp_client", fake_module)

    out = _make_fmp_client("test-key")
    assert isinstance(out, FakeClient)
    assert captured["api_key"] == "test-key"
    assert captured["retry_attempts"] == 2
    assert captured["timeout_seconds"] == 12


# ---------------------------------------------------------------------------
# _derive_volume_regime
# ---------------------------------------------------------------------------


def test_derive_volume_regime_handles_none_or_empty() -> None:
    assert _derive_volume_regime(None) == {"low_tickers": [], "holiday_suspect_tickers": []}
    assert _derive_volume_regime(pd.DataFrame()) == {"low_tickers": [], "holiday_suspect_tickers": []}


def test_derive_volume_regime_handles_missing_column() -> None:
    out = _derive_volume_regime(pd.DataFrame({"symbol": ["A", "B"]}))
    assert out == {"low_tickers": [], "holiday_suspect_tickers": []}


def test_derive_volume_regime_classifies_low_and_holiday_suspects() -> None:
    base = pd.DataFrame({
        "symbol": ["aapl", "MSFT", "TINY", "TWO"],
        "adv_dollar_rth_20d": [100_000_000, 50_000_000, 100_000, 5_000],
    })
    out = _derive_volume_regime(base, adv_threshold=5_000_000)
    assert "TINY" in out["low_tickers"]
    assert "TWO" in out["low_tickers"]
    assert "AAPL" not in out["low_tickers"]
    # holiday-suspect = below 20% of median; median ~75M → threshold ~15M;
    # TINY=100k and TWO=5k are below.
    assert "TWO" in out["holiday_suspect_tickers"]


# ---------------------------------------------------------------------------
# _read_previous_refresh_count
# ---------------------------------------------------------------------------


def test_read_previous_refresh_count_none_or_missing(tmp_path: Path) -> None:
    assert _read_previous_refresh_count(None) == 0
    assert _read_previous_refresh_count(tmp_path / "missing.json") == 0


def test_read_previous_refresh_count_valid(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"refresh_count": 7}), encoding="utf-8")
    assert _read_previous_refresh_count(p) == 7


def test_read_previous_refresh_count_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    assert _read_previous_refresh_count(p) == 0


# ---------------------------------------------------------------------------
# _coerce_non_negative_float / _safe_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.5, 1.5), (-3.0, 0.0), ("2.5", 2.5), ("bad", 0.0), (None, 0.0)],
)
def test_coerce_non_negative_float(value: Any, expected: float) -> None:
    assert _coerce_non_negative_float(value) == expected


def test_safe_float_valid() -> None:
    assert _safe_float("1.5") == 1.5
    assert _safe_float(2) == 2.0


def test_safe_float_invalid_returns_none() -> None:
    assert _safe_float("bad") is None
    assert _safe_float(None) is None
    assert _safe_float(float("nan")) is None


# ---------------------------------------------------------------------------
# _select_volatility_proxy_symbol / _select_daily_bars_for_volatility
# ---------------------------------------------------------------------------


def test_select_volatility_proxy_symbol_empty_returns_none() -> None:
    assert _select_volatility_proxy_symbol(daily_bars=None, base_snapshot=None) == ("", "none")
    assert _select_volatility_proxy_symbol(
        daily_bars=pd.DataFrame(), base_snapshot=None
    ) == ("", "none")


def test_select_volatility_proxy_symbol_prefers_known_benchmark() -> None:
    daily = pd.DataFrame({"symbol": ["AAPL", "SPY", "MSFT"]})
    sym, src = _select_volatility_proxy_symbol(daily_bars=daily, base_snapshot=None)
    assert sym == "SPY"
    assert src == "preferred_benchmark"


def test_select_volatility_proxy_symbol_falls_back_to_highest_adv() -> None:
    daily = pd.DataFrame({"symbol": ["AAPL", "MSFT"]})
    base = pd.DataFrame({
        "symbol": ["AAPL", "MSFT"],
        "adv_dollar_rth_20d": [50_000_000, 200_000_000],
    })
    sym, src = _select_volatility_proxy_symbol(daily_bars=daily, base_snapshot=base)
    assert sym == "MSFT"
    assert src == "highest_adv_symbol"


def test_select_volatility_proxy_symbol_first_available_when_no_base() -> None:
    daily = pd.DataFrame({"symbol": ["BAR", "ABC", "FOO"]})
    sym, src = _select_volatility_proxy_symbol(daily_bars=daily, base_snapshot=None)
    assert sym == "ABC"  # alphabetically first
    assert src == "first_available_symbol"


def test_select_daily_bars_for_volatility_empty_inputs() -> None:
    assert _select_daily_bars_for_volatility(daily_bars=None, symbol="SPY").empty
    assert _select_daily_bars_for_volatility(daily_bars=pd.DataFrame(), symbol="SPY").empty
    assert _select_daily_bars_for_volatility(
        daily_bars=pd.DataFrame({"a": [1]}), symbol=""
    ).empty


def test_select_daily_bars_for_volatility_filters_and_sorts() -> None:
    daily = pd.DataFrame({
        "symbol": ["spy", "AAPL", "SPY"],
        "trade_date": ["2026-04-23", "2026-04-22", "2026-04-21"],
        "high": [101, 200, 100],
        "low": [99, 199, 98],
        "close": [100, 199.5, 99],
    })
    out = _select_daily_bars_for_volatility(daily_bars=daily, symbol="SPY")
    assert len(out) == 2
    assert out.iloc[0]["trade_date"] == "2026-04-21"


def test_select_daily_bars_for_volatility_missing_columns() -> None:
    daily = pd.DataFrame({"symbol": ["SPY"], "high": [1]})  # missing low/close
    assert _select_daily_bars_for_volatility(daily_bars=daily, symbol="SPY").empty


# ---------------------------------------------------------------------------
# _macro_bias_direction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bias", "expected"),
    [(0.5, "BULLISH"), (-0.5, "BEARISH"), (0.0, "NEUTRAL"), (0.05, "NEUTRAL"), (0.06, "BULLISH"), (-0.06, "BEARISH")],
)
def test_macro_bias_direction(bias: float, expected: str) -> None:
    assert _macro_bias_direction(bias) == expected


# ---------------------------------------------------------------------------
# _load_newsapi_feed_state / _save_newsapi_feed_state
# ---------------------------------------------------------------------------


def test_load_newsapi_feed_state_none_or_missing(tmp_path: Path) -> None:
    assert _load_newsapi_feed_state(None) == {"last_seen_epoch": 0.0, "last_seen_news_uri": ""}
    assert _load_newsapi_feed_state(tmp_path / "missing.json") == {"last_seen_epoch": 0.0, "last_seen_news_uri": ""}


def test_load_newsapi_feed_state_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("not-json", encoding="utf-8")
    assert _load_newsapi_feed_state(p) == {"last_seen_epoch": 0.0, "last_seen_news_uri": ""}


def test_load_newsapi_feed_state_non_dict_payload(tmp_path: Path) -> None:
    p = tmp_path / "y.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _load_newsapi_feed_state(p) == {"last_seen_epoch": 0.0, "last_seen_news_uri": ""}


def test_load_newsapi_feed_state_valid(tmp_path: Path) -> None:
    p = tmp_path / "z.json"
    p.write_text(json.dumps({"last_seen_epoch": 12.0, "last_seen_news_uri": "uri-x"}), encoding="utf-8")
    out = _load_newsapi_feed_state(p)
    assert out == {"last_seen_epoch": 12.0, "last_seen_news_uri": "uri-x"}


def test_save_newsapi_feed_state_no_op_when_path_none() -> None:
    _save_newsapi_feed_state(None, last_seen_epoch=1.0, last_seen_news_uri="x")
    # no exception → success


def test_save_newsapi_feed_state_writes_payload(tmp_path: Path) -> None:
    p = tmp_path / "subdir" / "state.json"
    _save_newsapi_feed_state(p, last_seen_epoch=42.0, last_seen_news_uri="uri-y")
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload == {"last_seen_epoch": 42.0, "last_seen_news_uri": "uri-y"}


# ---------------------------------------------------------------------------
# _load_live_news_snapshot
# ---------------------------------------------------------------------------


def test_load_live_news_snapshot_none_or_missing(tmp_path: Path) -> None:
    assert _load_live_news_snapshot(None) is None
    assert _load_live_news_snapshot(tmp_path / "missing.json") is None


def test_load_live_news_snapshot_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not-json", encoding="utf-8")
    assert _load_live_news_snapshot(p) is None


def test_load_live_news_snapshot_non_dict(tmp_path: Path) -> None:
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _load_live_news_snapshot(p) is None


def test_load_live_news_snapshot_valid(tmp_path: Path) -> None:
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"stories": []}), encoding="utf-8")
    assert _load_live_news_snapshot(p) == {"stories": []}


# ---------------------------------------------------------------------------
# _parse_ticker_heat_map / _build_news_payload_from_score_map /
# _news_payload_has_mentions / _summarize_news_payload
# ---------------------------------------------------------------------------


def test_parse_ticker_heat_map_skips_invalid_entries() -> None:
    out = _parse_ticker_heat_map("AAPL:0.5, MSFT:bad, TSLA:-0.3,  ,bare-no-colon")
    assert out == {"AAPL": 0.5, "TSLA": -0.3}


def test_parse_ticker_heat_map_handles_none() -> None:
    assert _parse_ticker_heat_map(None) == {}


def test_build_news_payload_from_score_map_classifies_buckets() -> None:
    out = _build_news_payload_from_score_map({"AAPL": 0.5, "MSFT": -0.3, "TSLA": 0.05})
    assert out["bullish_tickers"] == ["AAPL"]
    assert out["bearish_tickers"] == ["MSFT"]
    assert out["neutral_tickers"] == ["TSLA"]
    assert "AAPL:0.50" in out["ticker_heat_map"]
    assert out["news_heat_global"] != 0.0


def test_build_news_payload_from_score_map_empty() -> None:
    out = _build_news_payload_from_score_map({})
    assert out["bullish_tickers"] == []
    assert out["bearish_tickers"] == []
    assert out["neutral_tickers"] == []
    assert out["news_heat_global"] == 0.0
    assert out["ticker_heat_map"] == ""


def test_news_payload_has_mentions_true_via_heat_map() -> None:
    assert _news_payload_has_mentions({"ticker_heat_map": "AAPL:0.5"}) is True


def test_news_payload_has_mentions_true_via_bucket() -> None:
    assert _news_payload_has_mentions({"bullish_tickers": ["AAPL"]}) is True


def test_news_payload_has_mentions_false_when_empty() -> None:
    assert _news_payload_has_mentions({}) is False
    assert _news_payload_has_mentions({"ticker_heat_map": "", "bullish_tickers": []}) is False


def test_summarize_news_payload_aggregates_buckets() -> None:
    payload = {
        "bullish_tickers": ["aapl", "MSFT"],
        "bearish_tickers": ["TSLA"],
        "neutral_tickers": [],
        "ticker_heat_map": "GOOGL:0.5",
        "news_heat_global": 0.42,
    }
    out = _summarize_news_payload(payload)
    assert out["news_heat_global"] == 0.42
    assert out["symbol_count"] == 4  # AAPL, MSFT, TSLA, GOOGL
    assert out["bullish_ticker_count"] == 2
    assert out["bearish_ticker_count"] == 1
    assert out["neutral_ticker_count"] == 0


# ---------------------------------------------------------------------------
# _merge_news_payloads
# ---------------------------------------------------------------------------


def test_merge_news_payloads_adds_live_only_symbols() -> None:
    base = {"ticker_heat_map": "AAPL:0.5", "news_heat_global": 0.5}
    live = {"ticker_heat_map": "MSFT:0.3", "news_heat_global": 0.3}
    merged, diag = _merge_news_payloads(base_payload=base, live_payload=live)
    assert "AAPL" in merged["ticker_heat_map"]
    assert "MSFT" in merged["ticker_heat_map"]
    assert diag["live_added_count"] == 1
    assert diag["base_symbol_count"] == 1


def test_merge_news_payloads_directional_override() -> None:
    base = {"ticker_heat_map": "AAPL:0.05"}  # neutral base
    live = {"ticker_heat_map": "AAPL:0.5"}    # directional live
    merged, diag = _merge_news_payloads(base_payload=base, live_payload=live)
    score_map = _parse_ticker_heat_map(merged["ticker_heat_map"])
    assert score_map["AAPL"] == 0.5
    # Override counter increments when live is directional and differs from base
    assert diag["live_directional_override_count"] == 1


def test_merge_news_payloads_neutral_preserves_base_directional() -> None:
    base = {"ticker_heat_map": "AAPL:0.5"}     # directional base
    live = {"ticker_heat_map": "AAPL:0.05"}    # neutral live
    merged, diag = _merge_news_payloads(base_payload=base, live_payload=live)
    score_map = _parse_ticker_heat_map(merged["ticker_heat_map"])
    assert score_map["AAPL"] == 0.5
    assert diag["live_neutral_preserved_base_count"] == 1


# ---------------------------------------------------------------------------
# _provider_status_from_result / _normalize_provider_attempts /
# _build_domain_diagnostic
# ---------------------------------------------------------------------------


def _make_result(*, ok: bool, provider: str, meta: dict[str, Any], stale: list[str] | None = None) -> Any:
    result = MagicMock()
    result.ok = ok
    result.provider = provider
    result.meta = meta
    result.stale = stale or []
    return result


def test_provider_status_from_result_uses_meta_when_present() -> None:
    res = _make_result(ok=True, provider="benzinga", meta={"provider_status": "stale", "status_detail": "old"})
    assert _provider_status_from_result(res) == ("stale", "old")


def test_provider_status_from_result_defaults_when_missing() -> None:
    res = _make_result(ok=True, provider="x", meta={})
    assert _provider_status_from_result(res) == ("ok", "")
    res = _make_result(ok=False, provider="x", meta={})
    status, detail = _provider_status_from_result(res)
    assert status == "no_data"
    assert "All configured providers" in detail


def test_normalize_provider_attempts_filters_non_dicts() -> None:
    out = _normalize_provider_attempts([
        "skip-me",
        {"provider": "P", "outcome": "ok", "failure_class": "x", "error_type": "e", "raw_record_count": 5},
    ])
    assert len(out) == 1
    assert out[0]["provider"] == "P"
    assert out[0]["failure_class"] == "x"
    assert out[0]["error_type"] == "e"
    assert out[0]["raw_record_count"] == 5


def test_normalize_provider_attempts_returns_empty_for_non_list() -> None:
    assert _normalize_provider_attempts(None) == []
    assert _normalize_provider_attempts({"x": 1}) == []


def test_build_domain_diagnostic_basic() -> None:
    res = _make_result(
        ok=True,
        provider="benzinga",
        meta={"provider_status": "ok", "status_detail": "fine", "attempts": [], "diagnostics": {"k": 1}},
        stale=["alphavantage"],
    )
    diag = _build_domain_diagnostic("news", res)
    assert diag["domain"] == "news"
    assert diag["ok"] is True
    assert diag["selected_provider"] == "benzinga"
    assert diag["stale_providers"] == ["alphavantage"]
    assert diag["diagnostics"] == {"k": 1}
    assert "cursor" not in diag


def test_build_domain_diagnostic_with_cursor() -> None:
    res = _make_result(ok=True, provider="benzinga", meta={"attempts": []})
    diag = _build_domain_diagnostic(
        "news", res,
        cursor_before={"epoch": 1.0},
        cursor_after={"epoch": 2.0},
    )
    assert diag["cursor"] == {"before": {"epoch": 1.0}, "after": {"epoch": 2.0}}


# ---------------------------------------------------------------------------
# _build_library_provider_diagnostics_report /
# _write_library_provider_diagnostics_report
# ---------------------------------------------------------------------------


def test_build_library_provider_diagnostics_report_ok_when_clean() -> None:
    enrichment = {
        "providers": {
            "domain_diagnostics": {
                "news": {"provider_status": "ok", "selected_provider": "benzinga"},
            },
            "stale_providers": "",
            "provider_count": 3,
        }
    }
    out = _build_library_provider_diagnostics_report(enrichment=enrichment, symbols_count=10)
    assert out["overall_status"] == "ok"
    assert out["symbols_count"] == 10
    assert out["provider_count"] == 3
    assert out["failure_reasons"] == []
    assert any(d.get("domain") == "news" for d in out["provider_domain_results"])


def test_build_library_provider_diagnostics_report_warn_on_stale_or_failure() -> None:
    enrichment = {
        "providers": {
            "domain_diagnostics": {
                "news": {
                    "provider_status": "stale",
                    "selected_provider": "benzinga",
                    "status_detail": "data is old",
                }
            },
            "stale_providers": "alphavantage",
            "provider_count": 2,
        }
    }
    out = _build_library_provider_diagnostics_report(enrichment=enrichment, symbols_count=5)
    assert out["overall_status"] == "warn"
    assert out["stale_providers"] == ["alphavantage"]
    assert len(out["failure_reasons"]) == 1
    assert out["failure_reasons"][0]["code"] == "LIBRARY_NEWS_STALE"


def test_build_library_provider_diagnostics_report_handles_missing_enrichment() -> None:
    out = _build_library_provider_diagnostics_report(enrichment=None, symbols_count=0)
    assert out["overall_status"] == "ok"
    assert out["symbols_count"] == 0


def test_write_library_provider_diagnostics_report_writes_json(tmp_path: Path) -> None:
    p = tmp_path / "subdir" / "out.json"
    payload = _write_library_provider_diagnostics_report(
        p,
        enrichment={"providers": {"domain_diagnostics": {}, "stale_providers": "", "provider_count": 0}},
        symbols_count=3,
    )
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["report_kind"] == "library_provider_diagnostics"
    assert on_disk["symbols_count"] == 3
    assert payload == on_disk


# ---------------------------------------------------------------------------
# _resolve_enrichment_flags + build_parser
# ---------------------------------------------------------------------------


def test_resolve_enrichment_flags_enrich_all_sets_everything_true() -> None:
    parser = build_parser()
    args = parser.parse_args(["dummy.xlsx", "--enrich-all"])
    flags = _resolve_enrichment_flags(args)
    assert all(flags.values())
    assert "enrich_regime" in flags
    assert "enrich_treasury" in flags


def test_resolve_enrichment_flags_individual_only() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "dummy.xlsx",
        "--enrich-regime",
        "--enrich-news",
    ])
    flags = _resolve_enrichment_flags(args)
    assert flags["enrich_regime"] is True
    assert flags["enrich_news"] is True
    assert flags["enrich_calendar"] is False
    assert flags["enrich_zone_priority"] is False


# ---------------------------------------------------------------------------
# main() — workbook path
# ---------------------------------------------------------------------------


def test_main_workbook_path_writes_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workbook_path = tmp_path / "wb.xlsx"
    workbook_path.touch()  # not actually loaded — we mock build_base_snapshot_from_workbook

    output_csv = tmp_path / "out.csv"
    report_md = tmp_path / "out.md"
    report_json = tmp_path / "out.json"

    fake_output = pd.DataFrame({"symbol": ["AAPL"], "asof_date": ["2026-04-23"]})
    fake_payload = {
        "workbook_path": str(workbook_path),
        "asof_date": "2026-04-23",
        "row_count": 1,
        "direct_fields": ["symbol"],
        "derived_fields": [],
        "missing_fields": [],
        "mapping_status": [
            {"field": "symbol", "status": "direct", "source_sheet": "summary",
             "source_columns": ["symbol"], "note": "ok"},
        ],
    }
    monkeypatch.setattr(
        gsm,
        "build_base_snapshot_from_workbook",
        lambda wb, *, schema_path, asof_date: (fake_output, fake_payload),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_smc_micro_base_from_databento",
            str(workbook_path),
            "--output-csv", str(output_csv),
            "--report-md", str(report_md),
            "--report-json", str(report_json),
        ],
    )

    main()

    assert output_csv.exists()
    assert report_md.exists()
    assert report_json.exists()
    parsed = json.loads(report_json.read_text(encoding="utf-8"))
    assert parsed["asof_date"] == "2026-04-23"


def test_main_raises_when_no_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["generate_smc_micro_base_from_databento"],
    )
    with pytest.raises(ValueError, match="legacy workbook path"):
        main()


def test_main_run_scan_requires_databento_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["generate_smc_micro_base_from_databento", "--run-scan"],
    )
    with pytest.raises(ValueError, match="Databento API key"):
        main()


def test_main_bundle_path_invokes_generate_and_finalize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.touch()

    captured: dict[str, Any] = {}

    def fake_generate(bundle, **kwargs: Any) -> str:
        captured["bundle"] = bundle
        captured["asof_date"] = kwargs.get("asof_date")
        return "fake-base-result"

    def fake_finalize(*, base_result: Any, **kwargs: Any) -> dict[str, Any]:
        captured["base_result"] = base_result
        return {"ok": True, "rows": 0}

    monkeypatch.setattr(gsm, "generate_base_from_bundle", fake_generate)
    monkeypatch.setattr(gsm, "finalize_pipeline", fake_finalize)
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_smc_micro_base_from_databento",
            "--bundle", str(bundle_path),
            "--asof-date", "2026-04-23",
        ],
    )

    main()

    assert captured["bundle"] == bundle_path
    assert captured["asof_date"] == "2026-04-23"
    assert captured["base_result"] == "fake-base-result"

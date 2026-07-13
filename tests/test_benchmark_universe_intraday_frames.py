"""Frame-integrity audit 2026-07-13: genuine full-session intraday frames.

The producer exports ``benchmark_universe_ohlcv_1m`` (full-session 1-minute
bars for the ~24-symbol release+benchmark reference universe) and every
intraday bar loader prefers it over the ~4-minute open-window resample that
degenerated to ~1 bar/day (clone slices; FVG structurally unscorable).
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

import databento_volatility_screener as screener
from smc_integration.measurement_evidence import _load_source_bars
from smc_integration.release_policy import BENCHMARK_ROLLING_SYMBOLS, RELEASE_REFERENCE_SYMBOLS
from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

ROOT = Path(__file__).resolve().parents[1]


# ── Collector unit tests (no network) ────────────────────────────


def _minute_frame(symbols: list[str], minutes: int = 3) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        for idx in range(minutes):
            rows.append(
                {
                    "ts_event": datetime(2026, 7, 10, 13, 30 + idx, tzinfo=UTC),
                    "symbol": symbol,
                    "open": 100.0 + idx,
                    "high": 101.0 + idx,
                    "low": 99.0 + idx,
                    "close": 100.5 + idx,
                    "volume": 1000 + idx,
                }
            )
    return pd.DataFrame(rows)


def test_collector_normalizes_and_sorts(monkeypatch) -> None:
    monkeypatch.setattr(screener, "_make_databento_client", lambda key: object())
    monkeypatch.setattr(screener, "_get_schema_available_end", lambda client, dataset, schema: None)
    captured: dict = {}

    def fake_get_range(client, *, context, **kwargs):
        captured.update(kwargs)
        return "store"

    monkeypatch.setattr(screener, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(
        screener,
        "_store_to_frame",
        lambda store, *, context: _minute_frame(["msft", "AAPL"]),
    )

    frame = screener.collect_benchmark_universe_ohlcv_1m(
        "key",
        dataset="XNAS.ITCH",
        trading_days=[date(2026, 7, 9), date(2026, 7, 10)],
        symbols=["AAPL", "MSFT", "AAPL", " "],
    )
    assert captured["schema"] == "ohlcv-1m"
    assert captured["symbols"] == ["AAPL", "MSFT"]
    assert list(frame.columns) == ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    assert frame["symbol"].tolist() == ["AAPL"] * 3 + ["MSFT"] * 3  # normalized + sorted
    assert frame["timestamp"].is_monotonic_increasing or frame.groupby("symbol")["timestamp"].apply(
        lambda s: s.is_monotonic_increasing
    ).all()


def test_collector_empty_inputs_fail_soft(monkeypatch) -> None:
    monkeypatch.setattr(screener, "_make_databento_client", lambda key: object())
    assert screener.collect_benchmark_universe_ohlcv_1m(
        "key", dataset="XNAS.ITCH", trading_days=[], symbols=["AAPL"]
    ).empty
    assert screener.collect_benchmark_universe_ohlcv_1m(
        "key", dataset="XNAS.ITCH", trading_days=[date(2026, 7, 10)], symbols=[]
    ).empty


def test_collector_clamps_to_schema_available_end(monkeypatch) -> None:
    monkeypatch.setattr(screener, "_make_databento_client", lambda key: object())
    # Available end BEFORE the requested start -> no request, empty frame.
    monkeypatch.setattr(
        screener,
        "_get_schema_available_end",
        lambda client, dataset, schema: pd.Timestamp("2026-07-01", tz="UTC"),
    )

    def boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("get_range must not be called when the window is empty")

    monkeypatch.setattr(screener, "_databento_get_range_with_retry", boom)
    frame = screener.collect_benchmark_universe_ohlcv_1m(
        "key", dataset="XNAS.ITCH", trading_days=[date(2026, 7, 10)], symbols=["AAPL"]
    )
    assert frame.empty


# ── Loader preference tests (synthetic bundle on disk) ───────────


def _write_bundle(tmp_path: Path, *, with_1m: bool, one_m_symbols: list[str]) -> Path:
    base = "databento_volatility_production_test"
    (tmp_path / f"{base}_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    if with_1m:
        one_m = pd.DataFrame(
            {
                "symbol": [s for s in one_m_symbols for _ in range(390)],
                "timestamp": [
                    datetime(2026, 7, 10, 13, 30, tzinfo=UTC) + pd.Timedelta(minutes=idx)
                    for _ in one_m_symbols
                    for idx in range(390)
                ],
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )
        one_m.to_parquet(tmp_path / f"{base}__benchmark_universe_ohlcv_1m.parquet")
    open_window = pd.DataFrame(
        {
            "symbol": ["AAPL", "ZZZZ"],
            "timestamp": [datetime(2026, 7, 10, 13, 35, tzinfo=UTC)] * 2,
            "open": [100.0, 50.0],
            "high": [101.0, 51.0],
            "low": [99.0, 49.0],
            "close": [100.5, 50.5],
            "volume": [10.0, 20.0],
        }
    )
    open_window.to_parquet(tmp_path / f"{base}__full_universe_second_detail_open.parquet")
    return tmp_path


def test_structure_loader_prefers_full_session_1m_frame(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, with_1m=True, one_m_symbols=["AAPL"])
    bars = _load_symbol_bars_from_canonical_exports("AAPL", "5m", bundle)
    assert bars is not None
    assert len(bars) == 390  # full session, not the 1-row open window


def test_structure_loader_falls_back_for_uncovered_symbol(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, with_1m=True, one_m_symbols=["AAPL"])
    bars = _load_symbol_bars_from_canonical_exports("ZZZZ", "5m", bundle)
    assert bars is not None
    assert len(bars) == 1  # served by the open-window fallback


def test_structure_loader_works_on_old_bundles_without_1m_frame(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, with_1m=False, one_m_symbols=[])
    bars = _load_symbol_bars_from_canonical_exports("AAPL", "5m", bundle)
    assert bars is not None
    assert len(bars) == 1


def test_measurement_evidence_loader_prefers_1m_frame(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, with_1m=True, one_m_symbols=["AAPL"])
    bars, mode = _load_source_bars("AAPL", "5m", resolved_inputs={"export_bundle_root": bundle})
    assert mode == "canonical_export_bundle"
    assert len(bars) == 390
    fallback_bars, fallback_mode = _load_source_bars(
        "ZZZZ", "5m", resolved_inputs={"export_bundle_root": bundle}
    )
    assert fallback_mode == "canonical_export_bundle"
    assert len(fallback_bars) == 1


# ── SSOT contract: workflow YAML default == release_policy tuple ─


def test_rolling_workflow_symbol_default_matches_ssot() -> None:
    body = (ROOT / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml").read_text(
        encoding="utf-8"
    )
    expected = ",".join(BENCHMARK_ROLLING_SYMBOLS)
    assert f'SYMBOLS="{expected}"' in body, (
        "The rolling workflow's default symbol list drifted from "
        "release_policy.BENCHMARK_ROLLING_SYMBOLS — the producer exports the 1m frame "
        "for exactly that SSOT set; update both together."
    )


def test_producer_universe_is_union_of_reference_sets() -> None:
    union = sorted(set(RELEASE_REFERENCE_SYMBOLS) | set(BENCHMARK_ROLLING_SYMBOLS))
    assert len(union) >= len(BENCHMARK_ROLLING_SYMBOLS)
    assert set(RELEASE_REFERENCE_SYMBOLS).issubset(union)

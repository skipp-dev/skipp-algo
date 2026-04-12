from __future__ import annotations

import pandas as pd

from smc_integration import service


def test_load_symbol_bars_for_context_normalizes_daily_trade_dates_to_epoch_seconds(monkeypatch) -> None:
    bundle = {
        "frames": {
            "daily_bars": pd.DataFrame(
                [
                    {
                        "symbol": "aapl",
                        "trade_date": "2026-04-10",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.5,
                        "close": 100.5,
                        "volume": 1000,
                    },
                    {
                        "symbol": "AAPL",
                        "trade_date": "2026-04-11",
                        "open": 100.5,
                        "high": 102.0,
                        "low": 100.0,
                        "close": 101.0,
                        "volume": 1200,
                    },
                ]
            )
        }
    }

    monkeypatch.setattr(service, "load_export_bundle", lambda *args, **kwargs: bundle)

    bars = service._load_symbol_bars_for_context("AAPL", "1D")

    assert bars["timestamp"].tolist() == [1775779200, 1775865600]
    assert bars["symbol"].tolist() == ["AAPL", "AAPL"]


def test_load_symbol_bars_for_context_normalizes_intraday_timestamps_to_epoch_seconds(monkeypatch) -> None:
    bundle = {
        "frames": {
            "full_universe_second_detail_open": pd.DataFrame(
                [
                    {
                        "symbol": "aapl",
                        "timestamp": "2026-04-10T13:30:05Z",
                        "open": 100.0,
                        "high": 100.2,
                        "low": 99.9,
                        "close": 100.1,
                        "volume": 500,
                    },
                    {
                        "symbol": "AAPL",
                        "timestamp": "2026-04-10T13:30:06Z",
                        "open": 100.1,
                        "high": 100.3,
                        "low": 100.0,
                        "close": 100.2,
                        "volume": 550,
                    },
                ]
            )
        }
    }

    monkeypatch.setattr(service, "load_export_bundle", lambda *args, **kwargs: bundle)

    bars = service._load_symbol_bars_for_context("AAPL", "15m")

    assert bars["timestamp"].tolist() == [1775827805, 1775827806]
    assert bars["symbol"].tolist() == ["AAPL", "AAPL"]
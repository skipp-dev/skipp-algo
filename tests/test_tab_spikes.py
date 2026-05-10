from __future__ import annotations

from typing import Any

from terminal_tabs.tab_spikes import _build_filtered_spike_rows


def _raw(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "price": 12.5,
        "changesPercentage": 5.0,
        "change": 0.5,
        "volume": 250_000,
        "avgVolume": 50_000,
        "marketCap": 3_000_000_000_000,
    }
    row.update(overrides)
    return row


def test_spikes_tab_uses_scanner_contract_and_local_filters() -> None:
    data = {
        "gainers": [
            _raw(symbol="AAPL", changesPercentage=5.0, price=12.5, volume=250_000),
            _raw(symbol="LOWVOL", changesPercentage=6.0, price=12.5, volume=10_000),
        ],
        "losers": [_raw(symbol="TSLA", changesPercentage=-4.0, price=8.0, volume=175_000)],
        "actives": [_raw(symbol="PENNY", changesPercentage=7.0, price=0.5, volume=500_000)],
    }

    all_rows, filtered_rows = _build_filtered_spike_rows(
        data,
        min_volume=100_000,
        min_change_pct=3.0,
        min_price=1.0,
    )

    assert {row["symbol"] for row in all_rows} == {"AAPL", "LOWVOL", "TSLA", "PENNY"}
    assert [row["symbol"] for row in filtered_rows] == ["AAPL", "TSLA"]
    assert all("change_pct" in row for row in filtered_rows)
    assert all(row["volume"] >= 100_000 for row in filtered_rows)
    assert all(row["price"] >= 1.0 for row in filtered_rows)


def test_spikes_tab_handles_missing_source_lists() -> None:
    all_rows, filtered_rows = _build_filtered_spike_rows(
        {"gainers": [_raw(symbol="AAPL")]},
        min_volume=0,
        min_change_pct=0.0,
        min_price=0.0,
    )

    assert [row["symbol"] for row in all_rows] == ["AAPL"]
    assert [row["symbol"] for row in filtered_rows] == ["AAPL"]

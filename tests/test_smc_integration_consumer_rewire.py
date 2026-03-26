from __future__ import annotations

import pandas as pd
import pytest

import scripts.execute_ibkr_watchlist as consumer


def test_execute_ibkr_watchlist_rewired_to_batch_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str, str]] = []

    def _fake_writer(symbols, timeframe, *, source="auto", output_dir="reports/smc_snapshot_bundles", generated_at=None):
        del output_dir, generated_at
        calls.append((list(symbols), timeframe, source))
        return {"manifest_path": "reports/smc_snapshot_bundles/manifest_15m.json"}

    monkeypatch.setattr(consumer, "write_snapshot_bundles_for_symbols", _fake_writer)

    watchlist = pd.DataFrame(
        {
            "symbol": ["aapl", "MSFT", "AAPL"],
            "trade_date": ["2026-03-06", "2026-03-06", "2026-03-06"],
        }
    )

    manifest = consumer.export_smc_snapshot_bundles_for_watchlist(
        watchlist,
        timeframe="15m",
        source="auto",
        output_dir="reports/smc_snapshot_bundles",
        generated_at=1709254000.0,
    )

    assert manifest["manifest_path"].endswith("manifest_15m.json")
    assert calls == [(["AAPL", "MSFT", "AAPL"], "15m", "auto")]

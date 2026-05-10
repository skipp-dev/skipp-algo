"""Lane 3b (provider-boundary audit follow-up, 2026-04-27): regression test
for ``terminal_databento.fetch_databento_daily_bars`` symbol chunking.

Previously the function did ``db_symbols = db_symbols[:200]`` which
silently dropped every symbol past index 200. With ``fetch_databento_quote_map``
called from the Streamlit terminal in places without a caller-side cap
(``streamlit_terminal.py:1052``), this caused snapshot quotes for the
201st-Nth tickers to be permanently missing.

The fix chunks the symbol list into ``_MAX_SYMBOLS_PER_REQUEST`` batches
and concatenates the resulting frames so the entire requested set is
honored.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pandas as pd
import pytest


@pytest.fixture
def reset_quote_cache():
    """Ensure each test starts with a clean module-level quote cache."""
    import terminal_databento
    terminal_databento._quote_cache.clear()
    terminal_databento._quote_cache_ts = 0.0
    yield
    terminal_databento._quote_cache.clear()
    terminal_databento._quote_cache_ts = 0.0


def _make_fake_store(symbols: list[str]) -> SimpleNamespace:
    """Build a minimal store stub with a .to_df() returning OHLCV bars."""
    rows = []
    ts = pd.Timestamp("2026-04-27", tz="UTC")
    for sym in symbols:
        rows.append({
            "symbol": sym,
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 1_000,
        })
        rows.append({
            "symbol": sym,
            "open": 100.5, "high": 102.0, "low": 100.0,
            "close": 101.5, "volume": 1_500,
        })
    df = pd.DataFrame(rows, index=[ts] * len(rows))
    return SimpleNamespace(to_df=lambda: df)


class TestFetchDatabentoDailyBarsChunking:
    def test_more_than_200_symbols_no_longer_silently_dropped(
        self, reset_quote_cache, monkeypatch
    ):
        import terminal_databento

        os.environ["DATABENTO_API_KEY"] = "test"
        symbols = [f"SYM{i:04d}" for i in range(350)]
        observed_batches: list[list[str]] = []

        def fake_get_range(*, symbols, **_):
            observed_batches.append(list(symbols))
            return _make_fake_store(symbols)

        fake_client = SimpleNamespace(
            timeseries=SimpleNamespace(get_range=fake_get_range),
            metadata=SimpleNamespace(
                list_datasets=lambda: ["DBEQ.BASIC"],
                get_dataset_range=lambda dataset: {"start": "2024-01-01", "end": "2026-12-31"},
            ),
        )

        monkeypatch.setattr(
            terminal_databento, "_make_databento_client", lambda key: fake_client
        )
        monkeypatch.setattr(
            terminal_databento, "_get_schema_available_end", lambda *a, **k: None
        )
        monkeypatch.setattr(
            terminal_databento, "_clamp_request_end", lambda req, end: req
        )
        monkeypatch.setattr(
            terminal_databento, "maybe_refresh_symbol_reference_cache", lambda *a, **k: None
        )
        monkeypatch.setattr(terminal_databento, "_pick_dataset", lambda c, k: "DBEQ.BASIC")

        result = terminal_databento.fetch_databento_daily_bars(symbols)

        # Two batches: 200 + 150
        assert len(observed_batches) == 2
        assert len(observed_batches[0]) == 200
        assert len(observed_batches[1]) == 150
        # The 201st symbol used to be silently dropped; pin that it is now present.
        assert "SYM0200" in result
        # And the last symbol survived too.
        assert "SYM0349" in result

    def test_under_200_symbols_still_uses_single_request(
        self, reset_quote_cache, monkeypatch
    ):
        import terminal_databento

        os.environ["DATABENTO_API_KEY"] = "test"
        symbols = [f"SYM{i:04d}" for i in range(50)]
        call_count = {"n": 0}

        def fake_get_range(*, symbols, **_):
            call_count["n"] += 1
            return _make_fake_store(symbols)

        fake_client = SimpleNamespace(
            timeseries=SimpleNamespace(get_range=fake_get_range),
            metadata=SimpleNamespace(
                list_datasets=lambda: ["DBEQ.BASIC"],
                get_dataset_range=lambda dataset: {"start": "2024-01-01", "end": "2026-12-31"},
            ),
        )

        monkeypatch.setattr(
            terminal_databento, "_make_databento_client", lambda key: fake_client
        )
        monkeypatch.setattr(
            terminal_databento, "_get_schema_available_end", lambda *a, **k: None
        )
        monkeypatch.setattr(
            terminal_databento, "_clamp_request_end", lambda req, end: req
        )
        monkeypatch.setattr(
            terminal_databento, "maybe_refresh_symbol_reference_cache", lambda *a, **k: None
        )
        monkeypatch.setattr(terminal_databento, "_pick_dataset", lambda c, k: "DBEQ.BASIC")

        result = terminal_databento.fetch_databento_daily_bars(symbols)

        assert call_count["n"] == 1
        assert len(result) == 50

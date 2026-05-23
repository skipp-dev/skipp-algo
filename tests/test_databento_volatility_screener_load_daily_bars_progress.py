"""Q3 obs(load_daily_bars): per-batch progress + opt-in parallel fetch.

These tests exercise the new ``progress_callback`` and ``max_workers`` kwargs
on :func:`databento_volatility_screener.load_daily_bars` without making any
real Databento API calls. The Databento client constructor and the per-batch
fetch helper are monkey-patched to return tiny synthetic frames.

The point of these tests is NOT to re-validate fetch correctness (covered by
existing screener tests) — it is to lock in the observability contract that
the producer (``scripts/databento_production_export.py`` Step 5/10) relies on
and to prove the parallel mode produces the same row set as sequential mode.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

import databento_volatility_screener as screener


@pytest.fixture
def synthetic_store_factory():
    """Factory that produces a fake databento store for a given symbol batch.

    Returns an object that ``_store_to_frame`` will accept (it goes through
    ``store.to_df``). We bypass that by monkey-patching ``_store_to_frame``
    directly to return the desired frame.
    """

    def _make(symbols: list[str]) -> pd.DataFrame:
        ts = pd.Timestamp(datetime(2026, 3, 6, 14, 0, tzinfo=timezone.utc))
        rows = []
        for sym in symbols:
            rows.append(
                {
                    "symbol": sym,
                    "ts": ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 10_000,
                }
            )
        return pd.DataFrame(rows)

    return _make


@pytest.fixture
def patched_screener(monkeypatch, synthetic_store_factory):
    """Patch network-touching helpers in ``databento_volatility_screener``."""

    monkeypatch.setattr(screener, "_make_databento_client", lambda key: object())
    # Always allow the request window (no schema-end clamping).
    monkeypatch.setattr(
        screener,
        "_get_schema_available_end",
        lambda client, dataset, schema: date(2030, 1, 1),
    )
    monkeypatch.setattr(
        screener,
        "_daily_request_end_exclusive",
        lambda end, schema_end: end,
    )

    def _fake_get_range(client, *, context, dataset, symbols, schema, start, end):
        # Return a sentinel; the real frame comes from the patched _store_to_frame.
        return ("STORE", tuple(symbols))

    monkeypatch.setattr(screener, "_databento_get_range_with_retry", _fake_get_range)

    def _fake_store_to_frame(store, *, context):
        _, symbols = store
        return synthetic_store_factory(list(symbols))

    monkeypatch.setattr(screener, "_store_to_frame", _fake_store_to_frame)
    # Avoid file-cache writes touching disk.
    monkeypatch.setattr(screener, "_write_cached_frame", lambda path, frame: None)
    return screener


def _common_call_kwargs() -> dict:
    return {
        "databento_api_key": "FAKE-KEY",
        "dataset": "XNAS.ITCH",
        "trading_days": [date(2026, 3, 6), date(2026, 3, 9)],
        "universe_symbols": {f"SYM{i:05d}" for i in range(4500)},
        "cache_dir": None,
        "use_file_cache": False,
        "force_refresh": False,
    }


def test_load_daily_bars_silent_when_no_callback(patched_screener):
    """Default (no callback) emits nothing and still returns rows."""
    frame = patched_screener.load_daily_bars(**_common_call_kwargs())
    assert isinstance(frame, pd.DataFrame)
    # Frame may be filtered/empty depending on dedup; the contract here is
    # that the call completes without raising and without requiring a callback.


def test_load_daily_bars_emits_step_5_progress_markers(patched_screener):
    """Callback receives 'step-5: ' prefixed messages with begin/complete + cache MISS."""
    msgs: list[str] = []
    patched_screener.load_daily_bars(
        **_common_call_kwargs(),
        progress_callback=msgs.append,
    )
    assert msgs, "expected at least one progress marker"
    assert all(m.startswith("step-5: ") for m in msgs), msgs
    assert all("(t+" in m for m in msgs), msgs

    joined = "\n".join(msgs)
    assert "begin" in joined, joined
    assert "cache MISS" in joined, joined
    assert "fetching" in joined and "batches" in joined, joined
    # At least one per-batch begin and one per-batch done.
    assert any("batch " in m and "begin" in m for m in msgs), msgs
    assert any("batch " in m and "done" in m for m in msgs), msgs
    assert any(m.startswith("step-5: complete ") for m in msgs), msgs


def test_load_daily_bars_cache_hit_emits_marker(patched_screener, monkeypatch):
    """When the file cache fully covers the universe, the function emits 'cache HIT'."""
    # Post-#2338 the cache path validates coverage against the requested
    # universe before declaring a hit; a partial cache now correctly emits
    # 'cache PARTIAL' and triggers a delta-fetch. To pin the HIT marker the
    # mocked cached frame must cover every requested symbol.
    universe = sorted(_common_call_kwargs()["universe_symbols"])
    ts = pd.Timestamp(datetime(2026, 3, 6, 14, 0, tzinfo=timezone.utc))
    cached = pd.DataFrame(
        [
            {
                "symbol": sym,
                "ts": ts,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1,
            }
            for sym in universe
        ]
    )
    monkeypatch.setattr(
        patched_screener,
        "_read_cached_frame",
        lambda path, max_age_seconds=None: cached,
    )
    msgs: list[str] = []
    patched_screener.load_daily_bars(
        **{**_common_call_kwargs(), "use_file_cache": True},
        progress_callback=msgs.append,
    )
    joined = "\n".join(msgs)
    assert "cache HIT" in joined, joined
    assert "cache MISS" not in joined, joined


def test_load_daily_bars_parallel_matches_sequential(patched_screener):
    """max_workers>1 must produce the same row set as sequential mode."""
    seq = patched_screener.load_daily_bars(**_common_call_kwargs(), max_workers=1)
    par = patched_screener.load_daily_bars(**_common_call_kwargs(), max_workers=4)
    # Same shape and same multiset of (symbol, trade_date) pairs.
    assert seq.shape == par.shape, (seq.shape, par.shape)
    if not seq.empty:
        seq_keys = sorted(zip(seq["symbol"].tolist(), seq["trade_date"].tolist()))
        par_keys = sorted(zip(par["symbol"].tolist(), par["trade_date"].tolist()))
        assert seq_keys == par_keys


def test_load_daily_bars_parallel_emits_parallel_mode_marker(patched_screener):
    """The fetch-mode marker reports 'parallel' when max_workers>1 and >1 batch."""
    msgs: list[str] = []
    patched_screener.load_daily_bars(
        **_common_call_kwargs(),
        progress_callback=msgs.append,
        max_workers=4,
    )
    joined = "\n".join(msgs)
    assert "mode=parallel" in joined, joined


def test_load_daily_bars_empty_trading_days_short_circuits(patched_screener):
    """Empty trading_days returns an empty frame with no callback emissions."""
    msgs: list[str] = []
    out = patched_screener.load_daily_bars(
        databento_api_key="FAKE",
        dataset="XNAS.ITCH",
        trading_days=[],
        universe_symbols={"AAPL"},
        progress_callback=msgs.append,
    )
    assert out.empty
    # No emissions because the function short-circuits before _t0 is set.
    assert msgs == []

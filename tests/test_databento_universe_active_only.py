"""Tests for active_only / per-day universe snapshot semantics (#2351).

Covers the survivorship-bias guard added to ``databento_universe``:

* ``active_only=True`` (default, live screening) returns only currently active
  symbols and idempotently persists today's snapshot.
* ``active_only=False`` with a ``trade_date`` prefers a previously persisted
  snapshot; on miss, it logs a warning and marks the metadata with
  ``survivorship_bias_risk=True``.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import databento_universe as universe_mod
from databento_universe import (
    UNIVERSE_COLUMNS,
    fetch_us_equity_universe,
    fetch_us_equity_universe_with_metadata,
    save_universe_snapshot,
)


def _build_live_frame(symbols: list[str]) -> pd.DataFrame:
    rows = [
        {
            "symbol": s,
            "company_name": f"{s} Inc.",
            "exchange": "NASDAQ",
            "sector": "",
            "industry": "",
            "market_cap": 0.0,
        }
        for s in symbols
    ]
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    return tmp_path / "universe_snapshots"


@pytest.fixture
def patched_live(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the live Nasdaq Trader fetcher to return ``["Y", "Z"]``.

    Returns a mutable list so individual tests can rewrite the live universe.
    """
    live_symbols: list[str] = ["Y", "Z"]

    def _fake_live(*, exchanges: str = "NASDAQ,NYSE,AMEX") -> pd.DataFrame:
        return _build_live_frame(list(live_symbols))

    monkeypatch.setattr(universe_mod, "_fetch_us_equity_universe_via_nasdaq_trader", _fake_live)
    return live_symbols


def test_active_only_true_returns_only_currently_active(
    patched_live: list[str],
    snapshot_root: Path,
) -> None:
    # Even with a historical snapshot present that includes X, active_only=True
    # must return the live ["Y", "Z"] universe.
    save_universe_snapshot(
        ["X", "Y"],
        trade_date=date(2021, 6, 15),
        source_schema="test",
        root=snapshot_root,
    )

    frame, meta = fetch_us_equity_universe_with_metadata(
        active_only=True,
        trade_date=date(2024, 1, 15),
        snapshot_root=snapshot_root,
    )

    assert sorted(frame["symbol"].tolist()) == ["Y", "Z"]
    assert "X" not in frame["symbol"].tolist()
    assert meta["active_only"] is True
    assert meta["survivorship_bias_risk"] is False
    assert meta["source"] == "nasdaq_trader_symbol_directory"


def test_active_only_false_loads_historical_snapshot(
    patched_live: list[str],
    snapshot_root: Path,
) -> None:
    save_universe_snapshot(
        ["X", "Y"],
        trade_date=date(2021, 6, 15),
        source_schema="nasdaq_trader_symbol_directory",
        root=snapshot_root,
    )

    frame, meta = fetch_us_equity_universe_with_metadata(
        active_only=False,
        trade_date=date(2021, 6, 15),
        snapshot_root=snapshot_root,
    )

    assert sorted(frame["symbol"].tolist()) == ["X", "Y"]
    # Z (a "today" symbol that did not exist on 2021-06-15) must be absent.
    assert "Z" not in frame["symbol"].tolist()
    assert meta["source"] == "universe_snapshot"
    assert meta["selection_reason"] == "historical_snapshot"
    assert meta["active_only"] is False
    assert meta["survivorship_bias_risk"] is False
    assert meta["trade_date"] == "2021-06-15"
    assert meta["snapshot_source_schema"] == "nasdaq_trader_symbol_directory"


def test_active_only_false_without_snapshot_falls_back_with_warning(
    patched_live: list[str],
    snapshot_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=universe_mod.logger.name):
        frame, meta = fetch_us_equity_universe_with_metadata(
            active_only=False,
            trade_date=date(2024, 1, 15),
            snapshot_root=snapshot_root,
        )

    assert sorted(frame["symbol"].tolist()) == ["Y", "Z"]
    assert meta["active_only"] is False
    assert meta["survivorship_bias_risk"] is True
    assert meta["trade_date"] == "2024-01-15"
    # Live source is reported (not "universe_snapshot") when no snapshot exists.
    assert meta["source"] == "nasdaq_trader_symbol_directory"
    assert any("survivorship-bias" in rec.message.lower() for rec in caplog.records), (
        f"expected survivorship-bias warning, got: {[r.message for r in caplog.records]}"
    )


def test_active_only_true_persists_snapshot_idempotently(
    patched_live: list[str],
    snapshot_root: Path,
) -> None:
    today = date(2026, 5, 24)

    # First call writes the snapshot.
    fetch_us_equity_universe(
        active_only=True,
        trade_date=today,
        snapshot_root=snapshot_root,
    )
    snapshot_path = snapshot_root / f"{today.isoformat()}.json"
    assert snapshot_path.exists()
    first_mtime = snapshot_path.stat().st_mtime_ns

    # Second call with a different live universe must NOT overwrite the
    # already-persisted snapshot (idempotency contract).
    patched_live[:] = ["Y", "Z", "NEW"]
    fetch_us_equity_universe(
        active_only=True,
        trade_date=today,
        snapshot_root=snapshot_root,
    )
    assert snapshot_path.stat().st_mtime_ns == first_mtime


def test_default_kwargs_preserve_legacy_behavior(
    patched_live: list[str],
    monkeypatch: pytest.MonkeyPatch,
    snapshot_root: Path,
) -> None:
    # Redirect the default snapshot root so the legacy-default call doesn't
    # litter the real artifacts/ directory during tests.
    monkeypatch.setattr(universe_mod, "UNIVERSE_SNAPSHOT_ROOT", snapshot_root)

    frame, meta = fetch_us_equity_universe_with_metadata()

    assert sorted(frame["symbol"].tolist()) == ["Y", "Z"]
    assert meta["active_only"] is True
    assert meta["trade_date"] is None
    assert meta["survivorship_bias_risk"] is False

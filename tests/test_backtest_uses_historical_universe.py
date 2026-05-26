"""Integration test for the backtest-side universe-snapshot consumer (#2352).

Covers the strict/fallback contract of
:func:`databento_universe.load_universe_for_backtest` and the matching CLI
in ``scripts/load_backtest_universe.py``.

The integration scenario mirrors the issue's acceptance criterion:

* A historical universe snapshot for ``2024-01-15`` contains symbol ``X``.
* The live vendor (mocked) returns ``["Y", "Z"]`` — i.e. ``X`` was delisted.
* A backtest for ``2024-01-15`` MUST surface ``X`` (no survivorship bias).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import databento_universe as universe_mod
from databento_universe import (
    UNIVERSE_COLUMNS,
    MissingUniverseSnapshotError,
    load_universe_for_backtest,
    save_universe_snapshot,
)
from scripts.load_backtest_universe import main as cli_main


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


@pytest.fixture(autouse=True)
def _patched_live_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Today's live vendor returns ``["Y", "Z"]`` — ``X`` is delisted."""

    def _fake_live(*, exchanges: str = "NASDAQ,NYSE,AMEX") -> pd.DataFrame:
        return _build_live_frame(["Y", "Z"])

    monkeypatch.setattr(universe_mod, "_fetch_us_equity_universe_via_nasdaq_trader", _fake_live)


def test_backtest_for_historical_date_surfaces_delisted_symbol(
    snapshot_root: Path,
) -> None:
    save_universe_snapshot(
        ["X", "Y"],
        trade_date=date(2024, 1, 15),
        source_schema="nasdaq_trader_symbol_directory",
        root=snapshot_root,
    )

    frame, metadata = load_universe_for_backtest(
        date(2024, 1, 15),
        strict=True,
        snapshot_root=snapshot_root,
    )

    symbols = set(frame["symbol"].tolist())
    assert "X" in symbols, "backtest must include the delisted symbol from the snapshot"
    assert "Z" not in symbols, "backtest must not include today-only symbols"
    assert metadata["source"] == "universe_snapshot"
    assert metadata["selection_reason"] == "historical_snapshot"
    assert metadata["survivorship_bias_risk"] is False


def test_strict_mode_without_snapshot_raises(snapshot_root: Path) -> None:
    with pytest.raises(MissingUniverseSnapshotError) as excinfo:
        load_universe_for_backtest(
            date(2024, 1, 15),
            strict=True,
            snapshot_root=snapshot_root,
        )
    assert excinfo.value.trade_date == date(2024, 1, 15)
    assert "2024-01-15" in str(excinfo.value)
    assert "survivorship-bias" in str(excinfo.value).lower()


def test_non_strict_without_snapshot_warns_and_falls_back(
    snapshot_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=universe_mod.logger.name):
        frame, metadata = load_universe_for_backtest(
            date(2024, 1, 15),
            strict=False,
            snapshot_root=snapshot_root,
        )

    assert sorted(frame["symbol"].tolist()) == ["Y", "Z"]
    assert metadata["survivorship_bias_risk"] is True
    assert metadata["trade_date"] == "2024-01-15"
    assert any("#2352" in rec.message for rec in caplog.records), (
        f"expected #2352 strict-mode warning, got: {[r.message for r in caplog.records]}"
    )


def test_cli_strict_mode_exits_nonzero_without_snapshot(
    snapshot_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(
        [
            "--trade-date",
            "2024-01-15",
            "--strict-universe",
            "--snapshot-root",
            str(snapshot_root),
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "MissingUniverseSnapshotError" in captured.err or "No persisted universe snapshot" in captured.err


def test_cli_non_strict_emits_json_to_output_file(
    snapshot_root: Path,
    tmp_path: Path,
) -> None:
    save_universe_snapshot(
        ["X", "Y"],
        trade_date=date(2024, 1, 15),
        source_schema="test",
        root=snapshot_root,
    )
    out_path = tmp_path / "resolved.json"
    exit_code = cli_main(
        [
            "--trade-date",
            "2024-01-15",
            "--snapshot-root",
            str(snapshot_root),
            "--output",
            str(out_path),
        ]
    )
    assert exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["trade_date"] == "2024-01-15"
    assert payload["strict_universe"] is False
    assert sorted(payload["symbols"]) == ["X", "Y"]
    assert payload["size"] == 2
    assert payload["metadata"]["source"] == "universe_snapshot"


def test_cli_rejects_invalid_trade_date() -> None:
    with pytest.raises(SystemExit):
        cli_main(["--trade-date", "not-a-date", "--strict-universe"])

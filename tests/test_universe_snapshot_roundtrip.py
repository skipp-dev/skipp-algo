"""Roundtrip tests for per-day universe snapshot persistence (#2351)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from databento_universe import (
    list_universe_snapshots,
    load_universe_snapshot,
    save_universe_snapshot,
)


def test_save_then_load_returns_identical_symbols(tmp_path: Path) -> None:
    trade_date = date(2023, 5, 1)
    symbols = ["AAPL", "MSFT", "NVDA"]

    saved_path = save_universe_snapshot(
        symbols,
        trade_date=trade_date,
        source_schema="nasdaq_trader_symbol_directory",
        root=tmp_path,
    )

    assert saved_path == tmp_path / "2023-05-01.json"
    assert saved_path.exists()

    loaded = load_universe_snapshot(trade_date, root=tmp_path)
    assert loaded is not None
    assert loaded["symbols"] == sorted(symbols)
    assert loaded["source_schema"] == "nasdaq_trader_symbol_directory"
    assert loaded["trade_date"] == "2023-05-01"
    assert loaded["size"] == 3
    # captured_at is a valid ISO-8601 UTC timestamp.
    datetime.fromisoformat(loaded["captured_at"])


def test_save_normalizes_and_deduplicates(tmp_path: Path) -> None:
    save_universe_snapshot(
        ["aapl", "AAPL", "  msft  ", "MSFT", ""],
        trade_date=date(2023, 5, 2),
        source_schema="test",
        root=tmp_path,
    )
    loaded = load_universe_snapshot(date(2023, 5, 2), root=tmp_path)
    assert loaded is not None
    # Sorted, stripped, deduplicated. Case-sensitive by design (Databento expects upper).
    assert loaded["symbols"] == sorted({"aapl", "AAPL", "msft", "MSFT"})


def test_save_is_idempotent_by_default(tmp_path: Path) -> None:
    trade_date = date(2023, 5, 3)
    path = save_universe_snapshot(
        ["A", "B"],
        trade_date=trade_date,
        source_schema="v1",
        root=tmp_path,
    )
    first_payload = path.read_text(encoding="utf-8")

    # Second save with different symbols + overwrite=False keeps the original.
    save_universe_snapshot(
        ["C", "D"],
        trade_date=trade_date,
        source_schema="v2",
        root=tmp_path,
    )
    assert path.read_text(encoding="utf-8") == first_payload

    loaded = load_universe_snapshot(trade_date, root=tmp_path)
    assert loaded is not None
    assert loaded["symbols"] == ["A", "B"]
    assert loaded["source_schema"] == "v1"


def test_save_with_overwrite_updates_file(tmp_path: Path) -> None:
    trade_date = date(2023, 5, 4)
    save_universe_snapshot(["A"], trade_date=trade_date, source_schema="v1", root=tmp_path)
    save_universe_snapshot(
        ["A", "B", "C"],
        trade_date=trade_date,
        source_schema="v2",
        root=tmp_path,
        overwrite=True,
    )
    loaded = load_universe_snapshot(trade_date, root=tmp_path)
    assert loaded is not None
    assert loaded["symbols"] == ["A", "B", "C"]
    assert loaded["source_schema"] == "v2"


def test_load_missing_snapshot_returns_none(tmp_path: Path) -> None:
    assert load_universe_snapshot(date(2099, 1, 1), root=tmp_path) is None


def test_load_corrupt_snapshot_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "2023-05-05.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not valid json", encoding="utf-8")
    assert load_universe_snapshot(date(2023, 5, 5), root=tmp_path) is None


def test_list_universe_snapshots_returns_sorted_dates(tmp_path: Path) -> None:
    assert list_universe_snapshots(root=tmp_path) == []
    for d in [date(2023, 5, 3), date(2023, 5, 1), date(2023, 5, 2)]:
        save_universe_snapshot(["A"], trade_date=d, source_schema="t", root=tmp_path)
    # An unrelated file in the dir must be ignored.
    (tmp_path / "README.md").write_text("ignore me", encoding="utf-8")
    (tmp_path / "not-a-date.json").write_text("{}", encoding="utf-8")
    assert list_universe_snapshots(root=tmp_path) == [
        date(2023, 5, 1),
        date(2023, 5, 2),
        date(2023, 5, 3),
    ]


def test_payload_includes_schema_version(tmp_path: Path) -> None:
    path = save_universe_snapshot(
        ["A"], trade_date=date(2023, 5, 6), source_schema="t", root=tmp_path
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert set(raw.keys()) >= {
        "schema_version",
        "trade_date",
        "captured_at",
        "source_schema",
        "symbols",
        "size",
    }

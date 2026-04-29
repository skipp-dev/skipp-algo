"""Tests for ``scripts/build_phase_a_inputs.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_phase_a_inputs import (
    _SETUP_TYPE_TO_VARIANT,
    build_gate_status,
    build_setups_from_trade_cards,
    main,
)

_HEADER = (
    "rank,symbol,setup_type,entry_trigger,invalidation,risk_management,"
    "atr,tight,mid,wide,stop_reference_source,stop_reference_price,"
    "stop_tight,stop_mid,stop_wide\n"
)


def _write_trade_cards(path: Path, rows: list[str]) -> Path:
    path.write_text(_HEADER + "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return path


def _row(
    rank: int,
    symbol: str,
    setup_type: str,
    *,
    ref_price: float = 100.0,
    stop_mid: float = 95.0,
) -> str:
    # tight/mid/wide ATR columns are not consumed by the producer, but
    # the CSV must remain well-formed.
    return (
        f"{rank},{symbol},{setup_type},trigger,invalidation,risk_mgmt,"
        f"5.0,5.0,7.5,10.0,price,{ref_price},{stop_mid + 2},{stop_mid},{stop_mid - 2}"
    )


def test_build_setups_from_known_setup_type(tmp_path: Path) -> None:
    csv_path = _write_trade_cards(
        tmp_path / "open_prep_trade_cards_x.csv",
        [_row(1, "AAPL", "ORB or VWAP-Hold", ref_price=175.0, stop_mid=170.0)],
    )

    setups = build_setups_from_trade_cards(
        csv_path, trade_date="2026-04-27", quantity=2
    )

    assert setups == [
        {
            "variant": "smc_orb_vwap_hold",
            "symbol": "AAPL",
            "entry": 175.0,
            "stop_loss": 170.0,
            # 2R target: 175 + 2 * (175 - 170) = 185
            "take_profit": 185.0,
            "quantity": 2,
            "trade_date": "2026-04-27",
        }
    ]


def test_unmapped_setup_type_raises(tmp_path: Path) -> None:
    csv_path = _write_trade_cards(
        tmp_path / "tc.csv",
        [_row(1, "AAPL", "Brand-New-Setup", ref_price=100.0, stop_mid=95.0)],
    )
    with pytest.raises(ValueError, match="unmapped setup_type"):
        build_setups_from_trade_cards(csv_path, trade_date="2026-04-27")


def test_stop_at_or_above_entry_rejected(tmp_path: Path) -> None:
    csv_path = _write_trade_cards(
        tmp_path / "tc.csv",
        [_row(1, "AAPL", "ORB or VWAP-Hold", ref_price=100.0, stop_mid=100.0)],
    )
    with pytest.raises(ValueError, match="long-only producer"):
        build_setups_from_trade_cards(csv_path, trade_date="2026-04-27")


def test_gate_status_cold_start_amber() -> None:
    setups = [
        {"variant": "smc_orb_vwap_hold", "symbol": "AAPL"},
        {"variant": "smc_orb_vwap_hold", "symbol": "MSFT"},
        {"variant": "smc_other", "symbol": "TSLA"},
    ]
    assert build_gate_status(setups) == {
        "smc_orb_vwap_hold": "amber",
        "smc_other": "amber",
    }


def test_main_writes_atomic_artefacts(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_trade_cards(
        reports / "open_prep_trade_cards_20260427_120000Z.csv",
        [
            _row(1, "AAPL", "ORB or VWAP-Hold", ref_price=175.0, stop_mid=170.0),
            _row(2, "MSFT", "ORB or VWAP-Hold", ref_price=420.0, stop_mid=410.0),
        ],
    )
    cache = tmp_path / "cache_live"

    rc = main(
        [
            "--reports-dir",
            str(reports),
            "--cache-dir",
            str(cache),
            "--trade-date",
            "2026-04-27",
        ]
    )

    assert rc == 0

    setups_path = cache / "setups_2026-04-27.jsonl"
    gate_path = cache / "gate_status.json"
    assert setups_path.exists()
    assert gate_path.exists()

    setups = json.loads(setups_path.read_text(encoding="utf-8"))
    assert {s["symbol"] for s in setups} == {"AAPL", "MSFT"}
    assert all(s["variant"] == "smc_orb_vwap_hold" for s in setups)
    assert all(s["take_profit"] > s["entry"] > s["stop_loss"] for s in setups)

    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate == {"smc_orb_vwap_hold": "amber"}


def test_setup_type_mapping_table_is_non_empty() -> None:
    # Smoke-test: prevents accidentally emptying the mapping during a
    # refactor, which would silently make every Phase-A run raise.
    assert _SETUP_TYPE_TO_VARIANT
    assert "ORB or VWAP-Hold" in _SETUP_TYPE_TO_VARIANT

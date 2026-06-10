"""Tests for ``scripts/build_phase_a_inputs.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_phase_a_inputs import (
    _SETUP_TYPE_TO_VARIANT,
    _MAX_TRADE_CARDS_AGE_DAYS,
    _latest_trade_cards,
    _trade_cards_age_days,
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


# ---------------------------------------------------------------------------
# B1/C1 (audit pass-4/5, 2026-06-10) — trade-cards staleness guard
# ---------------------------------------------------------------------------


def test_trade_cards_age_days_production_compact_format() -> None:
    """Primary format: export_open_prep_lists.py writes strftime("%Y%m%d_%H%M%SZ")."""
    p = Path("reports/open_prep_trade_cards_20260606_120000Z.csv")
    assert _trade_cards_age_days(p, "2026-06-10") == 4


def test_trade_cards_age_days_iso_dashed_format() -> None:
    """ISO-dashed form is also accepted for backwards-compat."""
    p = Path("reports/open_prep_trade_cards_2026-06-06_120000Z.csv")
    assert _trade_cards_age_days(p, "2026-06-10") == 4


def test_trade_cards_age_days_no_date_in_name() -> None:
    p = Path("reports/open_prep_trade_cards_nodateinname.csv")
    assert _trade_cards_age_days(p, "2026-06-10") is None


def test_producer_filename_format_matches_regex() -> None:
    """Pin-test: the compact filename format from export_open_prep_lists.py
    must be parseable by _trade_cards_age_days.

    If export_open_prep_lists.py ever changes its strftime pattern, this
    test will fail loudly rather than silently treating every real CSV as
    stale (C1/C2, audit pass-5, 2026-06-10).
    """
    # Mirrors: version = now_utc.strftime("%Y%m%d_%H%M%SZ") in export_open_prep_lists.py
    production_name = "open_prep_trade_cards_20260610_081404Z.csv"
    result = _trade_cards_age_days(Path(production_name), "2026-06-10")
    assert result == 0, (
        f"Production filename {production_name!r} returned age={result!r}; "
        "expected 0. Check whether export_open_prep_lists.py changed its "
        "strftime format and update _trade_cards_age_days regex accordingly."
    )


def test_latest_trade_cards_accepts_fresh_production_csv(tmp_path: Path) -> None:
    """Compact-format CSV from today is accepted."""
    reports = tmp_path / "reports"
    reports.mkdir()
    fresh = reports / "open_prep_trade_cards_20260610_090000Z.csv"
    fresh.write_text("", encoding="utf-8")
    result = _latest_trade_cards(reports, trade_date="2026-06-10")
    assert result == fresh


def test_latest_trade_cards_accepts_csv_within_age_cap(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    # 3 days old — within _MAX_TRADE_CARDS_AGE_DAYS (4)
    borderline = reports / "open_prep_trade_cards_20260607_090000Z.csv"
    borderline.write_text("", encoding="utf-8")
    result = _latest_trade_cards(reports, trade_date="2026-06-10")
    assert result == borderline


# W3 — boundary: exactly at cap and one day over (off-by-one guard)
def test_latest_trade_cards_boundary_exactly_max_age(tmp_path: Path) -> None:
    """age == _MAX_TRADE_CARDS_AGE_DAYS (the last accepted value)."""
    from datetime import date, timedelta

    ref = date(2026, 6, 10)
    boundary_date = ref - timedelta(days=_MAX_TRADE_CARDS_AGE_DAYS)
    reports = tmp_path / "reports"
    reports.mkdir()
    fname = f"open_prep_trade_cards_{boundary_date:%Y%m%d}_090000Z.csv"
    (reports / fname).write_text("", encoding="utf-8")
    result = _latest_trade_cards(reports, trade_date="2026-06-10")
    assert result == reports / fname


def test_latest_trade_cards_rejects_just_over_max_age(tmp_path: Path) -> None:
    """age == _MAX_TRADE_CARDS_AGE_DAYS + 1 must be rejected."""
    from datetime import date, timedelta

    ref = date(2026, 6, 10)
    over_date = ref - timedelta(days=_MAX_TRADE_CARDS_AGE_DAYS + 1)
    reports = tmp_path / "reports"
    reports.mkdir()
    fname = f"open_prep_trade_cards_{over_date:%Y%m%d}_090000Z.csv"
    (reports / fname).write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="stale"):
        _latest_trade_cards(reports, trade_date="2026-06-10")


# H6 — future-dated CSVs must also be rejected (age < 0)
def test_latest_trade_cards_rejects_future_dated_csv(tmp_path: Path) -> None:
    """A CSV timestamped in the future (e.g. TZ drift) is rejected."""
    reports = tmp_path / "reports"
    reports.mkdir()
    future = reports / "open_prep_trade_cards_20261231_090000Z.csv"
    future.write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="stale"):
        _latest_trade_cards(reports, trade_date="2026-06-10")


def test_latest_trade_cards_rejects_stale_csv(tmp_path: Path) -> None:
    """A CSV older than _MAX_TRADE_CARDS_AGE_DAYS must raise FileNotFoundError.

    This guards the invariant that stale entry/stop prices from days ago
    are never silently stamped with today's trade_date in the Phase-A
    audit trail (B1, audit pass-4, 2026-06-10).
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    stale = reports / "open_prep_trade_cards_20260601_090000Z.csv"  # 9 days old
    stale.write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="stale"):
        _latest_trade_cards(reports, trade_date="2026-06-10")


def test_latest_trade_cards_rejects_unparseable_date_in_name(tmp_path: Path) -> None:
    """A CSV whose filename carries no parseable date is treated as stale."""
    reports = tmp_path / "reports"
    reports.mkdir()
    no_date = reports / "open_prep_trade_cards_nodateinname.csv"
    no_date.write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="stale"):
        _latest_trade_cards(reports, trade_date="2026-06-10")


def test_latest_trade_cards_skips_staleness_when_no_trade_date(tmp_path: Path) -> None:
    """trade_date=None disables the staleness guard (used by explicit --trade-cards-csv)."""
    reports = tmp_path / "reports"
    reports.mkdir()
    old = reports / "open_prep_trade_cards_20200101_090000Z.csv"
    old.write_text("", encoding="utf-8")
    result = _latest_trade_cards(reports, trade_date=None)
    assert result == old


def test_main_rejects_stale_csv_without_explicit_path(tmp_path: Path) -> None:
    """main() propagates the FileNotFoundError from _latest_trade_cards when
    the newest discovered CSV is too old — no --trade-cards-csv override."""
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_trade_cards(
        reports / "open_prep_trade_cards_20260501_120000Z.csv",  # >4d stale
        [_row(1, "AAPL", "ORB or VWAP-Hold")],
    )
    with pytest.raises((FileNotFoundError, SystemExit)):
        main([
            "--reports-dir", str(reports),
            "--cache-dir", str(tmp_path / "cache"),
            "--trade-date", "2026-06-10",
        ])

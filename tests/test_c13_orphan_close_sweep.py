"""Orphan sweep (#4848-Nacharbeit): documented orphans instead of silent ones.

The pre-GTC/EOD-flatten era left filled-but-never-closed records in old day
audits (measured 2026-08-19: 38 across 12 files); their close prices are
unrecoverable and no cron re-reads those files. The sweep stamps them as
explicit orphans, and the backfill counts orphans separately so they can
never inflate ``records_pending_close`` (the F-V3-15 ``closable`` base).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_live_outcomes import ORPHANED_STATUS, backfill_live_outcomes
from scripts.c13_orphan_close_sweep import main, sweep


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _open_fill(intent_id: str) -> dict:
    return {
        "intent_id": intent_id,
        "action": "filled",
        "symbol": "AMD",
        "entry_price": 100.0,
        "fill_price": 100.5,
        "stop_loss": 95.0,
        "size_usd": 100.5,
    }


def _closed_fill(intent_id: str) -> dict:
    return {
        "intent_id": intent_id,
        "action": "tp_hit",
        "symbol": "MSFT",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "stop_loss": 95.0,
        "close_price": 110.0,
        "close_action": "tp_hit",
        "size_usd": 100.0,
        "phase": "paper",
    }


@pytest.fixture()
def live_dir(tmp_path: Path) -> Path:
    d = tmp_path / "live"
    d.mkdir()
    _write_jsonl(
        d / "incubation_2026-08-17.jsonl",
        [
            _open_fill("smc-AMD-2026-08-17"),
            _open_fill("smc-NVDA-2026-08-17"),
            _closed_fill("smc-MSFT-2026-08-17"),
            {"intent_id": "smc-TSLA-2026-08-17", "action": "audit_only"},
        ],
    )
    # Cutoff day itself: live trading day, must never be touched.
    _write_jsonl(d / "incubation_2026-08-19.jsonl", [_open_fill("smc-PWR-2026-08-19")])
    # Commercial lane has its own reconcile — out of scope by filename shape.
    _write_jsonl(
        d / "incubation_commercial_2026-08-17.jsonl",
        [_open_fill("smc-COM-2026-08-17")],
    )
    return d


def test_dry_run_reports_but_writes_nothing(live_dir: Path) -> None:
    before = {p.name: p.read_bytes() for p in live_dir.iterdir()}

    summary = sweep(live_dir, before="2026-08-19", reason="r", apply=False)["orphan_sweep"]

    assert summary["dry_run"] is True
    assert summary["records_orphaned"] == 2
    assert summary["records_left_open_at_or_after_cutoff"] == 1
    assert summary["files_changed"] == 1
    assert summary["per_file"] == {"incubation_2026-08-17.jsonl": 2}
    assert {p.name: p.read_bytes() for p in live_dir.iterdir()} == before


def test_apply_stamps_only_pre_cutoff_open_fills(live_dir: Path) -> None:
    reason = "pre-GTC era (#4848): closed by manual flatten without recorded price"

    summary = sweep(live_dir, before="2026-08-19", reason=reason, apply=True)["orphan_sweep"]

    assert summary["records_orphaned"] == 2
    records = _read_jsonl(live_dir / "incubation_2026-08-17.jsonl")
    stamped = [r for r in records if r.get("outcome_status") == ORPHANED_STATUS]
    assert {r["intent_id"] for r in stamped} == {"smc-AMD-2026-08-17", "smc-NVDA-2026-08-17"}
    assert all(r["orphan_reason"] == reason and r["orphaned_at"] for r in stamped)
    # Closed and audit_only records pass through with their content unchanged.
    closed = next(r for r in records if r["intent_id"] == "smc-MSFT-2026-08-17")
    assert closed["close_action"] == "tp_hit" and "orphan_reason" not in closed
    audit_only = next(r for r in records if r["intent_id"] == "smc-TSLA-2026-08-17")
    assert "outcome_status" not in audit_only
    # The cutoff-day file and the commercial file are byte-untouched.
    assert _read_jsonl(live_dir / "incubation_2026-08-19.jsonl")[0].get("outcome_status") is None
    assert _read_jsonl(live_dir / "incubation_commercial_2026-08-17.jsonl")[0].get(
        "outcome_status"
    ) is None


def test_second_apply_is_a_noop(live_dir: Path) -> None:
    sweep(live_dir, before="2026-08-19", reason="r", apply=True)
    after_first = {p.name: p.read_bytes() for p in live_dir.iterdir()}

    summary = sweep(live_dir, before="2026-08-19", reason="r", apply=True)["orphan_sweep"]

    assert summary["records_orphaned"] == 0
    assert summary["files_changed"] == 0
    assert {p.name: p.read_bytes() for p in live_dir.iterdir()} == after_first


def test_orphans_never_gain_prices_or_outcomes(live_dir: Path) -> None:
    sweep(live_dir, before="2026-08-19", reason="r", apply=True)

    for record in _read_jsonl(live_dir / "incubation_2026-08-17.jsonl"):
        if record.get("outcome_status") != ORPHANED_STATUS:
            continue
        assert "close_price" not in record
        assert "outcome_pnl_usd" not in record
        assert "outcome_r_multiple" not in record


def test_backfill_counts_orphans_outside_pending_close(live_dir: Path) -> None:
    """Orphans must leave the F-V3-15 base: pending_close excludes them."""
    path = live_dir / "incubation_2026-08-17.jsonl"
    sweep(live_dir, before="2026-08-19", reason="r", apply=True)

    summary = backfill_live_outcomes(path)

    assert summary["records_orphaned"] == 2
    # audit_only bleibt pending (und wird dort per Zaehler ausgewiesen);
    # die zwei Waisen tauchen NICHT mehr als pending auf.
    assert summary["records_pending_close"] == 1
    assert summary["records_audit_only"] == 1
    assert summary["records_backfilled"] == 1  # der tp_hit-Record bekommt sein Outcome


def test_before_must_be_an_iso_date(live_dir: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--live-dir", str(live_dir), "--before", "gestern", "--reason", "r"])


def test_reason_is_required(live_dir: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--live-dir", str(live_dir), "--before", "2026-08-19"])

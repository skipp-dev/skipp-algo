"""CLI contract for the incubation → execution-session adapter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.incubation_to_execution_sessions import main


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "action": "filled",
        "entry_price": 200.0,
        "fill_price": 199.0,
        "filled_shares": 1.0,
        "intent_id": "smc-NVDA-2026-07-13-port7497",
        "phase": "paper",
        "quantity": 1,
        "reconciled_at": "2026-07-13T21:05:05+00:00",
        "size_scale": 0.1,
        "stop_loss": 190.0,
        "symbol": "NVDA",
        "take_profit": 220.0,
        "ts": "2026-07-13T13:28:06+00:00",
        "variant": "smc_orb_vwap_hold",
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def test_it_writes_one_session_file_per_trading_day(tmp_path: Path) -> None:
    ledger = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row()])
    out_dir = tmp_path / "sessions"

    rc = main([str(ledger), "--out-dir", str(out_dir), "--report", str(tmp_path / "r.json")])

    assert rc == 0
    written = sorted(p.name for p in out_dir.glob("*.json"))
    assert written == ["execution_session_2026-07-13.json"]
    session = json.loads((out_dir / written[0]).read_text(encoding="utf-8"))
    assert session["submission"]["placements"][0]["orders"][0]["lmt_price"] == 200.0


def test_the_report_names_what_was_excluded(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path,
        "incubation_2026-07-16.jsonl",
        [
            _row(ts="2026-07-16T13:28:06+00:00"),
            _row(
                action="submit_failed",
                intent_id="smc-AMD-2026-07-16-port7497",
                ts="2026-07-16T13:28:06+00:00",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
            _row(
                action="paper_submitted",
                intent_id="smc-META-2026-07-16-port7497",
                ts="2026-07-16T13:28:06+00:00",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
        ],
    )
    report_path = tmp_path / "report.json"

    rc = main([str(ledger), "--out-dir", str(tmp_path / "s"), "--report", str(report_path)])

    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["rows_skipped_never_submitted"] == 1
    assert report["rows_without_fill_evidence"] == 1
    assert report["entry_orders"] == 2
    assert report["entry_fills"] == 1
    assert report["unreconciled_days"] == "count"


def test_nothing_usable_does_not_look_like_success(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path,
        "incubation_2026-07-16.jsonl",
        [_row(action="submit_failed", fill_price=None, filled_shares=None, reconciled_at=None)],
    )

    rc = main([str(ledger), "--out-dir", str(tmp_path / "s")])

    assert rc == 2


def test_a_row_it_cannot_convert_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row(stop_loss=220.0)])

    rc = main([str(ledger), "--out-dir", str(tmp_path / "s")])

    assert rc == 1
    assert "direction" in capsys.readouterr().err


def test_the_written_sessions_feed_the_calibrator(tmp_path: Path) -> None:
    """The whole point: the output must be what §5's estimator consumes."""
    from governance.execution_costs import calibrate_costs

    rows = [
        _row(
            intent_id=f"smc-S{i}-2026-07-13-port7497",
            symbol=f"S{i}",
            entry_price=100.0 + i,
            fill_price=100.0 + i,
            stop_loss=90.0 + i,
            take_profit=120.0 + i,
        )
        for i in range(25)
    ]
    ledger = _write(tmp_path, "incubation_2026-07-13.jsonl", rows)
    out_dir = tmp_path / "sessions"
    assert main([str(ledger), "--out-dir", str(out_dir)]) == 0

    sessions = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(out_dir.glob("*.json"))
    ]
    calibration = calibrate_costs(sessions, n_bootstrap=50)

    assert calibration.n_cost_samples == 25
    assert calibration.fill_rate == 1.0
    assert calibration.measurable is True
    assert calibration.round_turn_cost_bps > 0  # commission is never free


def test_stale_session_files_do_not_survive_a_rerun(tmp_path: Path) -> None:
    """The documented consumer globs the out-dir; leftovers get re-pooled."""
    out_dir = tmp_path / "sessions"
    out_dir.mkdir()
    (out_dir / "execution_session_2020-01-01.json").write_text("{}", encoding="utf-8")
    ledger = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row()])

    rc = main([str(ledger), "--out-dir", str(out_dir), "--report", str(tmp_path / "r.json")])

    assert rc == 0
    assert sorted(p.name for p in out_dir.glob("*.json")) == [
        "execution_session_2026-07-13.json"
    ]
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["stale_files_removed"] == 1


def test_a_non_numeric_ledger_value_is_an_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row(entry_price="n/a")])

    rc = main([str(ledger), "--out-dir", str(tmp_path / "s")])

    assert rc == 1
    assert capsys.readouterr().err.startswith("error:")


def test_skipping_unreconciled_days_is_opt_in_and_recorded(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path,
        "incubation_2026-07-07.jsonl",
        [
            _row(
                action="paper_submitted",
                ts="2026-07-07T13:28:06+00:00",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            )
        ],
    )
    report_path = tmp_path / "report.json"

    rc = main(
        [
            str(ledger),
            "--out-dir",
            str(tmp_path / "s"),
            "--report",
            str(report_path),
            "--unreconciled-days",
            "skip",
        ]
    )

    assert rc == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["unreconciled_days"] == "skip"
    assert report["skipped_session_dates"] == ["2026-07-07"]

"""Tests for scripts/f2_status_alert.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_status_alert import main, _scan_reports, _trailing_streak


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(reports: Path, decisions: dict[str, str]) -> None:
    """Seed reports/{date}: decision pairs into the directory."""
    for date, decision in decisions.items():
        _write(reports / f"f2_promotion_gate_{date}.json", {"decision": decision})


def test_alert_fires_on_three_consecutive_skipped(tmp_path: Path) -> None:
    reports = tmp_path / "r"
    _seed(reports, {
        "2026-04-19": "skipped",
        "2026-04-20": "skipped",
        "2026-04-21": "skipped",
    })
    rc = main(["--reports-dir", str(reports), "--threshold", "3"])
    assert rc == 0


def test_alert_does_not_fire_below_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = tmp_path / "r"
    _seed(reports, {
        "2026-04-19": "skipped",
        "2026-04-20": "skipped",
    })
    rc = main(["--reports-dir", str(reports), "--threshold", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["alerted"] is False
    assert payload["streak"] == 2


def test_promote_in_middle_resets_streak_to_trailing_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Streak counts only the trailing run of non-progressing decisions."""
    reports = tmp_path / "r"
    _seed(reports, {
        "2026-04-19": "skipped",
        "2026-04-20": "skipped",
        "2026-04-21": "promote",   # resets the streak
        "2026-04-22": "skipped",
        "2026-04-23": "hold",
    })
    rc = main(["--reports-dir", str(reports), "--threshold", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["alerted"] is False
    assert payload["streak"] == 2
    assert payload["decisions"] == ["skipped", "hold"]


def test_mixed_non_progressing_decisions_count_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = tmp_path / "r"
    _seed(reports, {
        "2026-04-19": "skipped",
        "2026-04-20": "insufficient_data",
        "2026-04-21": "hold",
        "2026-04-22": "skipped",
    })
    rc = main(["--reports-dir", str(reports), "--threshold", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["alerted"] is True
    assert payload["streak"] == 4


def test_rollback_decision_is_progressing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """rollback (rc=2) is its own loud signal — must NOT count as a streak."""
    reports = tmp_path / "r"
    _seed(reports, {
        "2026-04-19": "skipped",
        "2026-04-20": "skipped",
        "2026-04-21": "rollback",
    })
    rc = main(["--reports-dir", str(reports), "--threshold", "2"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["alerted"] is False
    assert payload["streak"] == 0


def test_unreadable_report_treated_as_skipped(tmp_path: Path) -> None:
    reports = tmp_path / "r"
    reports.mkdir()
    (reports / "f2_promotion_gate_2026-04-19.json").write_text("not json", encoding="utf-8")
    rows = _scan_reports(reports)
    assert rows == [("2026-04-19", "skipped")]


def test_missing_reports_dir_returns_no_alert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--reports-dir", str(tmp_path / "does-not-exist"), "--threshold", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["alerted"] is False
    assert payload["streak"] == 0


def test_invalid_threshold_returns_one(tmp_path: Path) -> None:
    rc = main(["--reports-dir", str(tmp_path), "--threshold", "0"])
    assert rc == 1


def test_trailing_streak_helper_direct() -> None:
    rows = [
        ("2026-04-19", "promote"),
        ("2026-04-20", "skipped"),
        ("2026-04-21", "hold"),
    ]
    dates, decisions = _trailing_streak(rows)
    assert dates == ["2026-04-20", "2026-04-21"]
    assert decisions == ["skipped", "hold"]

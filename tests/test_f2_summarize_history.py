"""Tests for scripts/f2_summarize_history.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_summarize_history import (
    DEFAULT_TREND_WINDOW,
    SUMMARY_SCHEMA_VERSION,
    build_summary,
    main,
    summarize_history,
    summarize_reports,
)

# ---------------------------------------------------------------------------
# summarize_history()
# ---------------------------------------------------------------------------


def test_history_summary_empty() -> None:
    s = summarize_history([])
    assert s["len"] == 0
    assert s["last"] is None
    assert s["trend_mean"] is None
    assert s["consecutive_worse"] == 0
    assert s["consecutive_better"] == 0


def test_history_summary_basic() -> None:
    s = summarize_history([-0.01, -0.02, 0.005, -0.001], trend_window=2)
    assert s["len"] == 4
    assert s["last"] == pytest.approx(-0.001)
    assert s["trend_mean"] == pytest.approx((0.005 + -0.001) / 2)


def test_consecutive_worse_counts_trailing_positives() -> None:
    s = summarize_history([-0.01, 0.001, 0.002, 0.003])
    assert s["consecutive_worse"] == 3
    assert s["consecutive_better"] == 0


def test_consecutive_better_counts_trailing_negatives() -> None:
    s = summarize_history([0.01, -0.001, -0.002, -0.003])
    assert s["consecutive_worse"] == 0
    assert s["consecutive_better"] == 3


def test_consecutive_breaks_on_zero() -> None:
    # Exactly 0 is neither better nor worse.
    s = summarize_history([-0.01, -0.02, 0.0])
    assert s["consecutive_worse"] == 0
    assert s["consecutive_better"] == 0


def test_default_trend_window_is_30() -> None:
    assert DEFAULT_TREND_WINDOW == 30


# ---------------------------------------------------------------------------
# summarize_reports()
# ---------------------------------------------------------------------------


def _write_report(path: Path, *, decision: str, sprt: dict | None = None) -> None:
    payload: dict = {"schema_version": 1, "decision": decision}
    if sprt is not None:
        payload["sprt"] = sprt
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reports_summary_counts_decisions_and_picks_latest(tmp_path: Path) -> None:
    d = tmp_path / "reports"
    d.mkdir()
    _write_report(d / "f2_promotion_gate_2026-04-19.json", decision="hold")
    _write_report(d / "f2_promotion_gate_2026-04-20.json", decision="hold")
    _write_report(
        d / "f2_promotion_gate_2026-04-21.json",
        decision="rollback",
        sprt={"decision": "accept_h0", "n": 600},
    )
    _write_report(d / "unrelated.json", decision="ignored")  # no date pattern

    s = summarize_reports(d)
    assert s["reports_seen"] == 3
    assert s["decisions"] == {"hold": 2, "rollback": 1}
    assert s["latest_report"]["date"] == "2026-04-21"
    assert s["latest_report"]["decision"] == "rollback"
    assert s["latest_sprt"] == {"decision": "accept_h0", "n": 600}


def test_reports_summary_handles_missing_dir(tmp_path: Path) -> None:
    s = summarize_reports(tmp_path / "nope")
    assert s == {
        "reports_seen": 0,
        "decisions": {},
        "latest_report": None,
        "latest_sprt": None,
    }


def test_reports_summary_skips_malformed_files(tmp_path: Path) -> None:
    d = tmp_path / "reports"
    d.mkdir()
    (d / "f2_promotion_gate_2026-04-21.json").write_text("{not json", encoding="utf-8")
    (d / "f2_promotion_gate_2026-04-22.json").write_text(json.dumps([]), encoding="utf-8")  # not dict
    _write_report(d / "f2_promotion_gate_2026-04-23.json", decision="hold")

    s = summarize_reports(d)
    assert s["reports_seen"] == 1
    assert s["decisions"] == {"hold": 1}
    assert s["latest_report"]["date"] == "2026-04-23"


# ---------------------------------------------------------------------------
# build_summary()
# ---------------------------------------------------------------------------


def test_build_summary_pins_schema_version(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([-0.001]), encoding="utf-8")
    summary = build_summary(history_path=history, reports_dir=None)
    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["history"]["last"] == pytest.approx(-0.001)
    assert "decisions" not in summary  # reports_dir omitted


def test_build_summary_includes_reports_when_provided(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.0]), encoding="utf-8")
    reports = tmp_path / "r"
    reports.mkdir()
    _write_report(reports / "f2_promotion_gate_2026-04-21.json", decision="promote")
    summary = build_summary(history_path=history, reports_dir=reports)
    assert summary["decisions"] == {"promote": 1}
    assert summary["latest_report"]["date"] == "2026-04-21"


def test_build_summary_handles_missing_history(tmp_path: Path) -> None:
    summary = build_summary(history_path=tmp_path / "missing.json", reports_dir=None)
    assert summary["history"]["len"] == 0
    assert summary["history"]["last"] is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_to_stdout(tmp_path: Path, capsys) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([-0.001]), encoding="utf-8")
    rc = main(["--history", str(history)])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["schema_version"] == SUMMARY_SCHEMA_VERSION


def test_cli_writes_to_file(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([-0.001]), encoding="utf-8")
    out_path = tmp_path / "out" / "summary.json"
    rc = main([
        "--history", str(history),
        "--output", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["history"]["len"] == 1


def test_cli_returns_1_on_invalid_trend_window(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.0]), encoding="utf-8")
    rc = main(["--history", str(history), "--trend-window", "0"])
    assert rc == 1


def test_cli_returns_1_on_non_list_history(tmp_path: Path) -> None:
    bad = tmp_path / "h.json"
    bad.write_text(json.dumps({"oops": True}), encoding="utf-8")
    rc = main(["--history", str(bad)])
    assert rc == 1

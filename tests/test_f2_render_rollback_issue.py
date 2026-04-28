"""Tests for scripts/f2_render_rollback_issue.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_render_rollback_issue import (
    ISSUE_LABEL,
    TITLE_PREFIX,
    main,
    render_body,
    render_title,
)


def _report() -> dict:
    return {
        "schema_version": 1,
        "decision": "rollback",
        "kpi_metrics": [
            {"metric": "calibrated_brier", "control": 0.16, "treatment": 0.18, "delta": 0.02},
            {"metric": "calibrated_ece",   "control": 0.10, "treatment": 0.12, "delta": 0.02},
            {"metric": "hit_rate_pct",     "control": 60.0, "treatment": 58.0, "delta": -2.0},
        ],
        "sprt": {
            "decision": "accept_h0",
            "n": 600, "k": 348,
            "llr": -0.42,
            "p0": 0.55, "p1": 0.60,
            "alpha": 0.05, "beta": 0.20,
        },
        "rollback_window": [0.011, 0.018],
    }


# ---------------------------------------------------------------------------
# render_title()
# ---------------------------------------------------------------------------


def test_title_includes_decision_and_prefix() -> None:
    t = render_title(_report())
    assert t.startswith(TITLE_PREFIX)
    assert "rollback" in t


def test_title_includes_date_when_provided() -> None:
    t = render_title(_report(), date="2026-04-21")
    assert "2026-04-21" in t


def test_title_handles_missing_decision() -> None:
    t = render_title({})
    assert "unknown" in t


# ---------------------------------------------------------------------------
# render_body()
# ---------------------------------------------------------------------------


def test_body_contains_metric_rows_and_sprt_block() -> None:
    body = render_body(_report(), date="2026-04-21")
    assert "calibrated_brier" in body
    assert "0.18" in body  # treatment value
    assert "SPRT terminal decision" in body
    assert "accept_h0" in body
    assert "Rollback-history window" in body
    assert "0.018" in body
    assert ISSUE_LABEL in body


def test_body_includes_workflow_url_and_report_path() -> None:
    body = render_body(
        _report(),
        date="2026-04-21",
        workflow_run_url="https://github.com/x/y/actions/runs/123",
        report_path="artifacts/reports/f2_promotion_gate_2026-04-21.json",
    )
    assert "actions/runs/123" in body
    assert "f2_promotion_gate_2026-04-21.json" in body


def test_body_runbook_mentions_rotate_helper() -> None:
    body = render_body(_report())
    # The runbook MUST point operators at the reset helper, otherwise the
    # next day's gate re-fires on stale history.
    assert "f2_rotate_rollback_history.py" in body


def test_body_omits_optional_sections_when_missing() -> None:
    minimal = {"decision": "rollback"}
    body = render_body(minimal)
    assert "rollback" in body
    assert "SPRT terminal decision" not in body
    assert "Rollback-history window" not in body
    assert "KPI deltas" not in body


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cli_writes_title_and_body_files(tmp_path: Path) -> None:
    report_path = tmp_path / "r.json"
    _write(report_path, _report())
    title_path = tmp_path / "title.txt"
    body_path = tmp_path / "body.md"
    rc = main([
        "--report", str(report_path),
        "--date", "2026-04-21",
        "--title-out", str(title_path),
        "--body-out", str(body_path),
    ])
    assert rc == 0
    title = title_path.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")
    assert "2026-04-21" in title
    assert "calibrated_brier" in body


def test_cli_stdout_default(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "r.json"
    _write(report_path, _report())
    rc = main(["--report", str(report_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert TITLE_PREFIX in out
    assert "KPI deltas" in out


def test_cli_returns_1_on_missing_report(tmp_path: Path) -> None:
    rc = main(["--report", str(tmp_path / "nope.json")])
    assert rc == 1


def test_cli_returns_1_on_malformed_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json}", encoding="utf-8")
    rc = main(["--report", str(bad)])
    assert rc == 1

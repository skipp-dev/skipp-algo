"""Tests for scripts/f2_runbook.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_runbook import build_runbook, main, render_markdown


def _seed(tmp_path: Path) -> dict[str, Path]:
    artifact = tmp_path / "treatment.json"
    artifact.write_text(json.dumps({"status": "production"}), encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "schema_version": 1,
        "arms": {"treatment": {"calibration_artifact": str(artifact)}},
    }), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    for date, decision in [
        ("2026-04-18", "hold"),
        ("2026-04-19", "hold"),
        ("2026-04-20", "rollback"),
    ]:
        (reports / f"f2_promotion_gate_{date}.json").write_text(json.dumps({
            "schema_version": 1,
            "decision": decision,
            "reason": f"day={date}",
            "sprt": {"decision": "continue", "n": 50, "k": 20},
            "kpi_metrics": [{"metric": "calibrated_brier", "delta": 0.01}],
        }), encoding="utf-8")
    revert_j = tmp_path / "revert.jsonl"
    revert_j.write_text(json.dumps({
        "action": "reverted", "timestamp": "2026-04-20T10-00-00Z"
    }) + "\n", encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text(json.dumps([
        {"date": "2026-04-18", "decision": "hold", "reason": "green"},
        {"date": "2026-04-19", "decision": "hold", "reason": "green"},
    ]), encoding="utf-8")
    return {
        "spec": spec, "revert": revert_j, "reports": reports, "history": history,
    }


def test_build_runbook_aggregates_all_three_sections(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    rb = build_runbook(
        spec_path=paths["spec"],
        revert_journal=paths["revert"],
        reports_dir=paths["reports"],
        history_path=paths["history"],
    )
    assert rb["schema_version"] == 1
    assert rb["status"]["artifact"]["status"] == "production"
    assert rb["weekly_digest"]["len"] == 3
    assert len(rb["recent_ring"]) == 2


def test_ring_tail_respected(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    rb = build_runbook(
        spec_path=paths["spec"],
        revert_journal=paths["revert"],
        reports_dir=paths["reports"],
        history_path=paths["history"],
        ring_tail=1,
    )
    assert len(rb["recent_ring"]) == 1
    assert rb["recent_ring"][0]["date"] == "2026-04-19"


def test_missing_history_yields_empty_ring(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    rb = build_runbook(
        spec_path=paths["spec"],
        revert_journal=paths["revert"],
        reports_dir=paths["reports"],
        history_path=tmp_path / "absent.json",
    )
    assert rb["recent_ring"] == []


def test_invalid_args_rejected(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    with pytest.raises(ValueError):
        build_runbook(
            spec_path=paths["spec"], revert_journal=paths["revert"],
            reports_dir=paths["reports"], history_path=paths["history"],
            window_days=0,
        )
    with pytest.raises(ValueError):
        build_runbook(
            spec_path=paths["spec"], revert_journal=paths["revert"],
            reports_dir=paths["reports"], history_path=paths["history"],
            ring_tail=-1,
        )


def test_render_markdown_contains_all_sections(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    rb = build_runbook(
        spec_path=paths["spec"], revert_journal=paths["revert"],
        reports_dir=paths["reports"], history_path=paths["history"],
    )
    md = render_markdown(rb)
    assert "# F2 Operator Runbook" in md
    assert "## Status" in md
    assert "## Weekly digest" in md
    assert "## Recent ring" in md
    assert "production" in md
    assert "| date | decision |" in md


def test_render_markdown_empty_ring(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    rb = build_runbook(
        spec_path=paths["spec"], revert_journal=paths["revert"],
        reports_dir=paths["reports"], history_path=tmp_path / "absent.json",
    )
    md = render_markdown(rb)
    assert "_(empty)_" in md


def test_cli_default_prints_md_and_writes_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed(tmp_path)
    out = tmp_path / "rb.json"
    rc = main([
        "--spec", str(paths["spec"]),
        "--revert-journal", str(paths["revert"]),
        "--reports-dir", str(paths["reports"]),
        "--history", str(paths["history"]),
        "--output", str(out),
    ])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert "# F2 Operator Runbook" in stdout
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1


def test_cli_json_format_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed(tmp_path)
    rc = main([
        "--spec", str(paths["spec"]),
        "--revert-journal", str(paths["revert"]),
        "--reports-dir", str(paths["reports"]),
        "--history", str(paths["history"]),
        "--format", "json",
    ])
    assert rc == 0
    stdout = capsys.readouterr().out
    parsed = json.loads(stdout)
    assert parsed["schema_version"] == 1


def test_cli_quiet_no_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed(tmp_path)
    out = tmp_path / "rb.json"
    rc = main([
        "--spec", str(paths["spec"]),
        "--revert-journal", str(paths["revert"]),
        "--reports-dir", str(paths["reports"]),
        "--history", str(paths["history"]),
        "--output", str(out),
        "--quiet",
    ])
    assert rc == 0
    assert capsys.readouterr().out == ""
    assert out.exists()


def test_long_reason_truncated_in_markdown(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    paths["history"].write_text(json.dumps([
        {"date": "2026-04-19", "decision": "hold", "reason": "x" * 200},
    ]), encoding="utf-8")
    rb = build_runbook(
        spec_path=paths["spec"], revert_journal=paths["revert"],
        reports_dir=paths["reports"], history_path=paths["history"],
    )
    md = render_markdown(rb)
    assert "..." in md
    # Full 200-char blob not present.
    assert "x" * 200 not in md

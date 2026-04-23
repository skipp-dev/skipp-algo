"""Tests for scripts/f2_inspect_status.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_inspect_status import (
    build_status,
    main,
    render_markdown,
    render_one_line,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _spec(tmp: Path, artifact: Path | None) -> Path:
    p = tmp / "spec.json"
    arms = {"treatment": {}}
    if artifact is not None:
        arms["treatment"]["calibration_artifact"] = str(artifact)
    _write(p, {"name": "f2-test", "arms": arms})
    return p


def _journal(path: Path, entries: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Artifact status
# ---------------------------------------------------------------------------


def test_status_reports_production_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "production", "weights": {}})
    status = build_status(spec_path=_spec(tmp_path, artifact))
    assert status["artifact"]["status"] == "production"
    assert status["artifact"]["exists"] is True
    assert status["artifact"]["revert_history_len"] == 0
    assert status["artifact"]["promote_history_len"] == 0


def test_status_reports_shadow_with_revert_history(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {
        "status": "shadow",
        "revert_history": [{"reverted_at_utc": "T1"}, {"reverted_at_utc": "T2"}],
    })
    status = build_status(spec_path=_spec(tmp_path, artifact))
    assert status["artifact"]["status"] == "shadow"
    assert status["artifact"]["revert_history_len"] == 2
    assert status["artifact"]["last_revert"]["reverted_at_utc"] == "T2"


def test_status_handles_missing_artifact(tmp_path: Path) -> None:
    status = build_status(spec_path=_spec(tmp_path, tmp_path / "missing.json"))
    assert status["artifact"]["exists"] is False
    assert status["artifact"]["status"] is None


def test_status_handles_no_artifact_field_in_spec(tmp_path: Path) -> None:
    status = build_status(spec_path=_spec(tmp_path, None))
    assert status["artifact"]["path"] is None
    assert status["artifact"]["exists"] is False


def test_status_handles_corrupt_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    artifact.write_text("not-json", encoding="utf-8")
    status = build_status(spec_path=_spec(tmp_path, artifact))
    assert status["artifact"]["exists"] is True
    assert status["artifact"]["status"] is None
    assert "error" in status["artifact"]


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------


def test_status_summarizes_revert_journal(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "shadow"})
    rj = _journal(tmp_path / "rj.jsonl", [
        {"action": "reverted", "timestamp_utc": "T1"},
        {"action": "noop_already_shadow", "timestamp_utc": "T2"},
        {"action": "reverted", "timestamp_utc": "T3"},
    ])
    status = build_status(spec_path=_spec(tmp_path, artifact), revert_journal=rj)
    assert status["revert_journal"]["len"] == 3
    assert status["revert_journal"]["actions"] == {
        "reverted": 2, "noop_already_shadow": 1,
    }


def test_status_summarizes_promote_journal(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    pj = _journal(tmp_path / "pj.jsonl", [
        {"action": "promoted", "timestamp_utc": "T1"},
    ])
    status = build_status(spec_path=_spec(tmp_path, artifact), promote_journal=pj)
    assert status["promote_journal"]["len"] == 1
    assert status["promote_journal"]["actions"] == {"promoted": 1}


def test_status_journals_default_to_empty_when_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    status = build_status(spec_path=_spec(tmp_path, artifact))
    assert status["revert_journal"]["len"] == 0
    assert status["promote_journal"]["len"] == 0


def test_status_journal_tail_is_bounded(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "shadow"})
    rj = _journal(tmp_path / "rj.jsonl", [
        {"action": "reverted", "timestamp_utc": f"T{i}"} for i in range(20)
    ])
    status = build_status(spec_path=_spec(tmp_path, artifact),
                          revert_journal=rj, tail_n=3)
    assert status["revert_journal"]["len"] == 3  # tail window
    assert [e["timestamp_utc"] for e in status["revert_journal"]["tail"]] \
        == ["T17", "T18", "T19"]


def test_status_tolerates_corrupt_journal_lines(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "shadow"})
    rj = tmp_path / "rj.jsonl"
    rj.write_text(
        json.dumps({"action": "reverted"}) + "\n"
        + "not-json\n"
        + json.dumps({"action": "noop_already_shadow"}) + "\n",
        encoding="utf-8",
    )
    status = build_status(spec_path=_spec(tmp_path, artifact), revert_journal=rj)
    # Bad lines silently skipped; good ones counted.
    assert status["revert_journal"]["len"] == 2


# ---------------------------------------------------------------------------
# Latest report
# ---------------------------------------------------------------------------


def test_status_picks_lexicographically_latest_report(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports / "f2_promotion_gate_2026-04-19.json",
           {"decision": "hold", "sprt": {"decision": "continue"}})
    _write(reports / "f2_promotion_gate_2026-04-21.json",
           {"decision": "promote", "sprt": {"decision": "accept_h1"}})
    _write(reports / "f2_promotion_gate_2026-04-20.json",
           {"decision": "hold", "sprt": {"decision": "continue"}})
    status = build_status(spec_path=_spec(tmp_path, artifact), reports_dir=reports)
    assert status["latest_report"]["date"] == "2026-04-21"
    assert status["latest_report"]["decision"] == "promote"
    assert status["latest_report"]["sprt"]["decision"] == "accept_h1"


def test_status_handles_empty_reports_dir(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    reports = tmp_path / "reports"
    reports.mkdir()
    status = build_status(spec_path=_spec(tmp_path, artifact), reports_dir=reports)
    assert status["latest_report"] is None


def test_status_handles_missing_reports_dir(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    status = build_status(spec_path=_spec(tmp_path, artifact),
                          reports_dir=tmp_path / "nope")
    assert status["latest_report"] is None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_build_status_raises_on_missing_spec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="spec does not exist"):
        build_status(spec_path=tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_output_file_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "shadow"})
    out = tmp_path / "status.json"
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["artifact"]["status"] == "shadow"
    assert data["schema_version"] == 1


def test_cli_missing_spec_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--spec", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "spec does not exist" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# One-line / --quiet
# ---------------------------------------------------------------------------


def test_render_one_line_full(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "shadow"})
    rj = _journal(tmp_path / "rj.jsonl",
                  [{"action": "reverted"}, {"action": "noop_already_shadow"}])
    pj = _journal(tmp_path / "pj.jsonl", [{"action": "promoted"}])
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports / "f2_promotion_gate_2026-04-21.json",
           {"decision": "rollback"})

    status = build_status(
        spec_path=_spec(tmp_path, artifact),
        revert_journal=rj, promote_journal=pj, reports_dir=reports,
    )
    line = render_one_line(status)
    assert line == (
        "f2[f2-test] spec_status=registered "
        "artifact=shadow revert=2 promote=1 latest=2026-04-21:rollback"
    )


def test_render_one_line_handles_missing_pieces() -> None:
    status = {
        "experiment": None,
        "artifact": {},
        "revert_journal": {},
        "promote_journal": {},
        "latest_report": None,
    }
    line = render_one_line(status)
    assert line == (
        "f2[?] spec_status=? artifact=missing revert=0 promote=0 latest=none"
    )


def test_cli_quiet_prints_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--quiet",
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    # Single line, no JSON braces.
    assert "\n" not in out
    assert out.startswith("f2[f2-test] spec_status=registered artifact=production")
    assert "{" not in out


def test_cli_quiet_still_writes_full_json_to_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    out = tmp_path / "status.json"
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--quiet",
        "--output", str(out),
    ])
    assert rc == 0
    # --output is the structured digest, --quiet only affects stdout.
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["artifact"]["status"] == "production"


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def test_render_markdown_full(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {
        "status": "shadow",
        "revert_history": [{"reverted_at_utc": "T1", "from_status": "production"}],
    })
    rj = _journal(tmp_path / "rj.jsonl",
                  [{"action": "reverted", "timestamp_utc": "T1"}])
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports / "f2_promotion_gate_2026-04-21.json",
           {"decision": "rollback",
            "sprt": {"decision": "accept_h0", "n": 100, "k": 55, "llr": 0.05}})
    status = build_status(
        spec_path=_spec(tmp_path, artifact),
        revert_journal=rj, reports_dir=reports,
    )
    md = render_markdown(status)
    # Section headers present.
    assert "# F2 contextual arm — `f2-test`" in md
    assert "## Artifact" in md
    assert "## Revert Journal" in md
    assert "## Promote Journal" in md
    assert "## Latest promotion-gate report" in md
    # Key facts present.
    assert "`shadow`" in md
    assert "1 entries" in md  # revert_history count
    assert "`reverted`=1" in md
    assert "`2026-04-21`" in md
    assert "`rollback`" in md
    assert "`accept_h0`" in md


def test_render_markdown_handles_no_reports(tmp_path: Path) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    md = render_markdown(build_status(spec_path=_spec(tmp_path, artifact)))
    assert "## Latest promotion-gate report" in md
    assert "_No reports found._" in md


def test_cli_format_md_emits_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "t.json"
    _write(artifact, {"status": "production"})
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--format", "md",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# F2 contextual arm" in out
    # Not the JSON form.
    assert '"schema_version"' not in out

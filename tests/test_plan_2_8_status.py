"""Tests for ``scripts/plan_2_8_status.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_status", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status"] = mod
    spec.loader.exec_module(mod)
    return mod


status_mod = _load()


def test_phases_cover_0_through_3() -> None:
    names = [p["name"] for p in status_mod.PHASES]
    assert any("Phase 0" in n for n in names)
    assert any("Phase 1" in n for n in names)
    assert any("Phase 2" in n for n in names)
    assert any("Phase 3" in n for n in names)


def test_evaluate_status_against_real_repo_passes() -> None:
    """All required anchors should exist in the live repo right now."""
    status = status_mod.evaluate_status(REPO)
    assert status["ok"], json.dumps(status, indent=2)
    for phase in status["phases"]:
        for anchor in phase["anchors"]:
            if anchor["kind"] == "required":
                assert anchor["status"] == "ok", anchor


def test_evaluate_status_marks_missing_required(tmp_path: Path) -> None:
    """Empty repo => everything required is missing => overall fails."""
    status = status_mod.evaluate_status(tmp_path)
    assert status["ok"] is False
    for phase in status["phases"]:
        for anchor in phase["anchors"]:
            if anchor["kind"] == "required":
                assert anchor["status"] == "missing"


def test_evaluate_status_marks_optional_missing_softly(tmp_path: Path) -> None:
    """Optional anchors are reported as 'optional-missing', not 'missing'."""
    status = status_mod.evaluate_status(tmp_path)
    optional_anchors = [
        a for phase in status["phases"] for a in phase["anchors"]
        if a["kind"] == "optional"
    ]
    assert optional_anchors, "expected at least one optional anchor"
    for a in optional_anchors:
        assert a["status"] == "optional-missing"


def test_render_markdown_has_per_phase_sections() -> None:
    status = status_mod.evaluate_status(REPO)
    md = status_mod.render_markdown(status)
    assert md.startswith("# Plan 2.8 phase status")
    for phase in status["phases"]:
        assert phase["name"] in md
    assert md.endswith("\n")


def test_cli_returns_zero_against_real_repo(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = status_mod.main(["--repo-root", str(REPO), "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_cli_returns_one_against_empty_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = status_mod.main(["--repo-root", str(tmp_path), "--format", "md"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "INCOMPLETE" in out


def test_cli_writes_output_file(tmp_path: Path) -> None:
    out_path = tmp_path / "out" / "status.json"
    rc = status_mod.main([
        "--repo-root", str(REPO),
        "--format", "json",
        "--output", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["ok"] is True

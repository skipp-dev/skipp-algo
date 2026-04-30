"""Tests for ``scripts/plan_2_8_runcard_from_status.py`` + batch #70 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runcard_from_status.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runcard_from_status", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runcard_from_status"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


STATUS = {
    "status": "amber",
    "score":  0.75,
    "signals": {
        "alerts":          2,
        "coverage_under":  1,
        "coverage_total":  10,
        "runcard_present": 5,
        "runcard_total":   8,
    },
}
RCIDX = {
    "counts": {"present": 5, "total": 8, "missing": 3},
    "sections": [
        {"section": "Weekly digest",  "filename": "weekly_digest.md",  "present": True},
        {"section": "Snapshot diff",  "filename": "snapshot_diff.md",  "present": False},
        {"section": "Top movers",     "filename": "top_movers.md",     "present": False},
    ],
}
HEALTH = {
    "status": "amber", "score": 0.75,
    "findings": ["2 drift alert(s) above threshold"],
}


def test_render_all_inputs_populated() -> None:
    md = rc.render(STATUS, RCIDX, HEALTH, run_url="https://e/run/1")
    assert "_status:_ **amber**" in md
    assert "score 0.75" in md
    assert "https://e/run/1" in md
    assert "2 drift alert" in md
    assert "Missing or empty:" in md


def test_render_all_missing_inputs() -> None:
    md = rc.render(None, None, None)
    assert "**unknown**" in md
    assert "n/a" in md
    assert "status_snapshot" in md
    assert "runcard_index" in md
    assert "health" in md


def test_render_all_sections_present_emits_friendly_line() -> None:
    clean = {
        "counts": {"present": 2, "total": 2},
        "sections": [
            {"section": "Weekly digest",  "filename": "weekly_digest.md",  "present": True},
            {"section": "Slice coverage", "filename": "coverage.md",       "present": True},
        ],
    }
    md = rc.render(STATUS, clean, HEALTH)
    assert "All expected sections are present." in md


def test_render_health_with_no_findings() -> None:
    md = rc.render(STATUS, RCIDX, {"status": "green", "score": 1.0,
                                   "findings": []})
    assert "_No findings._" in md


def test_render_status_falls_back_to_health_when_snapshot_missing() -> None:
    md = rc.render(None, RCIDX, HEALTH)
    assert "**amber**" in md


def test_render_score_from_status_snapshot_only() -> None:
    snap_only = {"status": "green", "score": 0.95,
                 "signals": {}}
    md = rc.render(snap_only, None, None)
    assert "score 0.95" in md


def _seed(d: Path, name: str, data: dict[str, Any]) -> Path:
    p = d / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_cli_writes_output(tmp_path: Path) -> None:
    s = _seed(tmp_path, "status_snapshot.json", STATUS)
    r = _seed(tmp_path, "runcard_index.json", RCIDX)
    h = _seed(tmp_path, "health.json", HEALTH)
    out = tmp_path / "status_runcard.md"
    rc_code = rc.main([
        "--status-snapshot", str(s),
        "--runcard-index",   str(r),
        "--health",          str(h),
        "--output",          str(out),
        "--run-url",         "https://example/run/42",
    ])
    assert rc_code == 0
    text = out.read_text(encoding="utf-8")
    assert "**amber**" in text
    assert "https://example/run/42" in text


def test_cli_tolerates_all_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc_code = rc.main([])
    assert rc_code == 0
    out = capsys.readouterr().out
    assert "**unknown**" in out


def test_cli_ignores_malformed_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    rc_code = rc.main([
        "--status-snapshot", str(bad),
    ])
    assert rc_code == 0


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_archive_compare_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest archive + weekly compare" in names
    assert "Upload Plan 2.8 digest archive" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest archive + weekly compare")
    assert "plan_2_8_digest_archive.py" in step["run"]
    assert "plan_2_8_digest_compare.py" in step["run"]


def test_weekly_downloads_prior_digest_archive() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Download Plan 2.8 digest archive" in names
    step = next(s for s in steps
                if s.get("name") == "Download Plan 2.8 digest archive")
    assert step["uses"].startswith("dawidd6/action-download-artifact@")
    assert step["with"]["name"] == "plan-2-8-digest-archive"
    assert step["with"]["name_is_regexp"] is True

"""Tests for ``scripts/plan_2_8_runcard_index.py`` + health step wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runcard_index.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runcard_index", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runcard_index"] = mod
    spec.loader.exec_module(mod)
    return mod


idx = _load()


def _seed(d: Path, files: dict[str, str]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for n, body in files.items():
        (d / n).write_text(body, encoding="utf-8")


def test_index_empty_dir(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rep = idx.index(tmp_path)
    assert rep["counts"]["present"] == 0
    assert rep["counts"]["missing"] == rep["counts"]["total"]


def test_index_partial(tmp_path: Path) -> None:
    _seed(tmp_path, {
        "coverage.md":  "# body",
        "stability.md": "# body",
    })
    rep = idx.index(tmp_path)
    assert rep["counts"]["present"] == 2
    files = {r["filename"]: r for r in rep["sections"]}
    assert files["coverage.md"]["present"] is True
    assert files["stability.md"]["present"] is True
    assert files["weekly_digest.md"]["present"] is False


def test_index_empty_file_counts_missing(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": ""})
    rep = idx.index(tmp_path)
    files = {r["filename"]: r for r in rep["sections"]}
    assert files["coverage.md"]["exists"] is True
    assert files["coverage.md"]["present"] is False


def test_index_section_map_matches_runcard(tmp_path: Path) -> None:
    rcard_mod_path = REPO / "scripts" / "plan_2_8_weekly_runcard.py"
    spec = importlib.util.spec_from_file_location("_rc", rcard_mod_path)
    assert spec and spec.loader
    rc = importlib.util.module_from_spec(spec)
    sys.modules["_rc"] = rc
    spec.loader.exec_module(rc)
    assert idx.SECTION_MAP == rc.SECTION_MAP


def test_render_markdown_table(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "x"})
    md = idx.render_markdown(idx.index(tmp_path))
    assert "# Plan 2.8 runcard index" in md
    assert "| section | file | status |" in md
    assert "coverage.md" in md


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    art = tmp_path / "art"
    _seed(art, {"coverage.md": "x", "stability.md": "y"})
    rc = idx.main([
        "--artifact-dir", str(art), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["present"] == 2


def test_cli_output_md(tmp_path: Path) -> None:
    art = tmp_path / "art"
    _seed(art, {"coverage.md": "x"})
    out = tmp_path / "i.md"
    rc = idx.main([
        "--artifact-dir", str(art), "--format", "md", "--output", str(out),
    ])
    assert rc == 0
    assert "coverage.md" in out.read_text(encoding="utf-8")


def test_cli_fail_on_min_present(tmp_path: Path) -> None:
    art = tmp_path / "art"
    _seed(art, {"coverage.md": "x"})  # only 1 present
    rc = idx.main([
        "--artifact-dir", str(art), "--min-present", "5",
    ])
    assert rc == 1


def test_cli_missing_artifact_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = idx.main([
        "--artifact-dir", str(tmp_path / "nope"),
    ])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


# --------- workflow health-step pin tests ---------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_rollout_health_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 rollout health" in names
    step = next(s for s in steps if s.get("name") == "Plan 2.8 rollout health")
    run = step["run"]
    assert "plan_2_8_health.py" in run
    assert "health.json" in run
    assert "health.md" in run


def test_weekly_coverage_step_emits_json() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    step = next(s for s in steps if s.get("name") == "Plan 2.8 slice coverage")
    assert "coverage.json" in step["run"]
    assert "--format     json" in step["run"]


def test_weekly_stability_step_emits_json() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 slice stability (last 8 snapshots)")
    assert "stability.json" in step["run"]

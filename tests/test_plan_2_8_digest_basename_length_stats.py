"""Tests for ``scripts/plan_2_8_digest_basename_length_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_basename_length_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_basename_length_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_basename_length_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


bl = _load()


def test_empty(tmp_path: Path) -> None:
    rep = bl.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["min_length"] == 0
    assert rep["max_length"] == 0
    assert rep["mean_length"] == 0.0


def test_basic(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")  # 5
    (tmp_path / "bb.txt").write_text("x", encoding="utf-8")  # 6
    rep = bl.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["min_length"] == 5
    assert rep["max_length"] == 6
    assert rep["mean_length"] == 5.5


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "ignored.txt").write_text("x", encoding="utf-8")
    rep = bl.build(tmp_path)
    assert rep["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    md = bl.render_markdown(bl.build(tmp_path))
    assert "mean_length" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "abc.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = bl.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["file_count"] == 1
    assert data["min_length"] == 7


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = bl.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_basename_length_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest basename length stats" in names
    assert "Upload Plan 2.8 digest basename length stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest basename length stats")
    assert "plan_2_8_digest_basename_length_stats.py" in step["run"]

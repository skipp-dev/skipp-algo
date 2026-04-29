"""Tests for ``scripts/plan_2_8_weekly_summary_mean_line_length.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_mean_line_length.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_mean_line_length", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_mean_line_length"] = mod
    spec.loader.exec_module(mod)
    return mod


ml = _load()


def test_missing(tmp_path: Path) -> None:
    rep = ml.compute(tmp_path / "nope.md")
    assert rep["mean_line_length"] == 0.0
    assert rep["line_count"] == 0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("")
    assert ml.compute(p)["line_count"] == 0


def test_mean(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("ab\ncde\nfghi\n")
    rep = ml.compute(p)
    assert rep["line_count"] == 3
    assert rep["mean_line_length"] == 3.0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("x\n")
    assert "mean_line_length" in ml.render_markdown(ml.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("ab\n")
    out = tmp_path / "o.json"
    code = ml.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["mean_line_length"] == 2.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = ml.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_mean_line_length_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary mean line length" in names
    assert "Upload Plan 2.8 weekly summary mean line length" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary mean line length")
    assert "plan_2_8_weekly_summary_mean_line_length.py" in step["run"]

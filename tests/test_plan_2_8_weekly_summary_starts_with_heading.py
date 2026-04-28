"""Tests for ``scripts/plan_2_8_weekly_summary_starts_with_heading.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / \
    "plan_2_8_weekly_summary_starts_with_heading.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_starts_with_heading", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_starts_with_heading"] = mod
    spec.loader.exec_module(mod)
    return mod


sh = _load()


def test_missing(tmp_path: Path) -> None:
    assert sh.compute(tmp_path / "nope.md")["starts_with_heading"] is False


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("")
    assert sh.compute(p)["starts_with_heading"] is False


def test_heading(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("\n\n# Title\nbody\n")
    assert sh.compute(p)["starts_with_heading"] is True


def test_no_heading(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("body text\n")
    assert sh.compute(p)["starts_with_heading"] is False


def test_h2_not_h1(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("## Two\n")
    assert sh.compute(p)["starts_with_heading"] is False


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# x\n")
    assert "starts_with_heading" in sh.render_markdown(sh.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# x\n")
    out = tmp_path / "o.json"
    code = sh.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["starts_with_heading"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = sh.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_starts_heading_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary starts with heading" in names
    assert "Upload Plan 2.8 weekly summary starts with heading" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary starts with heading")
    assert "plan_2_8_weekly_summary_starts_with_heading.py" in step["run"]

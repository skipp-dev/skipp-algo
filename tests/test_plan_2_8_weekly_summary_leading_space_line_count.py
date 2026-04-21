"""Tests for ``plan_2_8_weekly_summary_leading_space_line_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO / "scripts"
    / "plan_2_8_weekly_summary_leading_space_line_count.py"
)
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_leading_space_line_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[
        "plan_2_8_weekly_summary_leading_space_line_count"] = mod
    spec.loader.exec_module(mod)
    return mod


ls = _load()


def test_missing(tmp_path: Path) -> None:
    assert ls.compute(
        tmp_path / "nope.md")["leading_space_line_count"] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    # lines: ' a', 'b', '  c', '\td'
    # leading space: ' a', '  c' = 2 (tab doesn't count)
    p.write_text(" a\nb\n  c\n\td", encoding="utf-8")
    assert ls.compute(p)["leading_space_line_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a")
    assert "leading_space_line_count" in ls.render_markdown(ls.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(" a\nb\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = ls.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["leading_space_line_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = ls.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_ls_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary leading space line count" in names
    assert (
        "Upload Plan 2.8 weekly summary leading space line count"
        in names
    )
    step = next(
        s for s in steps
        if s.get("name")
        == "Plan 2.8 weekly summary leading space line count"
    )
    assert (
        "plan_2_8_weekly_summary_leading_space_line_count.py"
        in step["run"]
    )

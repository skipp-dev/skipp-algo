"""Tests for ``scripts/plan_2_8_weekly_summary_bold_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_bold_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_bold_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_bold_count"] = mod
    spec.loader.exec_module(mod)
    return mod


bc = _load()


def test_missing(tmp_path: Path) -> None:
    assert bc.compute(tmp_path / "nope.md")["total"] == 0


def test_none(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("plain\n", encoding="utf-8")
    assert bc.compute(p)["total"] == 0


def test_counts_both(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**a** and __b__ also **c**\n", encoding="utf-8")
    rep = bc.compute(p)
    assert rep["star_count"] == 2
    assert rep["underscore_count"] == 1
    assert rep["total"] == 3


def test_empty_markers_ignored(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**** __ __\n", encoding="utf-8")
    assert bc.compute(p)["total"] == 0


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("```\n**ignored**\n```\n**counted**\n", encoding="utf-8")
    assert bc.compute(p)["total"] == 1


def test_inline_code_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("`**not**` and **yes**\n", encoding="utf-8")
    assert bc.compute(p)["total"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**a**\n", encoding="utf-8")
    md = bc.render_markdown(bc.compute(p))
    assert "star_count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**a**\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = bc.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = bc.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_bold_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary bold count" in names
    assert "Upload Plan 2.8 weekly summary bold count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary bold count")
    assert "plan_2_8_weekly_summary_bold_count.py" in step["run"]

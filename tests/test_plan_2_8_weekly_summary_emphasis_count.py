"""Tests for ``scripts/plan_2_8_weekly_summary_emphasis_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_emphasis_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_emphasis_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_emphasis_count"] = mod
    spec.loader.exec_module(mod)
    return mod


ec = _load()


def test_empty_missing(tmp_path: Path) -> None:
    rep = ec.compute(tmp_path / "nope.md")
    assert rep == {"schema_version": 1, "bold_count": 0, "italic_count": 0}


def test_bold_and_italic(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**hi** and *italic* and _under_\n", encoding="utf-8")
    rep = ec.compute(p)
    assert rep["bold_count"] == 1
    assert rep["italic_count"] == 2


def test_bold_does_not_double_count_italic(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**boldonly**\n", encoding="utf-8")
    rep = ec.compute(p)
    assert rep["bold_count"] == 1
    assert rep["italic_count"] == 0


def test_fenced_code_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n**ignore** *me*\n```\n**real**\n",
        encoding="utf-8",
    )
    rep = ec.compute(p)
    assert rep["bold_count"] == 1
    assert rep["italic_count"] == 0


def test_empty_spans_not_counted(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("****\n", encoding="utf-8")
    rep = ec.compute(p)
    assert rep["bold_count"] == 0
    assert rep["italic_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**x**\n", encoding="utf-8")
    md = ec.render_markdown(ec.compute(p))
    assert "emphasis count" in md
    assert "bold_count: 1" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("**x** *y*\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ec.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["bold_count"] == 1
    assert data["italic_count"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ec.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_emphasis_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary emphasis count" in names
    assert "Upload Plan 2.8 weekly summary emphasis count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary emphasis count")
    assert "plan_2_8_weekly_summary_emphasis_count.py" in step["run"]

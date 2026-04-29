"""Tests for ``scripts/plan_2_8_weekly_summary_paragraph_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_paragraph_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_paragraph_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_paragraph_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


ps = _load()


def test_missing(tmp_path: Path) -> None:
    rep = ps.compute(tmp_path / "nope.md")
    assert rep["paragraph_count"] == 0
    assert rep["avg_lines_per_paragraph"] == 0.0


def test_single_paragraph(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    rep = ps.compute(p)
    assert rep["paragraph_count"] == 1
    assert rep["avg_lines_per_paragraph"] == 3.0


def test_multi_paragraphs(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n\nb\nc\n\nd\n", encoding="utf-8")
    rep = ps.compute(p)
    assert rep["paragraph_count"] == 3
    assert rep["avg_lines_per_paragraph"] == round(4 / 3, 2)


def test_fence_marker_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n\n```\nb\n```\n\nc\n", encoding="utf-8")
    rep = ps.compute(p)
    # paragraphs: [a], [b], [c] => 3 paragraphs of 1 line each
    assert rep["paragraph_count"] == 3


def test_trailing_paragraph_eof(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a", encoding="utf-8")
    rep = ps.compute(p)
    assert rep["paragraph_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n", encoding="utf-8")
    md = ps.render_markdown(ps.compute(p))
    assert "paragraph stats" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n\nb\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ps.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["paragraph_count"] == 2


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ps.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_paragraph_stats_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary paragraph stats" in names
    assert "Upload Plan 2.8 weekly summary paragraph stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary paragraph stats")
    assert "plan_2_8_weekly_summary_paragraph_stats.py" in step["run"]

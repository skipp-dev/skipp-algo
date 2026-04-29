"""Tests for ``scripts/plan_2_8_weekly_summary_heading_hierarchy.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_heading_hierarchy.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_heading_hierarchy", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_heading_hierarchy"] = mod
    spec.loader.exec_module(mod)
    return mod


hh = _load()


def test_missing(tmp_path: Path) -> None:
    rep = hh.compute(tmp_path / "nope.md")
    assert rep["total"] == 0
    assert rep["deepest_level"] == 0
    assert rep["counts"]["h1"] == 0


def test_mixed_levels(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "# A\n## B\n## C\n### D\ntext\n", encoding="utf-8",
    )
    rep = hh.compute(p)
    assert rep["total"] == 4
    assert rep["deepest_level"] == 3
    assert rep["counts"]["h1"] == 1
    assert rep["counts"]["h2"] == 2
    assert rep["counts"]["h3"] == 1


def test_fenced_code_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n# ignore\n```\n# real\n", encoding="utf-8",
    )
    rep = hh.compute(p)
    assert rep["total"] == 1


def test_requires_space_and_content(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("#nospace\n#\n", encoding="utf-8")
    rep = hh.compute(p)
    assert rep["total"] == 0


def test_seven_hashes_not_heading(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("####### too many\n", encoding="utf-8")
    rep = hh.compute(p)
    assert rep["total"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# a\n## b\n", encoding="utf-8")
    md = hh.render_markdown(hh.compute(p))
    assert "heading hierarchy" in md
    assert "h1: 1" in md
    assert "h2: 1" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# a\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = hh.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 1
    assert data["counts"]["h1"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hh.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_heading_hierarchy_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary heading hierarchy" in names
    assert "Upload Plan 2.8 weekly summary heading hierarchy" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary heading hierarchy")
    assert "plan_2_8_weekly_summary_heading_hierarchy.py" in step["run"]

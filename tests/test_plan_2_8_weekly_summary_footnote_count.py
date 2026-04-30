"""Tests for ``scripts/plan_2_8_weekly_summary_footnote_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_footnote_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_footnote_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_footnote_count"] = mod
    spec.loader.exec_module(mod)
    return mod


fc = _load()


def test_missing(tmp_path: Path) -> None:
    rep = fc.compute(tmp_path / "nope.md")
    assert rep["total"] == 0


def test_none(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("plain paragraph\n", encoding="utf-8")
    assert fc.compute(p)["total"] == 0


def test_counts_refs_and_defs(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "see [^a] and [^b]\n\n[^a]: def\n[^b]: def\n",
        encoding="utf-8",
    )
    rep = fc.compute(p)
    assert rep["reference_count"] == 2
    assert rep["definition_count"] == 2
    assert rep["total"] == 4


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\nsee [^ignored]\n```\n\n[^a]: def\n",
        encoding="utf-8",
    )
    rep = fc.compute(p)
    assert rep["reference_count"] == 0
    assert rep["definition_count"] == 1


def test_definition_not_double_counted(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[^x]: y\n", encoding="utf-8")
    rep = fc.compute(p)
    assert rep["definition_count"] == 1
    assert rep["reference_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("see [^a]\n[^a]: def\n", encoding="utf-8")
    md = fc.render_markdown(fc.compute(p))
    assert "reference_count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("see [^a]\n[^a]: d\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = fc.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total"] == 2


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fc.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_footnote_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary footnote count" in names
    assert "Upload Plan 2.8 weekly summary footnote count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary footnote count")
    assert "plan_2_8_weekly_summary_footnote_count.py" in step["run"]

"""Tests for ``scripts/plan_2_8_weekly_summary_section_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_section_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_section_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_section_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


ss = _load()


def test_empty_text_no_sections() -> None:
    rep = ss.compute("")
    assert rep["section_count"] == 0
    assert rep["empty_sections"] == []


def test_single_section_counts_words() -> None:
    rep = ss.compute("## A\n\nhello world\n")
    assert rep["section_count"] == 1
    assert rep["sections"][0]["words"] == 2
    assert rep["sections"][0]["lines"] == 1


def test_multiple_sections() -> None:
    rep = ss.compute("## A\nfoo\n## B\nbar baz\n")
    assert rep["section_count"] == 2
    assert rep["sections"][1]["words"] == 2


def test_empty_section_flagged() -> None:
    rep = ss.compute("## A\n\n## B\nhi\n")
    assert rep["empty_sections"] == ["A"]


def test_h1_not_a_section() -> None:
    rep = ss.compute("# Title\nbody\n## S\nx\n")
    assert rep["section_count"] == 1
    assert rep["sections"][0]["heading"] == "S"


def test_content_before_first_h2_ignored() -> None:
    rep = ss.compute("intro words\n## A\nhi\n")
    assert rep["sections"][0]["words"] == 1


def test_markdown_shape() -> None:
    md = ss.render_markdown(ss.compute("## A\nhi there\n"))
    assert "section stats" in md
    assert "A" in md


def test_markdown_empty_placeholder() -> None:
    md = ss.render_markdown(ss.compute(""))
    assert "_no sections_" in md


def test_cli_fail_on_empty(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## A\n\n## B\nhi\n", encoding="utf-8")
    rc = ss.main([
        "--input", str(p), "--fail-on-empty",
    ])
    assert rc == 1


def test_cli_fail_on_empty_clean(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## A\nhi\n", encoding="utf-8")
    rc = ss.main([
        "--input", str(p), "--fail-on-empty",
    ])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## A\nhi\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ss.main([
        "--input", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["section_count"] == 1


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ss.main(["--input", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_section_stats_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary section stats" in names
    assert "Upload Plan 2.8 weekly summary section stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary section stats")
    assert "plan_2_8_weekly_summary_section_stats.py" in step["run"]

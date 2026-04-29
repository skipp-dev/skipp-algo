"""Tests for ``scripts/plan_2_8_weekly_summary_tables_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_tables_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_tables_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_tables_count"] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = tc.compute(p)
    assert rep["table_count"] == 0


def test_single_table(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "| a | b |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    rep = tc.compute(p)
    assert rep["table_count"] == 1
    assert rep["row_count"] == 3


def test_two_tables_separated(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "| a | b |\n|---|---|\n\nbetween\n\n| c | d |\n|---|---|\n",
        encoding="utf-8",
    )
    rep = tc.compute(p)
    assert rep["table_count"] == 2


def test_single_pipe_line_not_table(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| lonely |\n\nend\n", encoding="utf-8")
    rep = tc.compute(p)
    assert rep["table_count"] == 0


def test_code_block_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n| fake |\n| row |\n```\n| real |\n| row |\n",
        encoding="utf-8",
    )
    rep = tc.compute(p)
    assert rep["table_count"] == 1


def test_table_at_eof(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a |\n| b |", encoding="utf-8")
    rep = tc.compute(p)
    assert rep["table_count"] == 1


def test_missing_file() -> None:
    rep = tc.compute(Path("nope.md"))
    assert rep["table_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a |\n| b |\n", encoding="utf-8")
    md = tc.render_markdown(tc.compute(p))
    assert "tables count" in md
    assert "table_count: 1" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("text\n", encoding="utf-8")
    rc = tc.main(["--summary", str(p), "--fail-below-tables", "1"])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a |\n| b |\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = tc.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["table_count"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = tc.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_tables_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary tables count" in names
    assert "Upload Plan 2.8 weekly summary tables count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary tables count")
    assert "plan_2_8_weekly_summary_tables_count.py" in step["run"]

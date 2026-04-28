"""Tests for ``scripts/plan_2_8_weekly_summary_table_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_table_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_table_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_table_count"] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load()


def test_missing(tmp_path: Path) -> None:
    rep = tc.compute(tmp_path / "nope.md")
    assert rep["table_count"] == 0


def test_single_table(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n", encoding="utf-8",
    )
    assert tc.compute(p)["table_count"] == 1


def test_multiple_tables(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
        "\n"
        "| c | d |\n| --- | --- |\n| 3 | 4 |\n",
        encoding="utf-8",
    )
    assert tc.compute(p)["table_count"] == 2


def test_no_separator_no_match(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a | b |\n| 1 | 2 |\n", encoding="utf-8")
    assert tc.compute(p)["table_count"] == 0


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n| a | b |\n| --- | --- |\n```\n"
        "| c | d |\n| --- | --- |\n",
        encoding="utf-8",
    )
    assert tc.compute(p)["table_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a | b |\n| --- | --- |\n", encoding="utf-8")
    md = tc.render_markdown(tc.compute(p))
    assert "table count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("| a | b |\n| --- | --- |\n", encoding="utf-8")
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


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_table_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary table count" in names
    assert "Upload Plan 2.8 weekly summary table count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary table count")
    assert "plan_2_8_weekly_summary_table_count.py" in step["run"]

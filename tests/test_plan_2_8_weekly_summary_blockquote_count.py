"""Tests for ``scripts/plan_2_8_weekly_summary_blockquote_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_blockquote_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_blockquote_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_blockquote_count"] = mod
    spec.loader.exec_module(mod)
    return mod


bq = _load()


def test_missing(tmp_path: Path) -> None:
    rep = bq.compute(tmp_path / "nope.md")
    assert rep["blockquote_lines"] == 0
    assert rep["blockquote_blocks"] == 0


def test_single_block(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("> a\n> b\n> c\n", encoding="utf-8")
    rep = bq.compute(p)
    assert rep["blockquote_lines"] == 3
    assert rep["blockquote_blocks"] == 1


def test_two_blocks_separated(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("> a\n\nsome text\n\n> b\n", encoding="utf-8")
    rep = bq.compute(p)
    assert rep["blockquote_lines"] == 2
    assert rep["blockquote_blocks"] == 2


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n> fake\n```\n> real\n", encoding="utf-8",
    )
    rep = bq.compute(p)
    assert rep["blockquote_lines"] == 1
    assert rep["blockquote_blocks"] == 1


def test_leading_spaces_ok(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("   > indented\n", encoding="utf-8")
    rep = bq.compute(p)
    assert rep["blockquote_lines"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("> a\n", encoding="utf-8")
    md = bq.render_markdown(bq.compute(p))
    assert "blockquote count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("> a\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = bq.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["blockquote_lines"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = bq.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_blockquote_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary blockquote count" in names
    assert "Upload Plan 2.8 weekly summary blockquote count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary blockquote count")
    assert "plan_2_8_weekly_summary_blockquote_count.py" in step["run"]

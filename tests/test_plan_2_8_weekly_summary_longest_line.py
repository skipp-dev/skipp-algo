"""Tests for ``scripts/plan_2_8_weekly_summary_longest_line.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_longest_line.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_longest_line", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_longest_line"] = mod
    spec.loader.exec_module(mod)
    return mod


ll = _load()


def test_missing(tmp_path: Path) -> None:
    rep = ll.compute(tmp_path / "nope.md")
    assert rep["max_length"] == 0
    assert rep["line_number"] == 0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = ll.compute(p)
    assert rep["max_length"] == 0
    assert rep["line_count"] == 0


def test_finds_longest(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nbb\nccc\nbb\n", encoding="utf-8")
    rep = ll.compute(p)
    assert rep["max_length"] == 3
    assert rep["line_number"] == 3
    assert rep["line_count"] == 4


def test_first_wins_on_tie(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("abc\ndef\n", encoding="utf-8")
    assert ll.compute(p)["line_number"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hello\n", encoding="utf-8")
    md = ll.render_markdown(ll.compute(p))
    assert "max_length" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hi\nhello\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ll.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["max_length"] == 5


def test_cli_fail_above(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("xxxxxxxxxx\n", encoding="utf-8")
    rc = ll.main(["--summary", str(p), "--fail-above-length", "5"])
    assert rc == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ll.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_longest_line_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary longest line" in names
    assert "Upload Plan 2.8 weekly summary longest line" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary longest line")
    assert "plan_2_8_weekly_summary_longest_line.py" in step["run"]

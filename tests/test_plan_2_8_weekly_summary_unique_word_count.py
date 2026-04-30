"""Tests for ``scripts/plan_2_8_weekly_summary_unique_word_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_unique_word_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_unique_word_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_unique_word_count"] = mod
    spec.loader.exec_module(mod)
    return mod


uw = _load()


def test_missing(tmp_path: Path) -> None:
    assert uw.compute(tmp_path / "nope.md")["unique_word_count"] == 0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("")
    assert uw.compute(p)["unique_word_count"] == 0


def test_unique(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("foo bar Foo BAR baz\n")
    rep = uw.compute(p)
    assert rep["line_count"] == 1
    assert rep["unique_word_count"] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hi\n")
    assert "unique_word_count" in uw.render_markdown(uw.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a a b\n")
    out = tmp_path / "o.json"
    code = uw.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["unique_word_count"] == 2


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = uw.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_unique_word_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary unique word count" in names
    assert "Upload Plan 2.8 weekly summary unique word count" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary unique word count")
    assert "plan_2_8_weekly_summary_unique_word_count.py" in step["run"]

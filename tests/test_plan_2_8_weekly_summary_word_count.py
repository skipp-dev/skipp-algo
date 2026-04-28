"""Tests for ``scripts/plan_2_8_weekly_summary_word_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_word_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_word_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_word_count"] = mod
    spec.loader.exec_module(mod)
    return mod


wc = _load()


def test_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = wc.compute(p)
    assert rep["word_count"] == 0
    assert rep["char_count"] == 0
    assert rep["non_ws_char_count"] == 0


def test_basic_counts(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hello world\n", encoding="utf-8")
    rep = wc.compute(p)
    assert rep["word_count"] == 2
    assert rep["char_count"] == 12
    assert rep["non_ws_char_count"] == 10
    assert rep["line_count"] == 1


def test_multiple_lines(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    rep = wc.compute(p)
    assert rep["word_count"] == 3
    assert rep["line_count"] == 3


def test_whitespace_only(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("   \n\t\n", encoding="utf-8")
    rep = wc.compute(p)
    assert rep["word_count"] == 0
    assert rep["non_ws_char_count"] == 0


def test_missing_file_is_empty() -> None:
    rep = wc.compute(Path("nope.md"))
    assert rep["word_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hello\n", encoding="utf-8")
    md = wc.render_markdown(wc.compute(p))
    assert "word count" in md
    assert "word_count: 1" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("hi\n", encoding="utf-8")
    rc = wc.main(["--summary", str(p), "--fail-below-words", "10"])
    assert rc == 1


def test_cli_pass_above(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("one two three\n", encoding="utf-8")
    rc = wc.main(["--summary", str(p), "--fail-below-words", "2"])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a b c\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = wc.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["word_count"] == 3


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wc.main(["--summary", str(tmp_path / "nope.md")])
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


def test_weekly_has_word_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary word count" in names
    assert "Upload Plan 2.8 weekly summary word count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary word count")
    assert "plan_2_8_weekly_summary_word_count.py" in step["run"]

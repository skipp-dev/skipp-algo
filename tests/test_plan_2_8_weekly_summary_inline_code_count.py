"""Tests for ``scripts/plan_2_8_weekly_summary_inline_code_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_inline_code_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_inline_code_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_inline_code_count"] = mod
    spec.loader.exec_module(mod)
    return mod


ic = _load()


def test_missing(tmp_path: Path) -> None:
    rep = ic.compute(tmp_path / "nope.md")
    assert rep["inline_code_count"] == 0


def test_single_span(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("use `foo` here", encoding="utf-8")
    assert ic.compute(p)["inline_code_count"] == 1


def test_multiple_spans(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("`a` and `b` with `c`\n", encoding="utf-8")
    assert ic.compute(p)["inline_code_count"] == 3


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n`inside`\n```\n`outside`\n", encoding="utf-8",
    )
    assert ic.compute(p)["inline_code_count"] == 1


def test_empty_backticks_not_counted(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("empty `` here\n", encoding="utf-8")
    assert ic.compute(p)["inline_code_count"] == 0


def test_double_backtick_not_matched(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("``x``\n", encoding="utf-8")
    assert ic.compute(p)["inline_code_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("`x`\n", encoding="utf-8")
    md = ic.render_markdown(ic.compute(p))
    assert "inline-code count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("`x` `y`\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ic.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["inline_code_count"] == 2


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ic.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_inline_code_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary inline-code count" in names
    assert "Upload Plan 2.8 weekly summary inline-code count" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary inline-code count")
    assert "plan_2_8_weekly_summary_inline_code_count.py" in step["run"]

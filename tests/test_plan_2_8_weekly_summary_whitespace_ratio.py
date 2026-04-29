"""Tests for ``scripts/plan_2_8_weekly_summary_whitespace_ratio.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_whitespace_ratio.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_whitespace_ratio", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_whitespace_ratio"] = mod
    spec.loader.exec_module(mod)
    return mod


wr = _load()


def test_missing(tmp_path: Path) -> None:
    rep = wr.compute(tmp_path / "nope.md")
    assert rep["total_chars"] == 0
    assert rep["whitespace_chars"] == 0
    assert rep["ratio"] == 0.0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = wr.compute(p)
    assert rep["total_chars"] == 0
    assert rep["ratio"] == 0.0


def test_all_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("   \n\t\n", encoding="utf-8")
    rep = wr.compute(p)
    assert rep["ratio"] == 1.0


def test_mixed(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("ab  ", encoding="utf-8")  # 2 non-ws, 2 ws, total 4
    rep = wr.compute(p)
    assert rep["total_chars"] == 4
    assert rep["whitespace_chars"] == 2
    assert rep["ratio"] == 0.5


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a", encoding="utf-8")
    assert "ratio" in wr.render_markdown(wr.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("ab ", encoding="utf-8")
    out = tmp_path / "o.json"
    code = wr.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total_chars"] == 3


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = wr.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_whitespace_ratio_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary whitespace ratio" in names
    assert "Upload Plan 2.8 weekly summary whitespace ratio" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary whitespace ratio")
    assert "plan_2_8_weekly_summary_whitespace_ratio.py" in step["run"]

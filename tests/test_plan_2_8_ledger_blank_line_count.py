"""Tests for ``scripts/plan_2_8_ledger_blank_line_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_blank_line_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_blank_line_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_blank_line_count"] = mod
    spec.loader.exec_module(mod)
    return mod


bl = _load()


def test_missing(tmp_path: Path) -> None:
    rep = bl.compute(tmp_path / "nope.jsonl")
    assert rep["total_lines"] == 0
    assert rep["blank_line_count"] == 0


def test_count(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("{}\n\n   \n{}\n", encoding="utf-8")
    rep = bl.compute(p)
    assert rep["total_lines"] == 4
    assert rep["blank_line_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    assert "blank_line_count" in bl.render_markdown(
        bl.compute(tmp_path / "nope.jsonl"))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("{}\n\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = bl.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["blank_line_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = bl.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_blank_line_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger blank line count" in names
    assert "Upload Plan 2.8 ledger blank line count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger blank line count")
    assert "plan_2_8_ledger_blank_line_count.py" in step["run"]

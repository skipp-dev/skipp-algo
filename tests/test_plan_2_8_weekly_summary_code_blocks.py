"""Tests for ``scripts/plan_2_8_weekly_summary_code_blocks.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_code_blocks.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_code_blocks", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_code_blocks"] = mod
    spec.loader.exec_module(mod)
    return mod


cb = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = cb.compute(p)
    assert rep["block_count"] == 0
    assert rep["unbalanced"] is False


def test_one_block(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("text\n```\ncode\n```\nmore\n", encoding="utf-8")
    rep = cb.compute(p)
    assert rep["block_count"] == 1
    assert rep["unbalanced"] is False


def test_multiple_blocks(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```py\na\n```\n\n```\nb\n```\n",
        encoding="utf-8",
    )
    rep = cb.compute(p)
    assert rep["block_count"] == 2


def test_unbalanced_detected(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("```\ncode without close\n", encoding="utf-8")
    rep = cb.compute(p)
    assert rep["block_count"] == 0
    assert rep["unbalanced"] is True


def test_no_fences(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# heading\nno code\n", encoding="utf-8")
    rep = cb.compute(p)
    assert rep["block_count"] == 0


def test_missing_file() -> None:
    rep = cb.compute(Path("nope.md"))
    assert rep["block_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("```\na\n```\n", encoding="utf-8")
    md = cb.render_markdown(cb.compute(p))
    assert "code blocks" in md
    assert "block_count: 1" in md


def test_cli_fail_on_unbalanced(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("```\n", encoding="utf-8")
    rc = cb.main(["--summary", str(p), "--fail-on-unbalanced"])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("```\na\n```\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = cb.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["block_count"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cb.main(["--summary", str(tmp_path / "nope.md")])
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


def test_weekly_has_code_blocks_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary code blocks" in names
    assert "Upload Plan 2.8 weekly summary code blocks" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary code blocks")
    assert "plan_2_8_weekly_summary_code_blocks.py" in step["run"]

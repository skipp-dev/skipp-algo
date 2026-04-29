"""Tests for ``scripts/plan_2_8_weekly_summary_list_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_list_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_list_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_list_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


ls = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["total"] == 0


def test_bullets_dash(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("- one\n- two\n- three\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["bullet_count"] == 3
    assert rep["numbered_count"] == 0


def test_bullets_star(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("* one\n* two\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["bullet_count"] == 2


def test_numbered(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("1. first\n2. second\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["numbered_count"] == 2
    assert rep["bullet_count"] == 0


def test_mixed(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("- a\n1. b\n- c\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["bullet_count"] == 2
    assert rep["numbered_count"] == 1
    assert rep["total"] == 3


def test_code_block_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n- not a real bullet\n1. not numbered\n```\n- real\n",
        encoding="utf-8",
    )
    rep = ls.compute(p)
    assert rep["bullet_count"] == 1
    assert rep["numbered_count"] == 0


def test_indented_bullets(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("  - nested\n    - deeper\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["bullet_count"] == 2


def test_hyphen_only_skipped(tmp_path: Path) -> None:
    # "- " followed by nothing shouldn't count (horizontal rule hint)
    p = tmp_path / "s.md"
    p.write_text("-\n- real\n", encoding="utf-8")
    rep = ls.compute(p)
    assert rep["bullet_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("- a\n", encoding="utf-8")
    md = ls.render_markdown(ls.compute(p))
    assert "list stats" in md
    assert "bullet_count: 1" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("- a\n", encoding="utf-8")
    rc = ls.main(["--summary", str(p), "--fail-below-total", "5"])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("- a\n- b\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ls.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["bullet_count"] == 2


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ls.main(["--summary", str(tmp_path / "nope.md")])
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


def test_weekly_has_list_stats_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary list stats" in names
    assert "Upload Plan 2.8 weekly summary list stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary list stats")
    assert "plan_2_8_weekly_summary_list_stats.py" in step["run"]

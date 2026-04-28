"""Tests for ``scripts/plan_2_8_weekly_summary_preview.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_preview.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_preview", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_preview"] = mod
    spec.loader.exec_module(mod)
    return mod


sp = _load()


def test_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = sp.preview(p, 5)
    assert rep["total_lines"] == 0
    assert rep["preview_lines"] == 0


def test_short_file(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    rep = sp.preview(p, 10)
    assert rep["total_lines"] == 3
    assert rep["preview_lines"] == 3


def test_truncation(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\nc\nd\n", encoding="utf-8")
    rep = sp.preview(p, 2)
    assert rep["preview"] == ["a", "b"]
    assert rep["total_lines"] == 4


def test_zero_max_lines(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\n", encoding="utf-8")
    rep = sp.preview(p, 0)
    assert rep["preview"] == []
    assert rep["total_lines"] == 2


def test_negative_max_lines_clamped_to_zero(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n", encoding="utf-8")
    rep = sp.preview(p, -5)
    assert rep["preview"] == []


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    rep = sp.preview(tmp_path / "nope.md", 5)
    assert rep["total_lines"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("# Heading\nbody\n", encoding="utf-8")
    md = sp.render_markdown(sp.preview(p, 10))
    assert "summary preview" in md
    assert "```" in md
    assert "Heading" in md


def test_markdown_empty_placeholder(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    md = sp.render_markdown(sp.preview(p, 5))
    assert "_empty_" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\nb\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = sp.main([
        "--summary", str(p), "--max-lines", "1",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["preview"] == ["a"]


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sp.main(["--summary", str(tmp_path / "nope.md")])
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


def test_weekly_has_summary_preview_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary preview" in names
    assert "Upload Plan 2.8 weekly summary preview" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary preview")
    assert "plan_2_8_weekly_summary_preview.py" in step["run"]

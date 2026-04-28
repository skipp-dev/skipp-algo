"""Tests for ``scripts/plan_2_8_weekly_summary_line_length_stddev.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_line_length_stddev.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_line_length_stddev", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_line_length_stddev"] = mod
    spec.loader.exec_module(mod)
    return mod


sd = _load()


def test_missing(tmp_path: Path) -> None:
    assert sd.compute(tmp_path / "nope.md")["line_length_stddev"] == 0.0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("")
    rep = sd.compute(p)
    assert rep["line_count"] == 0
    assert rep["line_length_stddev"] == 0.0


def test_stddev(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    # lengths: 2, 4, 4, 6 -> mean=4, var=2, stddev=sqrt(2)
    p.write_text("xx\nxxxx\nxxxx\nxxxxxx\n")
    rep = sd.compute(p)
    assert rep["line_count"] == 4
    assert rep["line_length_stddev"] == round((2.0) ** 0.5, 4)


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("x\n")
    assert "line_length_stddev" in sd.render_markdown(sd.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("a\n")
    out = tmp_path / "o.json"
    code = sd.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["line_length_stddev"] == 0.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = sd.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_stddev_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary line length stddev" in names
    assert "Upload Plan 2.8 weekly summary line length stddev" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary line length stddev")
    assert "plan_2_8_weekly_summary_line_length_stddev.py" in step["run"]

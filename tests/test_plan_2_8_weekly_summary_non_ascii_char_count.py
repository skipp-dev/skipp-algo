"""Tests for ``scripts/plan_2_8_weekly_summary_non_ascii_char_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO / "scripts" / "plan_2_8_weekly_summary_non_ascii_char_count.py"
)
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_non_ascii_char_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_non_ascii_char_count"] = mod
    spec.loader.exec_module(mod)
    return mod


na = _load()


def test_missing(tmp_path: Path) -> None:
    assert na.compute(
        tmp_path / "nope.md")["non_ascii_char_count"] == 0


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("")
    assert na.compute(p)["non_ascii_char_count"] == 0


def test_count(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    # 3 non-ASCII: \u00e9 (e-acute), \u00fc (u-umlaut), \u2014 (em dash)
    p.write_text("caf\u00e9 f\u00fcr \u2014 ok\n", encoding="utf-8")
    assert na.compute(p)["non_ascii_char_count"] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("x\n")
    assert "non_ascii_char_count" in na.render_markdown(na.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("\u00e9\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = na.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["non_ascii_char_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = na.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_non_ascii_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary non-ascii char count" in names
    assert "Upload Plan 2.8 weekly summary non-ascii char count" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 weekly summary non-ascii char count")
    assert "plan_2_8_weekly_summary_non_ascii_char_count.py" in step["run"]

"""Tests for ``plan_2_8_weekly_summary_leading_comma_line_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
NAME = "plan_2_8_weekly_summary_leading_comma_line_count"
SCRIPT = REPO / "scripts" / f"{NAME}.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"
KEY = "leading_comma_line_count"
NM = "Plan 2.8 weekly summary leading comma line count"


def _load():
    spec = importlib.util.spec_from_file_location(NAME, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = mod
    spec.loader.exec_module(mod)
    return mod


m = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    assert m.compute(p)[KEY] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(",a\nfoo\n,bc\n# bar\n", encoding="utf-8")
    assert m.compute(p)[KEY] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(",x\n", encoding="utf-8")
    assert KEY in m.render_markdown(m.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(",x\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = m.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))[KEY] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = m.main(["--summary", str(tmp_path / "nope.md")])
    assert code == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_lcma_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert NM in names
    assert f"Upload {NM}" in names
    step = next(s for s in steps if s.get("name") == NM)
    assert f"{NAME}.py" in step["run"]

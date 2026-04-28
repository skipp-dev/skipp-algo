"""Tests for ``scripts/plan_2_8_ledger_green_streak_max.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_green_streak_max.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_green_streak_max", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_green_streak_max"] = mod
    spec.loader.exec_module(mod)
    return mod


gs = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "2026-05-10T00:00:00Z"}


def test_empty() -> None:
    assert gs.compute([])["green_streak_max"] == 0


def test_streak() -> None:
    recs = [
        _r("green"), _r("green"), _r("amber"),
        _r("green"), _r("green"), _r("green"), _r("red"),
    ]
    rep = gs.compute(recs)
    assert rep["record_count"] == 7
    assert rep["green_streak_max"] == 3


def test_markdown_shape() -> None:
    assert "green_streak_max" in gs.render_markdown(
        gs.compute([_r("green")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = gs.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["green_streak_max"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = gs.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_green_streak_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger green streak max" in names
    assert "Upload Plan 2.8 ledger green streak max" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger green streak max")
    assert "plan_2_8_ledger_green_streak_max.py" in step["run"]

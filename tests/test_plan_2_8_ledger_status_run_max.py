"""Tests for ``scripts/plan_2_8_ledger_status_run_max.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_run_max.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_run_max", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_run_max"] = mod
    spec.loader.exec_module(mod)
    return mod


rm = _load()


def _r(st: str, t: str) -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    assert rm.compute([])["found"] is False


def test_single_run() -> None:
    rep = rm.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("green", "2026-04-20T01:00:00+00:00"),
    ])
    assert rep["status"] == "green"
    assert rep["length"] == 2


def test_picks_longest() -> None:
    rep = rm.compute([
        _r("green", "t1"),
        _r("amber", "t2"),
        _r("amber", "t3"),
        _r("amber", "t4"),
        _r("red",   "t5"),
    ])
    assert rep["status"] == "amber"
    assert rep["length"] == 3
    assert rep["start"] == "t2"
    assert rep["end"] == "t4"


def test_tie_prefers_first() -> None:
    rep = rm.compute([
        _r("green", "t1"),
        _r("green", "t2"),
        _r("amber", "t3"),
        _r("amber", "t4"),
    ])
    assert rep["status"] == "green"


def test_invalid_skipped() -> None:
    assert rm.compute([_r("bogus", "t1")])["found"] is False


def test_markdown_empty() -> None:
    assert "_none_" in rm.render_markdown(rm.compute([]))


def test_markdown_shape() -> None:
    md = rm.render_markdown(rm.compute([_r("green", "t1")]))
    assert "status: green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green", "t1")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = rm.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = rm.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_run_max_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status-run max" in names
    assert "Upload Plan 2.8 ledger status-run max" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status-run max")
    assert "plan_2_8_ledger_status_run_max.py" in step["run"]

"""Tests for ``scripts/plan_2_8_ledger_status_run_min.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_run_min.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_run_min", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_run_min"] = mod
    spec.loader.exec_module(mod)
    return mod


rn = _load()


def _r(st: str, t: str) -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    assert rn.compute([])["found"] is False


def test_single_run() -> None:
    rep = rn.compute([_r("green", "t1"), _r("green", "t2")])
    assert rep["status"] == "green"
    assert rep["length"] == 2


def test_picks_shortest() -> None:
    rep = rn.compute([
        _r("green", "t1"),
        _r("green", "t2"),
        _r("green", "t3"),
        _r("amber", "t4"),
        _r("red",   "t5"),
        _r("red",   "t6"),
    ])
    assert rep["status"] == "amber"
    assert rep["length"] == 1


def test_tie_prefers_first() -> None:
    rep = rn.compute([
        _r("green", "t1"),
        _r("amber", "t2"),
    ])
    assert rep["status"] == "green"


def test_invalid_skipped() -> None:
    assert rn.compute([_r("bogus", "t1")])["found"] is False


def test_markdown_empty() -> None:
    assert "_none_" in rn.render_markdown(rn.compute([]))


def test_markdown_shape() -> None:
    md = rn.render_markdown(rn.compute([_r("green", "t1")]))
    assert "status: green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green", "t1")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = rn.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = rn.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_run_min_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status-run min" in names
    assert "Upload Plan 2.8 ledger status-run min" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status-run min")
    assert "plan_2_8_ledger_status_run_min.py" in step["run"]

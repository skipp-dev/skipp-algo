"""Tests for ``scripts/plan_2_8_ledger_status_streaks.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_streaks.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_streaks", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_streaks"] = mod
    spec.loader.exec_module(mod)
    return mod


ss = _load()


def _r(s: str, t: str) -> dict[str, Any]:
    return {"status": s, "captured_at": t}


def test_empty() -> None:
    rep = ss.compute([])
    assert rep == {"schema_version": 1, "found": False}


def test_single() -> None:
    rep = ss.compute([_r("green", "T1")])
    assert rep["length"] == 1
    assert rep["status"] == "green"
    assert rep["start_at"] == "T1"


def test_tail_streak() -> None:
    recs = [
        _r("red", "T1"), _r("amber", "T2"),
        _r("green", "T3"), _r("green", "T4"), _r("green", "T5"),
    ]
    rep = ss.compute(recs)
    assert rep["length"] == 3
    assert rep["start_at"] == "T3"
    assert rep["end_at"] == "T5"


def test_length_one_when_status_flips() -> None:
    recs = [_r("green", "T1"), _r("green", "T2"), _r("red", "T3")]
    rep = ss.compute(recs)
    assert rep["status"] == "red"
    assert rep["length"] == 1


def test_invalid_filtered() -> None:
    recs = [_r("bogus", "T0"), _r("green", "T1")]
    rep = ss.compute(recs)
    assert rep["status"] == "green"
    assert rep["length"] == 1


def test_markdown_empty() -> None:
    assert "_none_" in ss.render_markdown(ss.compute([]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green", "T1")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ss.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["length"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ss.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_status_streaks_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status streaks" in names
    assert "Upload Plan 2.8 ledger status streaks" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status streaks")
    assert "plan_2_8_ledger_status_streaks.py" in step["run"]

"""Tests for ``scripts/plan_2_8_ledger_transition_matrix.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_transition_matrix.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_transition_matrix", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_transition_matrix"] = mod
    spec.loader.exec_module(mod)
    return mod


tm = _load()


def _r(status: str) -> dict[str, Any]:
    return {"status": status}


def test_empty_matrix() -> None:
    rep = tm.compute([])
    assert rep["total_transitions"] == 0
    for frm in tm.VALID_STATUSES:
        for to in tm.VALID_STATUSES:
            assert rep["matrix"][frm][to] == 0


def test_same_status_no_transition() -> None:
    rep = tm.compute([_r("green"), _r("green"), _r("green")])
    assert rep["total_transitions"] == 0


def test_green_to_amber() -> None:
    rep = tm.compute([_r("green"), _r("amber")])
    assert rep["matrix"]["green"]["amber"] == 1
    assert rep["total_transitions"] == 1


def test_chain_transitions() -> None:
    rep = tm.compute([
        _r("green"), _r("amber"), _r("red"), _r("green"),
    ])
    assert rep["matrix"]["green"]["amber"] == 1
    assert rep["matrix"]["amber"]["red"] == 1
    assert rep["matrix"]["red"]["green"] == 1
    assert rep["total_transitions"] == 3


def test_invalid_status_skipped() -> None:
    rep = tm.compute([_r("green"), _r("bogus"), _r("red")])
    # bogus filtered, so chain is green -> red
    assert rep["matrix"]["green"]["red"] == 1
    assert rep["total_transitions"] == 1


def test_unknown_status_tracked() -> None:
    rep = tm.compute([_r("green"), _r("unknown")])
    assert rep["matrix"]["green"]["unknown"] == 1


def test_markdown_contains_matrix_header() -> None:
    md = tm.render_markdown(tm.compute([_r("green"), _r("amber")]))
    assert "status transitions" in md
    assert "from \\ to" in md
    assert "green" in md and "amber" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green")) + "\n" + json.dumps(_r("amber")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = tm.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total_transitions"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = tm.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_transition_matrix_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger transition matrix" in names
    assert "Upload Plan 2.8 ledger transition matrix" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger transition matrix")
    assert "plan_2_8_ledger_transition_matrix.py" in step["run"]

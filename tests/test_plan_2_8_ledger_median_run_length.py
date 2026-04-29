"""Tests for ``scripts/plan_2_8_ledger_median_run_length.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_median_run_length.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_median_run_length", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_median_run_length"] = mod
    spec.loader.exec_module(mod)
    return mod


mr = _load()


def _r(st: str, t: str = "t") -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    rep = mr.compute([])
    assert rep["run_count"] == 0
    assert rep["median_length"] == 0.0


def test_odd() -> None:
    # runs: 2, 1, 3 -> sorted 1,2,3 -> median 2
    rep = mr.compute([
        _r("green"), _r("green"),
        _r("amber"),
        _r("red"), _r("red"), _r("red"),
    ])
    assert rep["run_count"] == 3
    assert rep["median_length"] == 2.0


def test_even() -> None:
    # runs: 2, 1, 3, 4 -> sorted 1,2,3,4 -> median 2.5
    rep = mr.compute([
        _r("green"), _r("green"),
        _r("amber"),
        _r("red"), _r("red"), _r("red"),
        _r("unknown"), _r("unknown"), _r("unknown"), _r("unknown"),
    ])
    assert rep["median_length"] == 2.5


def test_invalid_skipped() -> None:
    assert mr.compute([_r("bogus")])["run_count"] == 0


def test_markdown_shape() -> None:
    md = mr.render_markdown(mr.compute([_r("green")]))
    assert "median_length" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = mr.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["run_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = mr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_run_length_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger median run length" in names
    assert "Upload Plan 2.8 ledger median run length" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger median run length")
    assert "plan_2_8_ledger_median_run_length.py" in step["run"]

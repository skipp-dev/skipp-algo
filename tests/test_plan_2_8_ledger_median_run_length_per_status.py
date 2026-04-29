"""Tests for ``scripts/plan_2_8_ledger_median_run_length_per_status.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_median_run_length_per_status.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_median_run_length_per_status", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_median_run_length_per_status"] = mod
    spec.loader.exec_module(mod)
    return mod


md = _load()


def _r(st: str) -> dict[str, Any]:
    return {"status": st, "captured_at": "t"}


def test_empty() -> None:
    rep = md.compute([])
    assert rep["median_by_status"] == {
        "green": 0.0, "amber": 0.0, "red": 0.0, "unknown": 0.0,
    }


def test_odd() -> None:
    # green runs: 1, 2, 3 -> median 2
    rep = md.compute([
        _r("green"),
        _r("amber"),
        _r("green"), _r("green"),
        _r("amber"),
        _r("green"), _r("green"), _r("green"),
    ])
    assert rep["median_by_status"]["green"] == 2.0


def test_even() -> None:
    # green runs: 1, 3 -> median 2.0
    rep = md.compute([
        _r("green"),
        _r("amber"),
        _r("green"), _r("green"), _r("green"),
    ])
    assert rep["median_by_status"]["green"] == 2.0


def test_invalid() -> None:
    assert md.compute([_r("bogus")])["median_by_status"]["green"] == 0.0


def test_markdown_shape() -> None:
    assert "green" in md.render_markdown(md.compute([_r("green")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = md.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["median_by_status"]["green"] == 1.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = md.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_per_status_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger median run length per status" in names
    assert "Upload Plan 2.8 ledger median run length per status" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 ledger median run length per status")
    assert "plan_2_8_ledger_median_run_length_per_status.py" in step["run"]

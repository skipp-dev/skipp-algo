"""Tests for ``scripts/plan_2_8_ledger_shortest_run.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_shortest_run.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_shortest_run", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_shortest_run"] = mod
    spec.loader.exec_module(mod)
    return mod


sr = _load()


def _r(st: str) -> dict[str, Any]:
    return {"status": st, "captured_at": "t"}


def test_empty() -> None:
    rep = sr.compute([])
    assert rep["run_count"] == 0
    assert rep["min_length"] == 0


def test_single() -> None:
    rep = sr.compute([_r("green"), _r("green")])
    assert rep["min_length"] == 2


def test_mixed() -> None:
    # runs 1, 3 -> min 1
    rep = sr.compute([
        _r("green"),
        _r("amber"), _r("amber"), _r("amber"),
    ])
    assert rep["min_length"] == 1


def test_invalid() -> None:
    assert sr.compute([_r("bogus")])["run_count"] == 0


def test_markdown_shape() -> None:
    assert "min_length" in sr.render_markdown(sr.compute([_r("green")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = sr.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["min_length"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = sr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_shortest_run_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger shortest run" in names
    assert "Upload Plan 2.8 ledger shortest run" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger shortest run")
    assert "plan_2_8_ledger_shortest_run.py" in step["run"]

"""Tests for ``scripts/plan_2_8_ledger_run_length_range.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_run_length_range.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_run_length_range", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_run_length_range"] = mod
    spec.loader.exec_module(mod)
    return mod


rr = _load()


def _r(st: str) -> dict[str, Any]:
    return {"status": st, "captured_at": "t"}


def test_empty() -> None:
    rep = rr.compute([])
    assert rep["run_count"] == 0
    assert rep["range"] == 0


def test_single() -> None:
    rep = rr.compute([_r("green"), _r("green")])
    assert rep["range"] == 0


def test_range() -> None:
    # runs 1, 3 -> range 2
    rep = rr.compute([
        _r("green"),
        _r("amber"), _r("amber"), _r("amber"),
    ])
    assert rep["range"] == 2


def test_invalid() -> None:
    assert rr.compute([_r("bogus")])["run_count"] == 0


def test_markdown_shape() -> None:
    assert "range" in rr.render_markdown(rr.compute([_r("green")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = rr.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["range"] == 0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = rr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_range_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger run length range" in names
    assert "Upload Plan 2.8 ledger run length range" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger run length range")
    assert "plan_2_8_ledger_run_length_range.py" in step["run"]

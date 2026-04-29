"""Tests for ``scripts/plan_2_8_ledger_last_n_summary.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_last_n_summary.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_last_n_summary", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_last_n_summary"] = mod
    spec.loader.exec_module(mod)
    return mod


ln = _load()


def _r(status: str) -> dict[str, Any]:
    return {"status": status, "captured_at": "2026-04-20T00:00:00+00:00"}


def test_empty() -> None:
    rep = ln.compute([], 5)
    assert rep["window_size"] == 0
    assert sum(rep["counts"].values()) == 0


def test_last_n_truncation() -> None:
    rep = ln.compute([_r("green")] * 10 + [_r("amber")] * 2, 5)
    assert rep["window_size"] == 5
    assert rep["counts"]["amber"] == 2
    assert rep["counts"]["green"] == 3


def test_last_n_larger_than_total() -> None:
    rep = ln.compute([_r("green")] * 3, 10)
    assert rep["window_size"] == 3
    assert rep["counts"]["green"] == 3


def test_zero_means_all() -> None:
    rep = ln.compute([_r("green")] * 5, 0)
    assert rep["window_size"] == 5


def test_invalid_filtered() -> None:
    rep = ln.compute(
        [_r("green"), _r("bogus"), _r("amber"), _r("amber")], 2,
    )
    # cleaned = [green, amber, amber]; window = last 2 = [amber, amber]
    assert rep["counts"]["amber"] == 2
    assert rep["counts"]["green"] == 0


def test_markdown_shape() -> None:
    md = ln.render_markdown(ln.compute([_r("green")], 10))
    assert "last-N summary" in md
    assert "green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ln.main([
        "--ledger", str(p), "--last-n", "5",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["window_size"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ln.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_last_n_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger last-N summary" in names
    assert "Upload Plan 2.8 ledger last-N summary" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger last-N summary")
    assert "plan_2_8_ledger_last_n_summary.py" in step["run"]

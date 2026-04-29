"""Tests for ``scripts/plan_2_8_ledger_best_day.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_best_day.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_best_day", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_best_day"] = mod
    spec.loader.exec_module(mod)
    return mod


bd = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_returns_none() -> None:
    rep = bd.compute([])
    assert rep["best_date"] is None
    assert rep["green"] == 0


def test_single_green() -> None:
    rep = bd.compute([_rec("2026-04-21T00:00:00+00:00", "green")])
    assert rep["best_date"] == "2026-04-21"
    assert rep["green"] == 1


def test_picks_most_green() -> None:
    rep = bd.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
        _rec("2026-04-21T06:00:00+00:00", "green"),
        _rec("2026-04-22T00:00:00+00:00", "amber"),
    ])
    assert rep["best_date"] == "2026-04-21"
    assert rep["green"] == 2


def test_tie_earliest_wins() -> None:
    rep = bd.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ])
    assert rep["best_date"] == "2026-04-20"


def test_invalid_skipped() -> None:
    rep = bd.compute([
        _rec("bogus", "green"),
        _rec("2026-04-21T00:00:00+00:00", "nope"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ])
    assert rep["green"] == 1


def test_all_non_green_zero() -> None:
    rep = bd.compute([
        _rec("2026-04-20T00:00:00+00:00", "amber"),
        _rec("2026-04-21T00:00:00+00:00", "red"),
    ])
    assert rep["best_date"] == "2026-04-20"
    assert rep["green"] == 0


def test_markdown_empty() -> None:
    md = bd.render_markdown(bd.compute([]))
    assert "no records" in md


def test_markdown_shape() -> None:
    md = bd.render_markdown(bd.compute([
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ]))
    assert "2026-04-21" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = bd.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["best_date"] == "2026-04-21"


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = bd.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_best_day_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger best day" in names
    assert "Upload Plan 2.8 ledger best day" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger best day")
    assert "plan_2_8_ledger_best_day.py" in step["run"]

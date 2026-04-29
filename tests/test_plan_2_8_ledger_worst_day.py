"""Tests for ``scripts/plan_2_8_ledger_worst_day.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_worst_day.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_worst_day", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_worst_day"] = mod
    spec.loader.exec_module(mod)
    return mod


wd = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_returns_none() -> None:
    rep = wd.compute([])
    assert rep["worst_date"] is None
    assert rep["non_green"] == 0


def test_single_all_green_non_green_zero() -> None:
    rep = wd.compute([_rec("2026-04-21T00:00:00+00:00", "green")])
    assert rep["worst_date"] == "2026-04-21"
    assert rep["non_green"] == 0


def test_picks_day_with_most_non_green() -> None:
    rep = wd.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "red"),
        _rec("2026-04-21T06:00:00+00:00", "amber"),
    ])
    assert rep["worst_date"] == "2026-04-21"
    assert rep["non_green"] == 2


def test_tie_breaks_earliest_date() -> None:
    rep = wd.compute([
        _rec("2026-04-20T00:00:00+00:00", "red"),
        _rec("2026-04-21T00:00:00+00:00", "red"),
    ])
    assert rep["worst_date"] == "2026-04-20"


def test_invalid_records_skipped() -> None:
    rep = wd.compute([
        _rec("not-a-date", "red"),
        _rec("2026-04-21T00:00:00+00:00", "bogus"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ])
    assert rep["worst_date"] == "2026-04-21"
    assert rep["non_green"] == 1


def test_markdown_empty() -> None:
    md = wd.render_markdown(wd.compute([]))
    assert "no records" in md


def test_markdown_non_empty() -> None:
    md = wd.render_markdown(wd.compute([
        _rec("2026-04-21T00:00:00+00:00", "red"),
    ]))
    assert "2026-04-21" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00", "red")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = wd.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["worst_date"] == "2026-04-21"


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wd.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_worst_day_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger worst day" in names
    assert "Upload Plan 2.8 ledger worst day" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger worst day")
    assert "plan_2_8_ledger_worst_day.py" in step["run"]

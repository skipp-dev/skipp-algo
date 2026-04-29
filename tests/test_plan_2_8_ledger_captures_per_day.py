"""Tests for ``scripts/plan_2_8_ledger_captures_per_day.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_captures_per_day.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_captures_per_day", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_captures_per_day"] = mod
    spec.loader.exec_module(mod)
    return mod


cp = _load()


def _r(t: str) -> dict[str, Any]:
    return {"status": "green", "captured_at": t}


def test_empty() -> None:
    rep = cp.compute([])
    assert rep["distinct_days"] == 0
    assert rep["total_captures"] == 0
    assert rep["per_day"] == []


def test_same_day() -> None:
    rep = cp.compute([
        _r("2026-04-20T01:00:00+00:00"),
        _r("2026-04-20T23:00:00+00:00"),
    ])
    assert rep["distinct_days"] == 1
    assert rep["per_day"] == [{"day": "2026-04-20", "count": 2}]


def test_multi_days_sorted() -> None:
    rep = cp.compute([
        _r("2026-04-22T00:00:00+00:00"),
        _r("2026-04-20T00:00:00+00:00"),
        _r("2026-04-20T12:00:00+00:00"),
        _r("2026-04-21T00:00:00+00:00"),
    ])
    assert rep["distinct_days"] == 3
    assert [e["day"] for e in rep["per_day"]] == [
        "2026-04-20", "2026-04-21", "2026-04-22",
    ]
    assert [e["count"] for e in rep["per_day"]] == [2, 1, 1]


def test_invalid_timestamp_skipped() -> None:
    rep = cp.compute([
        {"status": "green", "captured_at": "nope"},
        _r("2026-04-20T00:00:00+00:00"),
    ])
    assert rep["total_captures"] == 1


def test_invalid_status_skipped() -> None:
    rep = cp.compute([
        {"status": "bogus", "captured_at": "2026-04-20T00:00:00+00:00"},
    ])
    assert rep["total_captures"] == 0


def test_markdown_shape() -> None:
    md = cp.render_markdown(
        cp.compute([_r("2026-04-20T00:00:00+00:00")]),
    )
    assert "captures per day" in md
    assert "2026-04-20: 1" in md


def test_markdown_empty() -> None:
    md = cp.render_markdown(cp.compute([]))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("2026-04-20T00:00:00+00:00")) + "\n",
                 encoding="utf-8")
    out = tmp_path / "o.json"
    rc = cp.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_captures"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cp.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_captures_per_day_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger captures per day" in names
    assert "Upload Plan 2.8 ledger captures per day" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger captures per day")
    assert "plan_2_8_ledger_captures_per_day.py" in step["run"]

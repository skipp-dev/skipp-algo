"""Tests for ``scripts/plan_2_8_ledger_median_gap.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_median_gap.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_median_gap", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_median_gap"] = mod
    spec.loader.exec_module(mod)
    return mod


mg = _load()


def _r(t: str) -> dict[str, Any]:
    return {"status": "green", "captured_at": t}


def test_empty() -> None:
    rep = mg.compute([])
    assert rep["gaps"] == 0
    assert rep["median_hours"] is None


def test_single_record() -> None:
    rep = mg.compute([_r("2026-04-20T00:00:00+00:00")])
    assert rep["gaps"] == 0
    assert rep["median_hours"] is None


def test_two_records() -> None:
    rep = mg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        _r("2026-04-20T02:00:00+00:00"),
    ])
    assert rep["gaps"] == 1
    assert rep["median_hours"] == 2.0


def test_median_of_three_gaps() -> None:
    rep = mg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        _r("2026-04-20T01:00:00+00:00"),  # gap 1h
        _r("2026-04-20T03:00:00+00:00"),  # gap 2h
        _r("2026-04-20T09:00:00+00:00"),  # gap 6h
    ])
    assert rep["median_hours"] == 2.0


def test_invalid_timestamp_skipped() -> None:
    rep = mg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        {"status": "green", "captured_at": "bogus"},
        _r("2026-04-20T02:00:00+00:00"),
    ])
    assert rep["records"] == 2
    assert rep["median_hours"] == 2.0


def test_markdown_na() -> None:
    md = mg.render_markdown(mg.compute([]))
    assert "median_hours: n/a" in md


def test_cli_fail_above(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("2026-04-20T00:00:00+00:00")) + "\n"
        + json.dumps(_r("2026-04-20T10:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    rc = mg.main([
        "--ledger", str(p), "--fail-above-hours", "5",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("2026-04-20T00:00:00+00:00")) + "\n"
        + json.dumps(_r("2026-04-20T02:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = mg.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["median_hours"] == 2.0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = mg.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_gap_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger median gap" in names
    assert "Upload Plan 2.8 ledger median gap" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger median gap")
    assert "plan_2_8_ledger_median_gap.py" in step["run"]

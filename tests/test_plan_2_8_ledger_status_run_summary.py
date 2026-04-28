"""Tests for ``scripts/plan_2_8_ledger_status_run_summary.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_run_summary.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_run_summary", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_run_summary"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


def _r(st: str, t: str) -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    rep = rs.compute([])
    assert rep["run_count"] == 0


def test_single_run() -> None:
    rep = rs.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("green", "2026-04-20T01:00:00+00:00"),
    ])
    assert rep["run_count"] == 1
    e = rep["entries"][0]
    assert e["status"] == "green"
    assert e["length"] == 2
    assert e["start"] == "2026-04-20T00:00:00+00:00"
    assert e["end"] == "2026-04-20T01:00:00+00:00"


def test_multiple_runs() -> None:
    rep = rs.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("amber", "2026-04-20T01:00:00+00:00"),
        _r("amber", "2026-04-20T02:00:00+00:00"),
        _r("red",   "2026-04-20T03:00:00+00:00"),
    ])
    assert rep["run_count"] == 3
    statuses = [e["status"] for e in rep["entries"]]
    assert statuses == ["green", "amber", "red"]
    assert rep["entries"][1]["length"] == 2


def test_invalid_skipped() -> None:
    assert rs.compute([_r("bogus", "2026-04-20T00:00:00+00:00")])[
        "run_count"
    ] == 0


def test_markdown_shape() -> None:
    md = rs.render_markdown(rs.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
    ]))
    assert "length=1" in md
    assert "start=" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-04-20T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = rs.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["run_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = rs.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_run_summary_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status-run summary" in names
    assert "Upload Plan 2.8 ledger status-run summary" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status-run summary")
    assert "plan_2_8_ledger_status_run_summary.py" in step["run"]

"""Tests for ``scripts/plan_2_8_status_ledger_summarize.py`` + wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status_ledger_summarize.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_status_ledger_summarize", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status_ledger_summarize"] = mod
    spec.loader.exec_module(mod)
    return mod


ss = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_records_summary() -> None:
    rep = ss.summarise([])
    assert rep["total"] == 0
    assert rep["pct_green"] == 0.0
    assert rep["current_status"] is None
    assert rep["current_streak"] == 0
    assert rep["last_flip"] is None


def test_counts_and_pct_green() -> None:
    records = [
        _rec("t1", "green"), _rec("t2", "amber"), _rec("t3", "green"),
        _rec("t4", "green"),
    ]
    rep = ss.summarise(records)
    assert rep["counts"] == {"green": 3, "amber": 1, "red": 0, "unknown": 0}
    assert rep["total"] == 4
    assert rep["pct_green"] == 75.0


def test_current_streak_simple() -> None:
    records = [
        _rec("t1", "amber"), _rec("t2", "green"),
        _rec("t3", "green"), _rec("t4", "green"),
    ]
    rep = ss.summarise(records)
    assert rep["current_status"] == "green"
    assert rep["current_streak"] == 3
    assert rep["last_flip"] == "t1"


def test_single_record_streak() -> None:
    rep = ss.summarise([_rec("t1", "green")])
    assert rep["current_streak"] == 1
    assert rep["last_flip"] is None


def test_all_identical_status_no_flip() -> None:
    rep = ss.summarise([
        _rec("t1", "green"), _rec("t2", "green"), _rec("t3", "green"),
    ])
    assert rep["current_streak"] == 3
    assert rep["last_flip"] is None


def test_unknown_status_bucketed() -> None:
    rep = ss.summarise([_rec("t1", "bogus")])
    assert rep["counts"]["unknown"] == 1
    assert rep["total"] == 1


def test_non_string_status_skipped() -> None:
    rep = ss.summarise([
        {"captured_at": "t1", "status": 7},
        _rec("t2", "green"),
    ])
    assert rep["total"] == 1
    assert rep["counts"]["green"] == 1


def test_status_case_normalised() -> None:
    rep = ss.summarise([_rec("t1", "GREEN"), _rec("t2", "Amber")])
    assert rep["counts"]["green"] == 1
    assert rep["counts"]["amber"] == 1


def test_render_markdown_format() -> None:
    rep = ss.summarise([_rec("t1", "green"), _rec("t2", "green")])
    md = ss.render_markdown(rep)
    assert "Plan 2.8 status ledger summary" in md
    assert "current streak:  2" in md
    assert "% green:         100.0" in md


def _seed(tmp: Path, records: list[dict[str, Any]],
          extra_lines: list[str] | None = None) -> Path:
    p = tmp / "l.jsonl"
    lines = [json.dumps(r) for r in records]
    if extra_lines:
        lines.extend(extra_lines)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_iter_tolerates_blank_and_malformed(tmp_path: Path) -> None:
    p = _seed(
        tmp_path,
        [_rec("t1", "green"), _rec("t2", "amber")],
        extra_lines=["", "not-json", "{}"],
    )
    records = ss._iter_records(p)
    # 2 valid + {} becomes a bare dict (valid but no status)
    assert len(records) == 3


def test_cli_md_output(tmp_path: Path) -> None:
    p = _seed(tmp_path, [_rec("t1", "green"), _rec("t2", "green")])
    out = tmp_path / "s.md"
    rc = ss.main([
        "--ledger", str(p), "--output", str(out),
    ])
    assert rc == 0
    assert "status ledger summary" in out.read_text(encoding="utf-8")


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = _seed(tmp_path, [_rec("t1", "green")])
    rc = ss.main([
        "--ledger", str(p), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ss.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_ledger_summary_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 status ledger summary" in names
    assert "Upload Plan 2.8 status ledger summary" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 status ledger summary")
    assert "plan_2_8_status_ledger_summarize.py" in step["run"]

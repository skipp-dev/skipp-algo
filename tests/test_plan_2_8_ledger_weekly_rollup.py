"""Tests for ``scripts/plan_2_8_ledger_weekly_rollup.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_weekly_rollup.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_weekly_rollup", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_weekly_rollup"] = mod
    spec.loader.exec_module(mod)
    return mod


wr = _load()


NOW = _dt.datetime(2026, 4, 21, 12, 0, tzinfo=_dt.UTC)


def _rec(days_ago: int, status: str) -> dict[str, Any]:
    ts = (NOW - _dt.timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S%z",
    )
    return {"captured_at": ts, "status": status}


def test_empty_records() -> None:
    rep = wr.summarise([], weeks=1, now=NOW)
    assert rep["total"] == 0
    assert rep["flips"] == 0
    assert rep["latest"] is None


def test_respects_window() -> None:
    records = [_rec(60, "green"), _rec(3, "amber"), _rec(0, "green")]
    rep = wr.summarise(records, weeks=1, now=NOW)
    assert rep["total"] == 2
    assert rep["counts"]["amber"] == 1
    assert rep["counts"]["green"] == 1
    assert rep["latest"] == "green"
    assert rep["flips"] == 1


def test_weeks_must_be_positive() -> None:
    with pytest.raises(ValueError):
        wr.summarise([], weeks=0, now=NOW)


def test_invalid_status_dropped() -> None:
    rep = wr.summarise([_rec(3, "bogus"), _rec(1, "green")], weeks=1,
                       now=NOW)
    assert rep["total"] == 1


def test_bad_timestamp_dropped() -> None:
    records = [{"captured_at": "not-a-date", "status": "green"},
               _rec(1, "green")]
    rep = wr.summarise(records, weeks=1, now=NOW)
    assert rep["total"] == 1


def test_case_normalised() -> None:
    rep = wr.summarise([_rec(3, "GREEN")], weeks=1, now=NOW)
    assert rep["counts"]["green"] == 1


def test_render_markdown_shape() -> None:
    rep = wr.summarise([_rec(3, "green"), _rec(1, "amber")], weeks=1,
                       now=NOW)
    md = wr.render_markdown(rep)
    assert "weekly rollup" in md
    assert "latest status: amber" in md
    assert "| green | 1 |" in md


def test_render_markdown_empty_latest() -> None:
    md = wr.render_markdown(wr.summarise([], weeks=2, now=NOW))
    assert "latest status: -" in md
    assert "last 2 wk" in md


def test_cli_md_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_rec(1, "green")) + "\n", encoding="utf-8")
    out = tmp_path / "r.md"
    rc = wr.main([
        "--ledger", str(p), "--weeks", "2", "--output", str(out),
    ])
    assert rc == 0
    assert "weekly rollup" in out.read_text(encoding="utf-8")


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_rec(1, "green")) + "\n", encoding="utf-8")
    rc = wr.main([
        "--ledger", str(p), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["weeks"] == 1


def test_cli_bad_weeks_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    rc = wr.main([
        "--ledger", str(p), "--weeks", "0",
    ])
    assert rc == 1
    assert ">= 1" in capsys.readouterr().err


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err

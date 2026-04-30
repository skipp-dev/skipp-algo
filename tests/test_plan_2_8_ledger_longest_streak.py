"""Tests for ``scripts/plan_2_8_ledger_longest_streak.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_longest_streak.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_longest_streak", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_longest_streak"] = mod
    spec.loader.exec_module(mod)
    return mod


ls = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_all_zero() -> None:
    rep = ls.compute([])
    for s in ("green", "amber", "red", "unknown"):
        assert rep["longest"][s]["length"] == 0
        assert rep["longest"][s]["start"] is None


def test_single_record() -> None:
    rep = ls.compute([_rec("2026-04-21T00:00:00+00:00", "green")])
    assert rep["longest"]["green"]["length"] == 1


def test_finds_longest_run_per_status() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-02T00:00:00+00:00", "green"),
        _rec("2026-04-03T00:00:00+00:00", "amber"),
        _rec("2026-04-04T00:00:00+00:00", "green"),
        _rec("2026-04-05T00:00:00+00:00", "green"),
        _rec("2026-04-06T00:00:00+00:00", "green"),
        _rec("2026-04-07T00:00:00+00:00", "red"),
    ]
    rep = ls.compute(records)
    assert rep["longest"]["green"]["length"] == 3
    assert rep["longest"]["green"]["start"].startswith("2026-04-04")
    assert rep["longest"]["green"]["end"].startswith("2026-04-06")
    assert rep["longest"]["amber"]["length"] == 1
    assert rep["longest"]["red"]["length"] == 1


def test_invalid_statuses_ignored() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-02T00:00:00+00:00", "bogus"),
        _rec("2026-04-03T00:00:00+00:00", "green"),
    ]
    rep = ls.compute(records)
    # the bogus record is dropped; the two greens are adjacent after
    # filtering, so the longest green run is 2.
    assert rep["longest"]["green"]["length"] == 2


def test_markdown_lists_all_four_statuses() -> None:
    md = ls.render_markdown(ls.compute([_rec("2026-04-21T00:00:00+00:00",
                                             "green")]))
    for s in ("green", "amber", "red", "unknown"):
        assert f"## {s}" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec("2026-04-01T00:00:00+00:00", "green"),
            _rec("2026-04-02T00:00:00+00:00", "green"),
        ]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["longest"]["green"]["length"] == 2


def test_cli_md(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    out = tmp_path / "o.md"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    assert "longest streaks" in out.read_text(encoding="utf-8")


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ls.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_invalid_json_lines_skipped(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "not-json\n"
        + json.dumps(_rec("2026-04-01T00:00:00+00:00", "green")) + "\n"
        + json.dumps(_rec("2026-04-02T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["longest"]["green"]["length"] == 2

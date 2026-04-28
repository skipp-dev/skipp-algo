"""Tests for ``scripts/plan_2_8_ledger_status_matrix.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_matrix.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_status_matrix", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_matrix"] = mod
    spec.loader.exec_module(mod)
    return mod


mx = _load()


def _rec(status: str) -> dict[str, Any]:
    return {"captured_at": "t", "status": status}


def test_empty_matrix_is_zeroed() -> None:
    rep = mx.build_matrix([])
    assert rep["counts"]["transitions"] == 0
    for a in mx.VALID_STATUSES:
        for b in mx.VALID_STATUSES:
            assert rep["matrix"][a][b] == 0


def test_single_record_produces_no_transitions() -> None:
    rep = mx.build_matrix([_rec("green")])
    assert rep["counts"]["transitions"] == 0


def test_transitions_counted() -> None:
    records = [_rec("green"), _rec("amber"), _rec("red"), _rec("green")]
    rep = mx.build_matrix(records)
    assert rep["counts"]["transitions"] == 3
    m = rep["matrix"]
    assert m["green"]["amber"] == 1
    assert m["amber"]["red"] == 1
    assert m["red"]["green"] == 1


def test_self_loop_counted() -> None:
    rep = mx.build_matrix([_rec("green"), _rec("green")])
    assert rep["matrix"]["green"]["green"] == 1


def test_invalid_status_breaks_chain() -> None:
    # green -> bogus -> amber should yield no transitions
    # (bogus resets prev)
    records = [_rec("green"), _rec("bogus"), _rec("amber")]
    rep = mx.build_matrix(records)
    assert rep["counts"]["transitions"] == 0


def test_status_case_normalised() -> None:
    records = [_rec("GREEN"), _rec("Amber")]
    rep = mx.build_matrix(records)
    assert rep["matrix"]["green"]["amber"] == 1


def test_non_string_status_breaks_chain() -> None:
    records = [_rec("green"), {"captured_at": "t", "status": 7},
               _rec("amber")]
    rep = mx.build_matrix(records)
    assert rep["counts"]["transitions"] == 0


def test_render_markdown_has_headers() -> None:
    rep = mx.build_matrix([_rec("green"), _rec("amber")])
    md = mx.render_markdown(rep)
    assert "transition matrix" in md
    assert "**green**" in md
    assert "| green | amber | red | unknown |" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("\n".join(json.dumps(_rec(s)) for s in ("green", "amber"))
                 + "\n", encoding="utf-8")
    out = tmp_path / "m.json"
    rc = mx.main([
        "--ledger", str(p), "--output", str(out), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["matrix"]["green"]["amber"] == 1


def test_cli_md_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_rec("green")) + "\n", encoding="utf-8")
    rc = mx.main(["--ledger", str(p), "--format", "md"])
    assert rc == 0
    assert "transition matrix" in capsys.readouterr().out


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = mx.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err

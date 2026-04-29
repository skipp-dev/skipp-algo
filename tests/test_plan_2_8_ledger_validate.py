"""Tests for ``scripts/plan_2_8_ledger_validate.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_validate.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_validate", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_validate"] = mod
    spec.loader.exec_module(mod)
    return mod


lv = _load()


def _good(ts: str = "2026-04-21T12:00:00+00:00", status: str = "green") -> str:
    return json.dumps({"captured_at": ts, "status": status})


def test_all_valid() -> None:
    rep = lv.validate([_good(), _good(status="amber")])
    assert rep["counts"] == {"valid": 2, "invalid": 0}
    assert rep["invalid"] == []


def test_rejects_json_error() -> None:
    rep = lv.validate([_good(), "not-json"])
    assert rep["counts"]["valid"] == 1
    assert rep["counts"]["invalid"] == 1
    assert rep["invalid"][0]["reason"].startswith("json_error")
    assert rep["invalid"][0]["lineno"] == 2


def test_rejects_non_object() -> None:
    rep = lv.validate([_good(), "[1,2]"])
    assert rep["invalid"][0]["reason"] == "not_object"


def test_rejects_bad_timestamp() -> None:
    rep = lv.validate([json.dumps({"captured_at": "xxx", "status": "green"})])
    assert rep["invalid"][0]["reason"] == "bad_captured_at"


def test_rejects_missing_timestamp() -> None:
    rep = lv.validate([json.dumps({"status": "green"})])
    assert rep["invalid"][0]["reason"] == "bad_captured_at"


def test_rejects_bad_status() -> None:
    rep = lv.validate([json.dumps({
        "captured_at": "2026-04-21T12:00:00+00:00",
        "status": "bogus",
    })])
    assert rep["invalid"][0]["reason"] == "bad_status"


def test_accepts_case_insensitive_status() -> None:
    rep = lv.validate([json.dumps({
        "captured_at": "2026-04-21T12:00:00+00:00",
        "status": "GREEN",
    })])
    assert rep["counts"]["valid"] == 1


def test_accepts_trailing_z() -> None:
    rep = lv.validate([json.dumps({
        "captured_at": "2026-04-21T12:00:00Z",
        "status": "green",
    })])
    assert rep["counts"]["valid"] == 1


def test_skips_blank_lines() -> None:
    rep = lv.validate(["", "  ", _good()])
    assert rep["counts"]["valid"] == 1
    assert rep["counts"]["invalid"] == 0


def test_render_markdown_all_valid() -> None:
    rep = lv.validate([_good()])
    md = lv.render_markdown(rep)
    assert "All records valid" in md
    assert "valid:   1" in md


def test_render_markdown_lists_errors() -> None:
    rep = lv.validate([_good(), "not-json"])
    md = lv.render_markdown(rep)
    assert "| 2 |" in md
    assert "json_error" in md


def test_cli_md_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(_good() + "\n", encoding="utf-8")
    out = tmp_path / "v.md"
    rc = lv.main([
        "--ledger", str(p), "--output", str(out),
    ])
    assert rc == 0
    assert "status ledger validation" in out.read_text(encoding="utf-8")


def test_cli_fail_on_invalid(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("not-json\n", encoding="utf-8")
    rc = lv.main([
        "--ledger", str(p), "--fail-on-invalid",
    ])
    assert rc == 1


def test_cli_all_valid_success(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(_good() + "\n", encoding="utf-8")
    rc = lv.main([
        "--ledger", str(p), "--fail-on-invalid",
    ])
    assert rc == 0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lv.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err

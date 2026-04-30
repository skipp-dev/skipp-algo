"""Tests for ``scripts/plan_2_8_history_validate.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_validate.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_validate", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_validate"] = mod
    spec.loader.exec_module(mod)
    return mod


val = _load()


def _snap(captured_at: str, scoring_root: str = "out/x") -> dict:
    return {
        "captured_at": captured_at, "scoring_root": scoring_root,
        "files_scanned": 1, "per_tf": {},
    }


def _write(history: Path, lines: list[str]) -> None:
    history.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_validate_ok_on_clean_file(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [json.dumps(_snap("2026-04-21T07:00:00Z"))])
    report = val.validate(history)
    assert report["ok"] is True
    assert report["snapshots"] == 1
    assert report["errors"] == []
    assert report["duplicates"] == []


def test_validate_flags_corrupt_json(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [json.dumps(_snap("2026-04-21T07:00:00Z")), "{not json"])
    report = val.validate(history)
    assert report["ok"] is False
    kinds = [e["kind"] for e in report["errors"]]
    assert "json" in kinds


def test_validate_flags_unparseable_captured_at(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [json.dumps({**_snap("xx"), "captured_at": "not-a-date"})])
    report = val.validate(history)
    assert report["ok"] is False
    assert any(e["kind"] == "captured_at" for e in report["errors"])


def test_validate_flags_missing_scoring_root(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    snap = _snap("2026-04-21T07:00:00Z")
    snap.pop("scoring_root")
    _write(history, [json.dumps(snap)])
    report = val.validate(history)
    assert any(e["kind"] == "scoring_root" for e in report["errors"])


def test_validate_flags_duplicates(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        json.dumps(_snap("2026-04-21T07:00:00Z", "out/a")),
        json.dumps(_snap("2026-04-21T07:00:00Z", "out/a")),
    ])
    report = val.validate(history)
    assert report["ok"] is False
    assert report["duplicates"] == [
        {"captured_at": "2026-04-21T07:00:00Z", "scoring_root": "out/a"},
    ]


def test_validate_flags_non_object_snapshot(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, ["[1, 2, 3]"])
    report = val.validate(history)
    assert any(e["kind"] == "shape" for e in report["errors"])


def test_validate_flags_non_dict_per_tf(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    snap = _snap("2026-04-21T07:00:00Z")
    snap["per_tf"] = "oops"
    _write(history, [json.dumps(snap)])
    report = val.validate(history)
    assert any(e["kind"] == "per_tf" for e in report["errors"])


def test_validate_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="history not found"):
        val.validate(tmp_path / "nope.jsonl")


def test_cli_exit_zero_on_clean(tmp_path: Path,
                                capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [json.dumps(_snap("2026-04-21T07:00:00Z"))])
    rc = val.main(["--history", str(history), "--quiet"])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_cli_exit_one_on_errors_and_writes_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, ["not-json"])
    out = tmp_path / "report.json"
    rc = val.main(["--history", str(history), "--output", str(out), "--quiet"])
    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["snapshots"] == 0


def test_cli_missing_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = val.main(["--history", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err

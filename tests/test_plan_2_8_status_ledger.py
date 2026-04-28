"""Tests for ``scripts/plan_2_8_status_ledger.py`` + #77 wiring."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status_ledger.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_status_ledger", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status_ledger"] = mod
    spec.loader.exec_module(mod)
    return mod


sl = _load()


NOW = _dt.datetime(2026, 4, 22, 12, 0, 0, tzinfo=_dt.UTC)


def test_resolve_status_from_snapshot() -> None:
    assert sl.resolve_status({"status": "green"}) == "green"


def test_resolve_status_falls_back_to_rollup() -> None:
    assert sl.resolve_status({"rollup": "amber"}) == "amber"


def test_resolve_status_unknown_label_normalised() -> None:
    assert sl.resolve_status({"status": "weird"}) == "unknown"


def test_resolve_status_missing_becomes_unknown() -> None:
    assert sl.resolve_status({}) == "unknown"


def test_resolve_status_non_dict_becomes_unknown() -> None:
    assert sl.resolve_status(["not", "dict"]) == "unknown"


def test_resolve_status_case_insensitive() -> None:
    assert sl.resolve_status({"status": "GREEN"}) == "green"


def test_build_record_includes_status_and_time() -> None:
    rec = sl.build_record({"status": "green"}, now=NOW)
    assert rec["status"] == "green"
    assert rec["captured_at"].startswith("2026-04-22T12:00:00")


def test_build_record_omits_run_url_when_empty() -> None:
    rec = sl.build_record({"status": "green"}, run_url=None, now=NOW)
    assert "run_url" not in rec


def test_build_record_includes_run_url_when_set() -> None:
    rec = sl.build_record(
        {"status": "red"}, run_url="https://ci/run/1", now=NOW,
    )
    assert rec["run_url"] == "https://ci/run/1"


def test_append_creates_parent_dirs(tmp_path: Path) -> None:
    ledger = tmp_path / "nested" / "dir" / "l.jsonl"
    sl.append(ledger, {"captured_at": "t", "status": "green"})
    assert ledger.exists()
    line = ledger.read_text(encoding="utf-8").strip()
    assert json.loads(line)["status"] == "green"


def test_append_is_additive(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    sl.append(ledger, {"status": "green"})
    sl.append(ledger, {"status": "amber"})
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["status"] == "green"
    assert json.loads(lines[1])["status"] == "amber"


def test_cli_appends_and_prints_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps({"status": "green"}), encoding="utf-8")
    ledger = tmp_path / "l.jsonl"
    rc = sl.main([
        "--input", str(snap), "--ledger", str(ledger),
        "--run-url", "https://ci/run/9",
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert json.loads(out)["status"] == "green"
    assert ledger.exists()


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sl.main([
        "--input", str(tmp_path / "nope.json"),
        "--ledger", str(tmp_path / "l.jsonl"),
    ])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


def test_cli_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    rc = sl.main([
        "--input", str(bad), "--ledger", str(tmp_path / "l.jsonl"),
    ])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_ledger_append_and_download() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Download prior Plan 2.8 status ledger" in names
    assert "Plan 2.8 status ledger append" in names
    assert "Upload Plan 2.8 status ledger" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 status ledger append")
    assert "plan_2_8_status_ledger.py" in step["run"]
    assert "RUN_URL" in step["run"]

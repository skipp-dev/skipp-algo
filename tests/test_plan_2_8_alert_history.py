"""Tests for ``scripts/plan_2_8_alert_history.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_history.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_alert_history", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_history"] = mod
    spec.loader.exec_module(mod)
    return mod


ah = _load()


def _alert(tf: str, family: str, delta: float = 0.1) -> dict:
    return {"tf": tf, "family": family, "delta_pp": delta,
            "hr_prev": 0.50, "hr_latest": 0.50 + delta}


def test_appends_alerts_to_empty_log(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    summary = ah.append_alerts(
        log, [_alert("5m", "FVG"), _alert("1H", "OB", -0.2)],
        captured_at="2026-04-21T07:00:00Z",
    )
    assert summary == {"appended": 2, "skipped_duplicates": 0}
    lines = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln]
    assert {(r["tf"], r["family"]) for r in lines} == {("5m", "FVG"), ("1H", "OB")}
    assert lines[0]["captured_at"] == "2026-04-21T07:00:00Z"


def test_dedupe_on_captured_tf_family(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    ah.append_alerts(
        log, [_alert("5m", "FVG")], captured_at="2026-04-21T07:00:00Z",
    )
    summary = ah.append_alerts(
        log, [_alert("5m", "FVG"), _alert("5m", "OB")],
        captured_at="2026-04-21T07:00:00Z",
    )
    assert summary == {"appended": 1, "skipped_duplicates": 1}
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_different_captured_at_is_not_duplicate(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    ah.append_alerts(log, [_alert("5m", "FVG")],
                     captured_at="2026-04-14T07:00:00Z")
    summary = ah.append_alerts(log, [_alert("5m", "FVG")],
                               captured_at="2026-04-21T07:00:00Z")
    assert summary["appended"] == 1


def test_ignores_malformed_alert_entries(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    summary = ah.append_alerts(
        log, [{"tf": "5m"}, {"family": "OB"}, _alert("1H", "FVG")],
        captured_at="2026-04-21T07:00:00Z",
    )
    assert summary["appended"] == 1


def test_run_url_persisted(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    ah.append_alerts(
        log, [_alert("5m", "FVG")],
        captured_at="2026-04-21T07:00:00Z",
        run_url="https://example/run/1",
    )
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["run_url"] == "https://example/run/1"


def test_accepts_list_or_digest_shaped_payload(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    # Digest-shaped file with 'alerts'.
    src = tmp_path / "digest.json"
    src.write_text(json.dumps({"alerts": [_alert("5m", "FVG")]}),
                   encoding="utf-8")
    rc = ah.main([
        "--alerts", str(src), "--log", str(log),
        "--captured-at", "2026-04-21T07:00:00Z", "--quiet",
    ])
    assert rc == 0
    # Plain list format.
    src2 = tmp_path / "alerts2.json"
    src2.write_text(json.dumps([_alert("15m", "OB")]), encoding="utf-8")
    rc2 = ah.main([
        "--alerts", str(src2), "--log", str(log),
        "--captured-at", "2026-04-21T07:00:00Z", "--quiet",
    ])
    assert rc2 == 0
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_missing_alerts_file_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ah.main([
        "--alerts", str(tmp_path / "no.json"),
        "--log", str(tmp_path / "log.jsonl"),
    ])
    assert rc == 1
    assert "alerts file not found" in capsys.readouterr().err


def test_cli_emits_summary_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "log.jsonl"
    src = tmp_path / "a.json"
    src.write_text(json.dumps([_alert("5m", "FVG")]), encoding="utf-8")
    rc = ah.main([
        "--alerts", str(src), "--log", str(log),
        "--captured-at", "2026-04-21T07:00:00Z",
    ])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["appended"] == 1

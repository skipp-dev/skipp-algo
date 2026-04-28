"""Tests for the issue-body renderer + alerts-file output of trend_digest."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


digest_mod = _load(
    "plan_2_8_trend_digest",
    REPO / "scripts" / "plan_2_8_trend_digest.py",
)


def _snap(captured_at: str, scoring_root: str, hr: float, n: int = 100) -> dict:
    return {
        "captured_at": captured_at,
        "scoring_root": scoring_root,
        "files_scanned": 1,
        "per_tf": {
            "5m": {
                "n_events": n, "hit_rate": hr,
                "families": {"FVG": {"n_events": n, "hit_rate": hr}},
            },
        },
    }


def _digest_with_alert() -> dict:
    return digest_mod.build_digest(snapshots=[
        _snap("2026-04-14T07:00:00Z", "out/a", 0.40),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50),  # +10pp
    ])


def _digest_without_alert() -> dict:
    return digest_mod.build_digest(snapshots=[
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.46),  # +1pp
    ])


def test_has_alerts_helper() -> None:
    assert digest_mod.has_alerts(_digest_with_alert()) is True
    assert digest_mod.has_alerts(_digest_without_alert()) is False
    assert digest_mod.has_alerts({"alerts": []}) is False
    assert digest_mod.has_alerts({}) is False


def test_render_issue_body_includes_alert_count_and_endpoints() -> None:
    body = digest_mod.render_issue_body(_digest_with_alert())
    assert "drift alerts" in body
    assert "alerts: **1**" in body
    assert "previous snapshot:" in body
    assert "latest snapshot:" in body
    assert "2026-04-14T07:00:00Z" in body
    assert "2026-04-21T07:00:00Z" in body


def test_render_issue_body_lists_each_alert() -> None:
    body = digest_mod.render_issue_body(_digest_with_alert())
    assert "`5m/FVG`" in body
    assert "drift +0.100" in body
    assert "hr_prev=0.400" in body
    assert "hr_latest=0.500" in body


def test_render_issue_body_empty_alerts_renders_zero_section() -> None:
    body = digest_mod.render_issue_body(_digest_without_alert())
    assert "alerts: **0**" in body
    assert body.endswith("\n")


def test_render_issue_body_carries_thresholds() -> None:
    body = digest_mod.render_issue_body(_digest_with_alert())
    assert "threshold (pp):" in body
    assert "min_events floor:" in body


def test_cli_format_issue_emits_alert_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text("\n".join(json.dumps(s) for s in [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.40),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50),
    ]) + "\n", encoding="utf-8")
    rc = digest_mod.main([
        "--history", str(history),
        "--format", "issue",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "drift alerts" in out
    assert "`5m/FVG`" in out


def test_cli_alerts_file_records_count(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text("\n".join(json.dumps(s) for s in [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.40),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50),
    ]) + "\n", encoding="utf-8")
    alerts_file = tmp_path / "alerts.json"
    rc = digest_mod.main([
        "--history", str(history),
        "--alerts-file", str(alerts_file),
        "--format", "json",
    ])
    assert rc == 0
    info = json.loads(alerts_file.read_text(encoding="utf-8"))
    assert info == {"has_alerts": True, "count": 1}


def test_cli_alerts_file_zero_when_no_drift(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text("\n".join(json.dumps(s) for s in [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.46),
    ]) + "\n", encoding="utf-8")
    alerts_file = tmp_path / "alerts.json"
    rc = digest_mod.main([
        "--history", str(history),
        "--alerts-file", str(alerts_file),
        "--format", "issue",
    ])
    assert rc == 0
    info = json.loads(alerts_file.read_text(encoding="utf-8"))
    assert info == {"has_alerts": False, "count": 0}


def test_render_issue_body_appends_run_url_when_provided() -> None:
    body = digest_mod.render_issue_body(
        _digest_with_alert(),
        run_url="https://github.com/skippALGO/skipp-algo/actions/runs/42",
    )
    assert "Workflow run: https://github.com/skippALGO/skipp-algo/actions/runs/42" in body


def test_render_issue_body_omits_run_url_when_absent() -> None:
    body = digest_mod.render_issue_body(_digest_with_alert())
    assert "Workflow run:" not in body


def test_cli_run_url_is_threaded_into_issue_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text("\n".join(json.dumps(s) for s in [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.40),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50),
    ]) + "\n", encoding="utf-8")
    rc = digest_mod.main([
        "--history", str(history),
        "--format", "issue",
        "--run-url", "https://example.invalid/run/9",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Workflow run: https://example.invalid/run/9" in out

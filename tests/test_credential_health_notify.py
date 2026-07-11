"""Unit tests for ``scripts/credential_health_notify.py`` (use case #1)."""

from __future__ import annotations

from typing import Any

from scripts import credential_health_notify as chn
from scripts.composio_ops import DeliveryResult


class _Recorder:
    """Records notify_slack calls and returns a fixed DeliveryResult."""

    def __init__(self, result: DeliveryResult) -> None:
        self.result = result
        self.messages: list[str] = []

    def __call__(self, message: str) -> DeliveryResult:
        self.messages.append(message)
        return self.result


def test_build_message_lists_only_nonok(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "skipp-dev/skipp-algo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    report: dict[str, Any] = {
        "overall_severity": "error",
        "probes": [
            {"name": "github_pat_validity", "severity": "error", "message": "EXPIRED"},
            {"name": "fmp_api_key", "severity": "ok", "message": "fine"},
            {"name": "tv_storage_state_age", "severity": "warn", "message": "aging"},
        ],
    }
    msg = chn.build_message(report)
    assert "github_pat_validity" in msg and "EXPIRED" in msg
    assert "tv_storage_state_age" in msg
    assert "fmp_api_key" not in msg  # ok probes are omitted
    assert "actions/runs/42" in msg


def test_main_skips_on_ok(tmp_path, monkeypatch):
    report = tmp_path / "r.json"
    report.write_text('{"overall_severity":"ok","probes":[]}', encoding="utf-8")
    rec = _Recorder(DeliveryResult(True, False, "ok"))
    monkeypatch.setattr(chn.composio_ops, "notify_slack", rec)
    assert chn.main(["--report", str(report)]) == 0
    assert rec.messages == []


def test_main_sends_on_error(tmp_path, monkeypatch):
    report = tmp_path / "r.json"
    report.write_text(
        '{"overall_severity":"error","probes":[{"name":"x","severity":"error","message":"m"}]}',
        encoding="utf-8",
    )
    rec = _Recorder(DeliveryResult(True, False, "ok"))
    monkeypatch.setattr(chn.composio_ops, "notify_slack", rec)
    assert chn.main(["--report", str(report)]) == 0
    assert rec.messages and "x" in rec.messages[0]


def test_main_exit0_even_when_delivery_fails(tmp_path, monkeypatch):
    report = tmp_path / "r.json"
    report.write_text('{"overall_severity":"error","probes":[]}', encoding="utf-8")
    rec = _Recorder(DeliveryResult(False, False, "boom"))
    monkeypatch.setattr(chn.composio_ops, "notify_slack", rec)
    assert chn.main(["--report", str(report)]) == 0
    assert rec.messages  # attempted


def test_main_missing_report_treated_as_error(tmp_path, monkeypatch):
    rec = _Recorder(DeliveryResult(True, True, "skipped"))
    monkeypatch.setattr(chn.composio_ops, "notify_slack", rec)
    assert chn.main(["--report", str(tmp_path / "nope.json")]) == 0
    assert rec.messages  # missing report => overall 'error' => attempts push

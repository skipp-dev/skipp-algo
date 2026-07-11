"""Unit tests for ``scripts/ops_digest.py`` (use case #4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import ops_digest
from scripts.composio_ops import DeliveryResult


def _write(root: Path, rel: str, obj: Any) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


class _MailRecorder:
    def __init__(self, result: DeliveryResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def __call__(self, to: str, subject: str, html: str) -> DeliveryResult:
        self.calls.append((to, subject))
        return self.result


def test_sweep_trap_below_gate_note(tmp_path):
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"n_samples": 10, "min_samples": 40, "verdict": "INCONCLUSIVE", "brier_delta": 0.0, "lift": 0.0},
    )
    section = ops_digest.collect_sweep_trap(tmp_path)
    assert any("10" in value for _, value in section.rows)
    assert "more samples" in section.note


def test_sweep_trap_promotable_note(tmp_path):
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"n_samples": 50, "min_samples": 40, "verdict": "PROMOTABLE", "verdict_code": 2},
    )
    section = ops_digest.collect_sweep_trap(tmp_path)
    assert "WS4b" in section.note


def test_missing_artifact_is_soft(tmp_path):
    section = ops_digest.collect_sweep_trap(tmp_path)
    assert section.rows == []
    assert section.note


def test_feature_importance_gate_note(tmp_path):
    _write(
        tmp_path,
        "artifacts/open_prep/feature_importance/latest.json",
        {
            "labeled_samples": 38,
            "min_samples_threshold": 200,
            "lookback_days": 30,
            "generated_at_et": "2026-07-10T19:12:41",
            "ranking_drift": {"drifted_features": []},
        },
    )
    section = ops_digest.collect_feature_importance(tmp_path)
    assert "162 more" in section.note
    assert any(label == "Ranking drift" for label, _ in section.rows)


def test_calibration_rows(tmp_path):
    _write(
        tmp_path,
        "docs/calibration/calibration_report_public.json",
        {"status": "ok", "weighted_hit_rate": None, "n_events": None, "family_weights": {}},
    )
    section = ops_digest.collect_calibration(tmp_path)
    labels = [label for label, _ in section.rows]
    assert "Status" in labels and "Weighted hit-rate" in labels


def test_render_html_and_text(tmp_path):
    sections = ops_digest.build_sections(tmp_path)
    html = ops_digest.render_html(sections, generated_at="2026-07-11")
    assert "<h2" in html and "Ops Digest" in html
    text = ops_digest.render_text(sections, generated_at="2026-07-11")
    assert "Ops Digest" in text


def test_main_dry_run_does_not_send(tmp_path, monkeypatch):
    rec = _MailRecorder(DeliveryResult(True, False, "ok"))
    monkeypatch.setattr(ops_digest.composio_ops, "send_outlook_email", rec)
    assert ops_digest.main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert rec.calls == []


def test_main_sends_email(tmp_path, monkeypatch):
    rec = _MailRecorder(DeliveryResult(True, False, "ok"))
    monkeypatch.setattr(ops_digest.composio_ops, "send_outlook_email", rec)
    rc = ops_digest.main(["--root", str(tmp_path), "--to", "ops@example.com"])
    assert rc == 0
    assert rec.calls and rec.calls[0][0] == "ops@example.com"


def test_main_returns_1_on_send_failure(tmp_path, monkeypatch):
    rec = _MailRecorder(DeliveryResult(False, False, "boom"))
    monkeypatch.setattr(ops_digest.composio_ops, "send_outlook_email", rec)
    assert ops_digest.main(["--root", str(tmp_path), "--to", "ops@example.com"]) == 1

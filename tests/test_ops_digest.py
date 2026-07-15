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


def test_sweep_trap_promotable_note_is_candidate_not_green_light(tmp_path):
    # A fresh PROMOTABLE snapshot: a candidate needing review, NOT a green light.
    now = 1_700_000_000.0
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"n_samples": 50, "min_samples": 40, "verdict": "PROMOTABLE", "verdict_code": 2,
         "generated_at": now - 3600},  # 1h old → fresh
    )
    section = ops_digest.collect_sweep_trap(tmp_path, now_ts=now)
    assert "WS4b candidate" in section.note and "review required" in section.note
    assert "green light" not in section.note
    assert any(label == "Snapshot age" for label, _ in section.rows)


def test_sweep_trap_promotable_stale_snapshot_is_flagged(tmp_path):
    now = 1_700_000_000.0
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"n_samples": 50, "min_samples": 40, "verdict": "PROMOTABLE", "verdict_code": 2,
         "generated_at": now - 5 * 86400},  # 5 days old → stale (cron stalled)
    )
    section = ops_digest.collect_sweep_trap(tmp_path, now_ts=now)
    assert "stalled" in section.note
    assert any(label == "Snapshot age" and value.startswith("5.0") for label, value in section.rows)


def test_sweep_trap_promotable_undated_snapshot_notes_unknown_age(tmp_path):
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"n_samples": 50, "min_samples": 40, "verdict": "PROMOTABLE", "verdict_code": 2},
    )
    section = ops_digest.collect_sweep_trap(tmp_path)
    assert "age unknown" in section.note
    assert any(label == "Snapshot age" and value == "n/a" for label, value in section.rows)


def test_sweep_trap_no_data_seed_reports_unknown_age_not_1970(tmp_path):
    # The committed seed carries generated_at=0.0 (#3414). Treating 0 as a real
    # epoch timestamp renders it as a ~20649-day-old snapshot; the publisher and
    # the daemon bridge both gate on generated_at > 0, so this must too.
    now = 1_700_000_000.0
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"generated_at": 0.0, "date": "", "n_samples": 0, "min_samples": 40,
         "brier_delta": 0.0, "lift": 0.0, "verdict": "INCONCLUSIVE", "verdict_code": 0},
    )
    section = ops_digest.collect_sweep_trap(tmp_path, now_ts=now)
    assert any(label == "Snapshot age" and value == "n/a" for label, value in section.rows)
    assert "no-data seed" in section.note


def test_sweep_trap_prefers_published_live_snapshot_over_seed(tmp_path):
    # The daily eval publishes to bot/live-sweep-trap-shadow under
    # artifacts/monitoring/latest/; the seed under artifacts/monitoring/ is never
    # refreshed on main. Reading only the seed reports 0/40 while the study runs.
    now = 1_700_000_000.0
    _write(
        tmp_path,
        "artifacts/monitoring/sweep_trap_shadow.json",
        {"generated_at": 0.0, "n_samples": 0, "min_samples": 40, "verdict": "INCONCLUSIVE"},
    )
    _write(
        tmp_path,
        "artifacts/monitoring/latest/sweep_trap_shadow.json",
        {"generated_at": now - 3600, "date": "2026-07-14", "n_samples": 7481,
         "min_samples": 40, "brier_delta": -0.067751, "lift": 0.377056,
         "verdict": "SHADOW", "verdict_code": 1},
    )
    section = ops_digest.collect_sweep_trap(tmp_path, now_ts=now)
    rows = dict(section.rows)
    assert rows["Samples"] == "7481 / 40 gate"
    assert rows["Verdict"] == "SHADOW"
    assert rows["Source"] == "artifacts/monitoring/latest/sweep_trap_shadow.json"


def test_missing_artifact_is_soft(tmp_path):
    section = ops_digest.collect_sweep_trap(tmp_path)
    assert section.rows == []
    assert section.note


def test_feature_importance_surfaces_era_gate_cascade(tmp_path):
    # labeled=0 with total=350 is a CORRECT cold start, not a stalled pipeline —
    # the digest must say which, or the operator cannot tell. The real cascade
    # (verified 2026-07-15 against the live fi_samples) is
    # 350 -214 zero-vector -> 136 -81 score-formula -> 55 -55 directional -> 0,
    # so the drops must be reported PER GATE, never lumped onto the newest one.
    _write(
        tmp_path,
        "artifacts/open_prep/feature_importance/latest.json",
        {
            "labeled_samples": 0,
            "total_samples": 350,
            "min_samples_threshold": 200,
            "lookback_days": 30,
            "status": "insufficient_labels",
            "era_gated_samples_dropped": 214,
            "formula_era_samples_dropped": 81,
            "directional_era_samples_dropped": 55,
            "generated_at_et": "2026-07-14T18:34:38-04:00",
            "ranking_drift": {"drifted_features": []},
        },
    )
    section = ops_digest.collect_feature_importance(tmp_path)
    rows = dict(section.rows)
    assert rows["Raw samples"] == "350"
    assert rows["Era-gate drops"] == "214 zero-vector, 81 score-formula, 55 directional-label"
    assert "Not a stalled backfill" in section.note
    assert "all 350 in-window sample(s)" in section.note
    assert "the last 55 to the 2026-07-14 directional-label cutover" in section.note


def test_feature_importance_omits_drop_row_when_counters_absent(tmp_path):
    # Pre-fix latest.json (no counters) must degrade quietly, not fabricate a row.
    _write(
        tmp_path,
        "artifacts/open_prep/feature_importance/latest.json",
        {"labeled_samples": 0, "total_samples": 350, "min_samples_threshold": 200},
    )
    section = ops_digest.collect_feature_importance(tmp_path)
    assert "Era-gate drops" not in dict(section.rows)
    assert "Not a stalled backfill" not in section.note


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


def test_main_returns_0_on_send_failure(tmp_path, monkeypatch, capsys):
    # Best-effort ops notification: a Composio send failure must NOT red the cron.
    rec = _MailRecorder(DeliveryResult(False, False, "boom"))
    monkeypatch.setattr(ops_digest.composio_ops, "send_outlook_email", rec)
    assert ops_digest.main(["--root", str(tmp_path), "--to", "ops@example.com"]) == 0
    assert "email FAILED" in capsys.readouterr().err  # surfaced, not swallowed

"""End-to-end pipeline test for the F2 contextual-promotion toolset.

Wires the 5 operator-facing F2 helpers together against synthetic
fixtures so a regression in any one of them fails this test
immediately:

  scripts/f2_append_rollback_history.py   (ring grow on rc=0)
  scripts/f2_render_rollback_issue.py     (Issue title+body on rc=2)
  scripts/f2_revert_contextual_weights.py (auto-revert on rc=2)
  scripts/f2_rotate_rollback_history.py   (manual reset after review)
  scripts/f2_summarize_history.py         (operator-readable digest)

Pure-Python, no I/O outside ``tmp_path``. No dependence on
``run_ab_comparison`` / ``load_benchmark`` (those have their own
unit tests); we feed each helper a hand-crafted promotion-gate
report so the chain stays fast and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_append_rollback_history import append_history
from scripts.f2_inspect_status import build_status
from scripts.f2_render_rollback_issue import ISSUE_LABEL, render_body, render_title
from scripts.f2_revert_contextual_weights import revert_contextual_weights
from scripts.f2_rotate_rollback_history import rotate_history
from scripts.f2_summarize_history import build_summary


def _gate_report(*, decision: str, brier_delta: float) -> dict:
    """Hand-crafted promotion-gate JSON, matching the real schema."""
    return {
        "schema_version": 1,
        "experiment": "f2-contextual-zone-priority-promotion",
        "decision": decision,
        "reason": f"synthetic fixture for e2e test ({decision})",
        "actions": [],
        "sprt": {
            "decision": "continue" if decision != "rollback" else "accept_h0",
            "n": 100, "k": 55, "llr": 0.05,
            "p0": 0.55, "p1": 0.60, "alpha": 0.05, "beta": 0.20,
        },
        "kpi_metrics": [
            {"metric": "calibrated_brier", "control": 0.16,
             "treatment": 0.16 + brier_delta, "delta": brier_delta},
            {"metric": "calibrated_ece", "control": 0.10,
             "treatment": 0.10 + brier_delta, "delta": brier_delta},
            {"metric": "hit_rate_pct", "control": 60.0,
             "treatment": 60.0 - 1.0, "delta": -1.0},
        ],
    }


def test_f2_pipeline_e2e_happy_then_rollback(tmp_path: Path) -> None:
    """Day-by-day walkthrough of two clean days, two worse days, rollback."""
    history_path = tmp_path / "rollback_history.json"
    journal_path = tmp_path / "revert_journal.jsonl"
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    # F2 spec + treatment calibration artifact (status=production).
    artifact_path = tmp_path / "treatment_calibration.json"
    artifact_path.write_text(json.dumps({
        "status": "production",
        "weights": {"OB": 1.0, "FVG": 0.8},
    }), encoding="utf-8")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "schema_version": 1,
        "name": "f2-e2e",
        "arms": {
            "control": {"label": "static"},
            "treatment": {
                "label": "contextual",
                "calibration_artifact": str(artifact_path),
            },
        },
    }), encoding="utf-8")

    # ------------------------------------------------------------------
    # Day 1+2 — green (rc=0). The append helper grows the ring.
    # ------------------------------------------------------------------
    for day, delta in [("2026-04-18", -0.005), ("2026-04-19", -0.003)]:
        report = _gate_report(decision="hold", brier_delta=delta)
        report_path = reports_dir / f"f2_promotion_gate_{day}.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        ring = append_history(report=report, history_path=history_path)
        assert ring[-1] == delta

    # Ring after 2 green days has both negative (better) deltas.
    ring = json.loads(history_path.read_text(encoding="utf-8"))
    assert ring == [-0.005, -0.003]

    # ------------------------------------------------------------------
    # Day 3+4 — worse (rc=0 still, but deltas are positive). The
    # promotion-gate evaluator would flip on Day 4 to decision='rollback'.
    # We simulate that explicitly here and STOP appending (matches the
    # workflow: append step is skipped when rc=2).
    # ------------------------------------------------------------------
    for day, delta in [("2026-04-20", 0.011), ("2026-04-21", 0.018)]:
        report = _gate_report(
            decision="hold" if day == "2026-04-20" else "rollback",
            brier_delta=delta,
        )
        report_path = reports_dir / f"f2_promotion_gate_{day}.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        if report["decision"] == "rollback":
            break  # workflow's append step is gated on rc=0.
        append_history(report=report, history_path=history_path)

    # Ring should now be [-0.005, -0.003, 0.011] (Day 4 not appended).
    ring = json.loads(history_path.read_text(encoding="utf-8"))
    assert ring == [-0.005, -0.003, 0.011]

    # ------------------------------------------------------------------
    # Day 4 — rollback path: render Issue + auto-revert.
    # ------------------------------------------------------------------
    rollback_report_path = reports_dir / "f2_promotion_gate_2026-04-21.json"
    rollback_report = json.loads(rollback_report_path.read_text(encoding="utf-8"))

    title = render_title(rollback_report, date="2026-04-21")
    body = render_body(
        rollback_report,
        date="2026-04-21",
        workflow_run_url="https://example.invalid/run/1",
        report_path=str(rollback_report_path),
    )
    assert title.startswith("[F2 rollback]")
    assert "rollback" in title
    assert ISSUE_LABEL in body
    # Runbook now reflects automatic revert.
    assert "f2_revert_contextual_weights.py" in body or "demoted" in body
    # Manual reset still required after review.
    assert "f2_rotate_rollback_history.py" in body

    # Auto-revert demotes the artifact and writes the journal.
    revert_record = revert_contextual_weights(
        spec_path=spec_path,
        report_path=rollback_report_path,
        journal_path=journal_path,
        timestamp="2026-04-21T10-00-00Z",
    )
    assert revert_record["action"] == "reverted"
    new_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert new_artifact["status"] == "shadow"
    assert len(new_artifact["revert_history"]) == 1

    # ------------------------------------------------------------------
    # Operator review: rotate the ring so Day 5 starts fresh.
    # ------------------------------------------------------------------
    rotate_record = rotate_history(
        history_path=history_path,
        timestamp="2026-04-21T11-00-00Z",
    )
    assert rotate_record["action"] == "rotated"
    assert rotate_record["archived_len"] == 3
    assert rotate_record["new_len"] == 0
    # Live ring is now empty.
    assert json.loads(history_path.read_text(encoding="utf-8")) == []

    # ------------------------------------------------------------------
    # Day 5 — summarize: digest must reflect the rollback run as latest.
    # ------------------------------------------------------------------
    digest = build_summary(
        history_path=history_path,
        reports_dir=reports_dir,
        trend_window=30,
    )
    assert digest["history"]["len"] == 0
    assert digest["latest_report"]["decision"] == "rollback"
    assert digest["latest_report"]["date"] == "2026-04-21"
    assert digest["decisions"]["rollback"] == 1
    assert digest["decisions"]["hold"] == 3
    assert digest["latest_sprt"]["decision"] == "accept_h0"

    # ------------------------------------------------------------------
    # Operator pings the inspector — must reflect: artifact demoted to
    # shadow with one revert_history entry, revert_journal has one
    # 'reverted' line, latest report still the rollback one.
    # ------------------------------------------------------------------
    status = build_status(
        spec_path=spec_path,
        revert_journal=journal_path,
        reports_dir=reports_dir,
    )
    assert status["artifact"]["status"] == "shadow"
    assert status["artifact"]["revert_history_len"] == 1
    assert status["revert_journal"]["len"] == 1
    assert status["revert_journal"]["actions"] == {"reverted": 1}
    assert status["promote_journal"]["len"] == 0
    assert status["latest_report"]["decision"] == "rollback"
    assert status["latest_report"]["date"] == "2026-04-21"


def test_f2_pipeline_e2e_revert_idempotent_on_second_rollback(tmp_path: Path) -> None:
    """Re-running revert on the same rollback report is a clean no-op."""
    artifact_path = tmp_path / "treatment.json"
    artifact_path.write_text(json.dumps({"status": "production"}), encoding="utf-8")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "arms": {"treatment": {"calibration_artifact": str(artifact_path)}},
    }), encoding="utf-8")
    report_path = tmp_path / "r.json"
    report_path.write_text(json.dumps(_gate_report(
        decision="rollback", brier_delta=0.02,
    )), encoding="utf-8")
    journal = tmp_path / "j.jsonl"

    rec1 = revert_contextual_weights(
        spec_path=spec_path, report_path=report_path,
        journal_path=journal, timestamp="2026-04-21T10-00-00Z",
    )
    rec2 = revert_contextual_weights(
        spec_path=spec_path, report_path=report_path,
        journal_path=journal, timestamp="2026-04-21T11-00-00Z",
    )
    assert rec1["action"] == "reverted"
    assert rec2["action"] == "noop_already_shadow"
    # Both runs journaled.
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    actions = [json.loads(l)["action"] for l in lines]
    assert actions == ["reverted", "noop_already_shadow"]

"""Tests for the WS4-01 backfill automation hardening."""
from __future__ import annotations

import json
from pathlib import Path

import open_prep.outcome_backfill as ob

# ── Run-log persistence ───────────────────────────────────────────────


class TestRunLog:
    def test_writes_run_log_with_status_ok(self, tmp_path: Path) -> None:
        log_path = ob._write_backfill_run_log(
            summary={"resolved": 7, "skipped": 1, "failed": 0, "dates_processed": 2},
            feature_importance_samples=5,
            cli_args={"date": None, "lookback": 5, "dataset": "X", "feature_importance": True},
            log_dir=tmp_path,
        )
        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["resolved"] == 7
        assert record["skipped"] == 1
        assert record["failed"] == 0
        assert record["dates_processed"] == 2
        assert record["status"] == "ok"
        assert record["feature_importance_samples"] == 5
        assert record["cli_args"]["lookback"] == 5

        # Latest pointer mirrors the same payload.
        latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
        assert latest == record

    def test_writes_run_log_with_status_failed(self, tmp_path: Path) -> None:
        log_path = ob._write_backfill_run_log(
            summary={"resolved": 0, "skipped": 0, "failed": 3, "dates_processed": 1},
            feature_importance_samples=None,
            cli_args={"date": "2026-04-20", "lookback": 1, "dataset": "X", "feature_importance": False},
            log_dir=tmp_path,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["status"] == "failed"
        assert record["failed"] == 3
        assert record["feature_importance_samples"] is None

    def test_writes_run_log_with_status_deferred(self, tmp_path: Path) -> None:
        # Bars not yet published upstream: deferred-only runs are not
        # failures, but the run log still distinguishes them from "ok".
        log_path = ob._write_backfill_run_log(
            summary={
                "resolved": 0, "skipped": 17, "failed": 0, "deferred": 13,
                "dates_processed": 3,
            },
            feature_importance_samples=None,
            cli_args={"date": None, "lookback": 5, "dataset": "X", "feature_importance": False},
            log_dir=tmp_path,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["status"] == "deferred"
        assert record["deferred"] == 13
        assert record["failed"] == 0

    def test_run_log_failed_status_wins_over_deferred(self, tmp_path: Path) -> None:
        log_path = ob._write_backfill_run_log(
            summary={
                "resolved": 0, "skipped": 0, "failed": 2, "deferred": 3,
                "dates_processed": 1,
            },
            feature_importance_samples=None,
            cli_args={"date": None, "lookback": 5, "dataset": "X", "feature_importance": False},
            log_dir=tmp_path,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["status"] == "failed"

    def test_atomic_write_replaces_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "x.json"
        ob._atomic_write_json(target, {"a": 1})
        ob._atomic_write_json(target, {"a": 2})
        assert json.loads(target.read_text(encoding="utf-8"))["a"] == 2


# ── Main exit-code propagation ────────────────────────────────────────


class TestMainExitCode:
    def _patch_backfill(self, monkeypatch, summary):
        monkeypatch.setattr(ob, "backfill_outcomes", lambda **kwargs: summary)
        monkeypatch.setattr(ob, "backfill_feature_importance", lambda **kwargs: 0)

    def test_exit_zero_on_clean_run(self, monkeypatch, tmp_path: Path) -> None:
        self._patch_backfill(monkeypatch, {"resolved": 3, "skipped": 0, "failed": 0, "dates_processed": 1})
        monkeypatch.setattr(ob, "BACKFILL_RUN_LOG_DIR", tmp_path)
        rc = ob.main(["--lookback", "1"])
        assert rc == 0
        assert (tmp_path / "latest.json").exists()

    def test_exit_two_on_failed_records(self, monkeypatch, tmp_path: Path) -> None:
        self._patch_backfill(monkeypatch, {"resolved": 0, "skipped": 0, "failed": 1, "dates_processed": 1})
        monkeypatch.setattr(ob, "BACKFILL_RUN_LOG_DIR", tmp_path)
        rc = ob.main(["--lookback", "1"])
        assert rc == 2

    def test_dry_run_skips_log_persistence(self, monkeypatch, tmp_path: Path) -> None:
        self._patch_backfill(monkeypatch, {"resolved": 1, "skipped": 0, "failed": 0, "dates_processed": 1})
        monkeypatch.setattr(ob, "BACKFILL_RUN_LOG_DIR", tmp_path)
        rc = ob.main(["--lookback", "1", "--dry-run"])
        assert rc == 0
        assert not (tmp_path / "latest.json").exists()


# ── Workflow contract ────────────────────────────────────────────────


_WORKFLOW = Path(".github/workflows/open-prep-outcome-backfill.yml")


class TestWorkflow:
    def test_workflow_file_exists(self) -> None:
        assert _WORKFLOW.exists()

    def test_workflow_runs_on_schedule(self) -> None:
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert "schedule:" in text
        assert "cron:" in text

    def test_workflow_invokes_backfill_module(self) -> None:
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert "python -m open_prep.outcome_backfill" in text

    def test_workflow_uploads_run_log_artifact(self) -> None:
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert "actions/upload-artifact" in text
        assert "artifacts/open_prep/outcome_backfill/" in text

    def test_workflow_uses_set_minus_e(self) -> None:
        # 'set -euo pipefail' makes the run step fail loudly on errors
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text

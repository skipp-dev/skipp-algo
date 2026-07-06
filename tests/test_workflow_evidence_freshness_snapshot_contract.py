"""Contract pin: ``evidence-freshness-snapshot`` workflow (2026-07-06).

Pins the daily schedule, the mutating-on-cron posture, the producer
entrypoint, and the rolling bot-branch publish so silent drift of the
evidence-freshness monitoring producer is caught at validate-time. This file
also satisfies ``test_workflow_orphan_inventory`` by referencing the workflow
stem ``evidence-freshness-snapshot``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "evidence-freshness-snapshot.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["snapshot"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[1]
    assert "live-window: mutating-on-cron" in head, (
        "second-line live-window marker required — mutating-on-cron because "
        "the workflow publishes the snapshot branch"
    )


def test_schedule_is_daily() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["0 5 * * *"], crons
    assert "workflow_dispatch" in on_block


def test_permissions_declare_write() -> None:
    assert _load()["permissions"] == {"contents": "write"}


def test_concurrency_does_not_cancel() -> None:
    assert _load()["concurrency"]["cancel-in-progress"] is False


def test_job_has_timeout_and_unbuffered() -> None:
    data = _load()
    assert 0 < int(data["jobs"]["snapshot"]["timeout-minutes"]) <= 360
    assert data["env"]["PYTHONUNBUFFERED"] == "1"


def test_runs_the_producer_module() -> None:
    body = " ".join(step.get("run", "") for step in _steps())
    assert "scripts.build_evidence_freshness_snapshot" in body
    assert "--audit-branch origin/data/phase-a-audit" in body


def test_publishes_to_rolling_bot_branch() -> None:
    body = " ".join(step.get("run", "") for step in _steps())
    assert "bot/live-evidence-freshness" in body, (
        "the snapshot must publish to the rolling bot branch the daemon reads "
        "via EVIDENCE_FRESHNESS_SNAPSHOT_URL"
    )
    # Publish must be fail-soft on a missing PAT (best-effort, never red).
    assert "GH_PAT not configured" in body


def test_audit_branch_fetch_is_fail_soft() -> None:
    """A missing data/phase-a-audit must degrade to empty audit/fills fields,
    never abort the snapshot (the ledger signal is still worth publishing)."""
    fetch_step = next(
        s for s in _steps() if "fetch" in s.get("name", "").lower()
    )
    assert "|| echo" in fetch_step["run"]

"""Contract pin: ``phase-b-promotion-readiness.yml`` (Bundle D-2 / issue #2422).

This is a manual / callable gate that blocks Phase-B promotion until a
backtest slippage sample exists (rather than the ``synthetic_normal``
fallback). The Deep-Review 2026-04-27 follow-up was created precisely
because no CI gate verified this — pin the script entrypoint and the
manual-only trigger surface so the gap cannot silently re-open.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "phase-b-promotion-readiness.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    return data.get("on") or data.get(True)


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_manual_only() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: manual-only" in head, (
        "first-line live-window marker required by F-V6-F2.1"
    )


def test_triggers_are_dispatch_and_call_no_schedule() -> None:
    """No schedule by design — readiness is asserted on demand pre-promotion."""
    on_block = _on(_load())
    assert set(on_block.keys()) == {"workflow_dispatch", "workflow_call"}, (
        "phase-b readiness must remain manual / callable only; adding schedule "
        "would create misleading green runs on every cron tick"
    )
    assert "schedule" not in on_block


def test_drift_glob_input_default_pinned() -> None:
    on_block = _on(_load())
    expected_default = "artifacts/drift/drift_report_*.json"
    for trigger in ("workflow_dispatch", "workflow_call"):
        inputs = on_block[trigger]["inputs"]
        assert inputs["drift_glob"]["default"] == expected_default, (
            f"{trigger}.inputs.drift_glob default drifted; downstream callers "
            "rely on this glob to find the live-drift report"
        )


def test_single_readiness_job() -> None:
    jobs = _load()["jobs"]
    assert list(jobs.keys()) == ["check-readiness"]
    job = jobs["check-readiness"]
    assert job["timeout-minutes"] == 5
    assert "SMC_GH_HOSTED_RUNNER" in job["runs-on"]


def test_invokes_check_phase_b_drift_readiness_script() -> None:
    body = "\n".join(
        s.get("run", "") for s in _load()["jobs"]["check-readiness"]["steps"]
    )
    assert "scripts.check_phase_b_drift_readiness" in body, (
        "entrypoint renamed; the gap from Deep-Review 2026-04-27 would silently "
        "re-open (Phase-B promotable on synthetic_normal slippage again)"
    )


def test_permissions_minimal_read_only() -> None:
    perms = _load()["permissions"]
    assert perms == {"contents": "read"}, (
        "readiness gate must remain read-only; it reports, never mutates"
    )

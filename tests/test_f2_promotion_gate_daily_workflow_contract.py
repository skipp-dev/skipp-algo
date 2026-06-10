"""Contract pin: ``f2-promotion-gate-daily.yml`` (Bundle D-3 / issue #2422).

Closes the last gap from issue #2422 finding D: ``f2-promotion-gate-daily``
had no dedicated structural test. The workflow has unusually intricate
fail-soft semantics:

  * rc=0 promote/hold/insufficient_data => CI green
  * rc=2 rollback                       => CI red (issue-ping rule G2)
  * rc=1 config error                   => CI red (real bug)
  * unknown rc                          => ::error:: + treat as rc=1

Plus L-2 fail-soft on missing dual-arm artefacts (skip+warning), plus
auto-revert + streak-alert on rc=2 (must surface ::error:: on crash —
Bundle A hardening 2026-05-28, PR #2426).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "f2-promotion-gate-daily.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    return data.get("on") or data.get(True)


def _steps_by_id(data: dict) -> dict[str, dict]:
    return {s["id"]: s for s in data["jobs"]["promotion-gate"]["steps"] if "id" in s}


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "f2-promotion-gate-daily writes journals + may auto-revert; must "
        "declare mutating-on-cron (F-V6-F2.1)"
    )


def test_cron_runs_after_databento_producer_mon_fri() -> None:
    """14:30 UTC Mon-Fri — must run AFTER smc-measurement-benchmark-rolling
    (13:00 UTC Mon-Fri) so the dual-arm artefact is published before the
    promotion gate downloads it. Mon-Fri matches the upstream Databento
    producer's cadence (12:00 UTC Mon-Fri). Pre-#2447 layout (`0 10 * * *`)
    fired BEFORE the producer every day and aborted every run on the
    missing-artefact guard. The producer\u2192consumer ordering invariant is
    enforced by tests/test_workflow_databento_consumer_cron_ordering.py.
    """
    crons = [e["cron"] for e in _on(_load())["schedule"]]
    assert crons == ["30 14 * * 1-5"], (
        f"f2 gate cron drifted to {crons}; must remain '30 14 * * 1-5' so the "
        "dual-arm artefact from rolling-bench (13:00 UTC Mon-Fri) is in place "
        "and weekend ticks (when the producer doesn't run) are skipped"
    )


def test_permissions_include_issues_write_for_g2_rule() -> None:
    perms = _load()["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("issues") == "write", (
        "issues:write required by plan §2.4 G2 GitHub-Issue-Ping rule "
        "(rollback rc=2 must file an issue)"
    )
    assert perms.get("actions") == "read", (
        "actions:read required for `gh run list/download` against rolling-bench"
    )


def test_concurrency_does_not_cancel() -> None:
    """Mid-flight cancellation could leave rollback journal half-written."""
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "f2-promotion-gate-daily"
    assert concurrency["cancel-in-progress"] is False


def test_gate_step_three_tier_rc_policy() -> None:
    gate = _steps_by_id(_load())["gate"]
    body = gate["run"]
    # rc 0 + 2 must propagate; only unknown rc folds to ::error::
    assert 'rc}" -eq 0 ] || [ "${rc}" -eq 2' in body, (
        "rc=0/2 propagation policy drifted; rollback signal (rc=2) MUST stay CI red"
    )
    assert "::error::" in body, (
        "unknown-rc must surface ::error:: (F-V4-A4 2026-05-01); otherwise a "
        "future return code shift would silently degrade to skip"
    )


def test_l2_warning_on_dual_arm_skip() -> None:
    """L-2 audit fix (2026-04-24): per-run ::warning:: instead of ::notice::."""
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "::warning title=f2-promotion-gate-daily::status=skipped" in text, (
        "L-2 warning surface removed; consecutive skipped runs will no longer "
        "show in the run-summary banner ('stuck on skipped for weeks' regression)"
    )
    assert "audit L-2" in text, "rationale tag must remain in workflow"


# NOTE: Bundle A surface pins (auto-revert + streak-alert ::error::) are
# intentionally deferred until PR #2426 merges. After it lands, append two
# tests here asserting the presence of:
#   '::error title=f2-promotion-gate::auto-revert FAILED'
#   '::error title=f2-promotion-gate::f2_status_alert.py CRASHED'


def test_flip_detection_cache_key_versioned() -> None:
    """#45 fix: spec-status flip detection requires cross-run cache."""
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "f2-last-spec-status-v1-" in text, (
        "cache key versioning lost; #45 SPRT-reset on plumbing_only->live "
        "transition will silently break"
    )


def test_flip_detection_cache_uses_explicit_save_before_gate() -> None:
    """2026-06-10 audit: unified actions/cache never persisted the status.

    The unified action saves in an implicit POST step that is skipped
    when the job fails — and this job exits 2 by design on every
    rollback decision, so five consecutive rollback runs persisted
    nothing (`gh cache list` was empty; every run logged "Cache not
    found"). The workflow must use explicit cache/restore + cache/save,
    with the save placed BEFORE the gate step can fail.
    """
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "actions/cache/restore@" in text, (
        "flip-detection must use explicit actions/cache/restore (the "
        "unified action's post-step save is skipped on rollback-failed runs)"
    )
    assert "actions/cache/save@" in text, (
        "flip-detection must use explicit actions/cache/save"
    )
    save_pos = text.find("actions/cache/save@")
    gate_pos = text.find("python scripts/f2_run_promotion_gate.py")
    assert gate_pos != -1, (
        "gate step invocation 'python scripts/f2_run_promotion_gate.py' "
        "not found in workflow"
    )
    assert save_pos < gate_pos, (
        "cache/save must run BEFORE the gate step; the gate exits 2 on "
        "rollback and any save placed after it would be skipped again"
    )


def test_h7_artifact_iteration_pattern() -> None:
    """Audit H7: must iterate recent rolling-bench runs, not assume newest."""
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "gh run list" in text and "smc-measurement-benchmark-rolling" in text

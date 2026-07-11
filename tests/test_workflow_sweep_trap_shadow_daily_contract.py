"""Contract pin: ``sweep-trap-shadow-daily`` workflow (WS4a shadow eval).

Pins the cron schedule, mutating-on-cron live-window marker, write permissions
(for the ledger commit-back), and the script entrypoint so silent drift of the
daily sweep-trap-shadow scheduler is caught at validate-time. Also satisfies
``test_workflow_orphan_inventory`` by referencing the workflow stem
``sweep-trap-shadow-daily``.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "sweep-trap-shadow-daily.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "mutating-on-cron because the workflow commits the shadow ledger back"
    )


def test_schedule_is_weekday_1500_utc() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)  # PyYAML parses bare ``on`` as True
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert "0 15 * * 1-5" in crons, "daily weekday 15:00 UTC schedule required"
    assert "workflow_dispatch" in on_block, "must allow manual operator runs"


def test_permissions_allow_ledger_commit_back() -> None:
    perms = _load()["permissions"]
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"


def test_entrypoint_is_the_shadow_eval() -> None:
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "python scripts/eval_sweep_trap_shadow.py" in text
    # observe-only: it must NOT flip any score/weight flag on.
    assert "ENABLE_CONFLUENCE_SCORE" not in text


def test_eval_rc_capture_is_fail_soft_under_dash_e() -> None:
    """The eval exit code is the SIGNAL (0/2/3/5), not a failure. GitHub runs
    the step under `bash -e`, so the eval call must be wrapped in `set +e` and
    its rc read via PIPESTATUS — otherwise a no_data/shadow/stale run aborts the
    step before the status mapping and the fail-soft design inverts (regression
    guard for the 2026-07-11 smoke-test finding)."""
    steps = _load()["jobs"]["sweep-trap-shadow"]["steps"]
    eval_step = next(s for s in steps if s.get("id") == "eval")
    body = eval_step["run"]
    call_at = body.index("python scripts/eval_sweep_trap_shadow.py")
    disable_at = body.rfind("set +e", 0, call_at)
    assert disable_at != -1, "eval call must be preceded by `set +e` so rc 2/3/5 don't abort the step"
    assert 'rc="${PIPESTATUS[0]}"' in body, "must capture the eval rc via PIPESTATUS, not the pipeline status"
    # -e restored before the git-touching work that follows.
    assert body.index("set -e", call_at) != -1, "restore `set -e` after capturing rc"


def test_commit_back_is_pr_flow_not_direct_push() -> None:
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "gh pr create" in text and "gh pr merge" in text, (
        "the main-governance ruleset rejects direct pushes; use the bot-branch PR flow"
    )
    assert "git diff --quiet artifacts/governance/sweep_trap_shadow.jsonl" in text, (
        "no-op guard: skip commit-back when the ledger is unchanged"
    )


def test_concurrency_serialized() -> None:
    conc = _load()["concurrency"]
    assert conc.get("group") and conc.get("cancel-in-progress") is False

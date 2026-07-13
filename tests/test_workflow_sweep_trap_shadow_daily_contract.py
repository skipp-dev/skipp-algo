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
    assert "git status --porcelain" in text, (
        "no-op guard: skip commit-back when the ledger is absent or unchanged"
    )


def test_concurrency_serialized() -> None:
    conc = _load()["concurrency"]
    assert conc.get("group") and conc.get("cancel-in-progress") is False


def test_commit_back_includes_measured_but_thin_runs() -> None:
    """rc 3 conflates 'measured, n<MIN_OOS (ledger row written)' with 'zero
    samples (nothing written)'. The commit-back gate must include
    thin_or_no_data or every measured-but-thin day is silently discarded (the
    diff-quiet guard no-ops the zero-sample case)."""
    text = _WF_PATH.read_text(encoding="utf-8")
    commit_step = text.split("Commit shadow ledger back via PR", 1)[1]
    gate = commit_step.split("env:", 1)[0]
    assert "steps.eval.outputs.status == 'thin_or_no_data'" in gate
    assert "git status --porcelain" in commit_step


def test_reaction_zone_eval_is_piggybacked_on_the_same_corpus() -> None:
    """F9 wire: the reaction-zone shadow evaluator runs against the identical
    rolling-bench corpus and its snapshot ships with the publish step."""
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "scripts/eval_reaction_zone_shadow.py --benchmark-dir" in text
    assert "artifacts/monitoring/reaction_zone_shadow.json" in text
    publish_step = text.split("Publish snapshot to rolling bot branch", 1)[1]
    assert 'reaction_zone_shadow.json"' in publish_step


def test_rolling_benchmark_arms_both_study_flags() -> None:
    """The producer flags live in the rolling benchmark env block; a flag that
    exists in code but is never threaded through any workflow env is dark by
    construction (that was the reaction study's state)."""
    rolling = _WF_PATH.parent / "smc-measurement-benchmark-rolling.yml"
    text = rolling.read_text(encoding="utf-8")
    assert "ENABLE_SWEEP_TRAP: ${{ vars.ENABLE_SWEEP_TRAP }}" in text
    assert "ENABLE_REACTION_ZONE_STUDY: ${{ vars.ENABLE_REACTION_ZONE_STUDY }}" in text


def test_corpus_resolver_iterates_multiple_runs_not_just_the_latest() -> None:
    """The rolling-benchmark's heavy job is guard-skipped on most workflow_run
    triggers (only select-runner runs → 0 artifacts), so --limit 1 usually
    downloads an empty artifact set → no_data every such day, starving the
    shadow ledger. The resolver must scan several recent successful runs and
    pick the first that actually contains events_*.jsonl."""
    text = _WF_PATH.read_text(encoding="utf-8")
    corpus_step = text.split("Resolve corpus directory", 1)[1].split("Run sweep-trap shadow eval", 1)[0]
    # Must NOT take a single run blindly.
    assert "--limit=1 " not in corpus_step and "--limit 1 " not in corpus_step
    # Must iterate a batch of recent successes and test each for the corpus.
    assert "--limit=15" in corpus_step
    assert "for run_id in" in corpus_step
    assert 'name "events_*.jsonl"' in corpus_step


def test_corpus_dir_is_three_dirnames_up_from_events_file() -> None:
    """The eval globs benchmark_dir/SYMBOL/TF/events_*.jsonl, so benchmark_dir is
    THREE dirnames up from the events file. A two-dirname form points at the
    SYMBOL dir (gh run download without --name nests under the artifact name),
    so the eval matches nothing → no_data with a real corpus present."""
    text = _WF_PATH.read_text(encoding="utf-8")
    corpus_step = text.split("Resolve corpus directory", 1)[1].split("Run sweep-trap shadow eval", 1)[0]
    assert 'dirname "$(dirname "$(dirname "${found}")")"' in corpus_step


def test_commit_back_guard_survives_untracked_and_absent_ledger() -> None:
    """The ledger is UNTRACKED on a fresh checkout (it accumulates only via bot
    PRs). ``git diff --quiet`` fatals on an absent path and returns 0 for an
    untracked-but-present file, so the commit-back must use an existence check +
    ``git status --porcelain`` instead."""
    text = _WF_PATH.read_text(encoding="utf-8")
    commit_step = text.split("Commit shadow ledger back via PR", 1)[1]
    assert "git diff --quiet artifacts/governance/sweep_trap_shadow.jsonl" not in commit_step
    assert 'if [ ! -f "${LEDGER}" ]' in commit_step
    assert "git status --porcelain" in commit_step

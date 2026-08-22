"""Fail-closed contract for the post-mutation re-verification chain.

Operator decision 2026-08-01: the operator's full browser is the normal
production writer on the TradingView account and automation is the guest
(#4316). An autosave from a tab still holding pre-mutation state can silently
overwrite a mutating run's result; before this workflow, the first automated
look was the 05:17Z cron — up to a day later, and run 30700389375's 67-minute
broken layout is what that gap costs in practice.

The pins below hold the two properties that make the chain safe rather than
merely present: the 15-minute wait must not hold the shared TradingView
session group, and the trigger loop must terminate by measurement (the
completed run's published snapshot) rather than by event-name convention.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "tv-post-mutation-verify.yml"


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["reverify"]["steps"]


def test_triggers_on_every_completed_save_run_and_only_there() -> None:
    trigger = (_load().get("on") or _load().get(True))["workflow_run"]
    assert trigger["workflows"] == ["tv-save-consumer-source"]
    assert trigger["types"] == ["completed"]


def test_skipped_runs_exit_and_failed_runs_never_do() -> None:
    """The job gate excludes exactly ONE conclusion, and it is not failure.

    Until 2026-08-03 this file pinned the ABSENCE of any job-level ``if``,
    because run 30700389375 FAILED and had mutated — a failure filter would
    have skipped the one case that mattered. That half still holds and is
    pinned below.

    What changed: three red library-refresh crons on 2026-08-03 produced four
    fail-closed re-verifies whose only finding was that nothing had been
    mutated — a SKIPPED save is the save job's own gate declining to start,
    GitHub's run state rather than anyone's claim, so there is nothing to
    look at. Operator decision 2026-08-03: skipped exits.
    """
    condition = " ".join(_load()["jobs"]["reverify"]["if"].split())

    assert "github.event.workflow_run.conclusion != 'skipped'" in condition
    # The 2026-08-01 rationale survives the 2026-08-03 change: no outcome that
    # ever opened a browser may be filtered here. A failed, cancelled or
    # timed-out run may have mutated before dying; they keep the +15min look.
    for still_fail_closed in ("failure", "cancelled", "timed_out", "success"):
        assert still_fail_closed not in condition, (
            f"the job gate must never filter '{still_fail_closed}' — "
            "run 30700389375 failed AND had mutated"
        )


def test_the_wait_happens_outside_the_shared_session_group() -> None:
    """A sleep inside tradingview-session would block the single account.

    Fifteen idle minutes per mutation, serialised against every publish and
    every readback — the wait must queue nothing. Only the dispatched verify
    run joins the session group, and only when it starts.
    """
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "tv-post-mutation-verify"
    assert concurrency["group"] != "tradingview-session"
    # A verify-triggered instance exits in seconds at the loop guard, and
    # cancelling a sleeping instance on an unrelated verify completion would
    # silently drop a pending re-verify.
    assert concurrency["cancel-in-progress"] is False
    # ...and cancel-in-progress alone never delivered that: under the default
    # `queue: single` a newer entrant cancels the one pending run regardless.
    assert concurrency["queue"] == "max"


def test_the_loop_terminates_by_measurement_not_convention() -> None:
    """The dispatched verify run re-triggers this workflow; the chain must end.

    The gate reads executionMode from the completed run's published snapshot.
    Every mutating outcome — including a missing artifact, which means the run
    died before proving it did not write — falls through to the re-verify.
    """
    steps = {step["name"]: step for step in _steps()}
    mode_step = steps["Read the completed run's execution mode from its snapshot"]
    assert "tradingview-consumer-bindings" in mode_step["run"]
    assert '.executionMode // "unknown"' in mode_step["run"]
    # Fail closed: no artifact -> mode stays "unknown" -> re-verify runs.
    assert 'mode="unknown"' in mode_step["run"]

    for name in (
        "Wait 15 minutes before re-reading the mutated surface",
        "Dispatch the read-only verification",
    ):
        assert steps[name]["if"] == (
            "${{ steps.mode.outputs.mode != 'verify-only' "
            "&& steps.mode.outputs.mode != 'never-ran' }}"
        )

    # Order: gate before sleep before dispatch — a dispatch ahead of the gate
    # would loop, a sleep ahead of the gate would waste 15 runner-minutes on
    # every verify completion.
    names = [step["name"] for step in _steps()]
    assert (
        names.index("Stop when the completed run provably did not mutate")
        < names.index("Wait 15 minutes before re-reading the mutated surface")
        < names.index("Dispatch the read-only verification")
    )


def test_a_save_job_that_never_ran_exits_without_the_fifteen_minute_look() -> None:
    """A trigger run whose save job never ran must not earn a re-verify.

    Decided 2026-08-22. Since #4998 split tv-save-consumer-source into a
    supersession-gate job plus the save job, a superseded (or
    failed-refresh-guard) run completes as SUCCESS with a SKIPPED save job —
    the 2026-08-03 skipped exit at the job gate never sees it — and a run
    cancelled while still queued completes with no jobs at all. Both have no
    snapshot, so before this probe each one earned a fail-closed verify-only
    dispatch. Measured 2026-08-22: 11 queued saves cancelled at 09:40Z
    produced one dispatch every ~15 min into the starved session queue.

    The probe reads GitHub's job record — the only artifact-free proof that
    no browser was opened — and must itself fail closed: on a probe error the
    mode stays "unknown" and the re-verify still runs.
    """
    steps = {step["name"]: step for step in _steps()}
    run = steps["Read the completed run's execution mode from its snapshot"]["run"]
    # The probe reads the trigger run's job list, not the event payload…
    assert "/jobs?per_page=100" in run
    # …counts only save jobs that actually ran. Skipped jobs DO carry a
    # started_at timestamp (measured: run 32467080904), so the filter must be
    # by conclusion, never by started_at.
    assert 'select(.name == "save")' in run
    assert 'select(.conclusion != "skipped")' in run
    # Only an exact count of 0 flips the mode; a probe error must not.
    assert '"${save_ran}" = "0"' in run
    assert "|| echo probe-error" in run
    assert 'mode="never-ran"' in run


def test_the_dispatch_is_read_only_and_targets_the_save_workflow() -> None:
    dispatch = next(s for s in _steps() if s["name"] == "Dispatch the read-only verification")
    assert "tv-save-consumer-source.yml/dispatches" in dispatch["run"]
    assert '"inputs":{"verify_only":"true"}' in dispatch["run"]
    # The re-verify must never itself mutate: verify_only is the ONLY input.
    assert "force_rebind" not in dispatch["run"]
    assert "r1_rollback_drill" not in dispatch["run"]

    sleep = next(s for s in _steps() if s["name"].startswith("Wait 15 minutes"))
    assert sleep["run"].strip() == "sleep 900"

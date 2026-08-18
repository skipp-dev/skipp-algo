"""What ``c13-daily-cron.yml``'s advisory chain decides, executed.

Six steps hand each other a single number. ``rc`` decides whether the next step
runs at all (``steps.<prev>.outputs.rc == '0'``) and whether the run opens an
issue at the end. ``tests/test_c13_daily_cron_backfill_step.py`` executes step
1; steps 2-5b were still measured only as source text.

Measured 2026-08-04, one mutation per step, each against a green unmutated
baseline of the FULL suite (24708 passed):

===================  ===========================================  =============
step                 mutation                                     suite verdict
===================  ===========================================  =============
``drift_input``      ``rc=$?`` -> ``rc=0``                        24708 green
``drift``            ``rc=$?`` -> ``rc=0``                        24708 green
``emit_public``      ``rc=$?`` -> ``rc=0``                        24708 green
``backtest_ref``     soft-skip ``rc=78`` -> ``rc=0``              24708 green
``families``         soft-skip ``rc=78`` -> ``rc=0``              24708 green
===================  ===========================================  =============

So every one of them could publish a constant forever and nothing would go
red -- while a failed step that reports ``rc=0`` lets the whole chain run on an
artefact that was never written, and silences the issue that exists to say so.

These mutations are NOT value-preserving (``$?`` has no second literal arm to
swap with), so they prove less than the arm swaps used elsewhere: a whole-line
source pin would also catch them. None existed.

Two blind spots per step, and both are closed here: running the ``run:`` block
does not check the ``if:``, so the published ``rc`` is fed back through
``evaluate_condition`` against the workflow's real conditions.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "c13-daily-cron.yml"
DATE = "2026-08-04"

DRIFT_INPUT = "Step 2 — drift-input from audit JSONL (advisory)"
BACKTEST_REF = "Step 3 — refresh backtest reference (advisory)"
DRIFT = "Step 4 — compute live drift (advisory)"
FAMILIES = "Step 5a — build families telemetry (advisory)"
EMIT_PUBLIC = "Step 5b — emit public calibration report (advisory)"

# The soft-skip sentinel. The issue-opening condition excludes it explicitly
# (`rc != '0' && rc != '78'`), which is what makes it different from a failure
# and what makes turning it into `0` invisible in the alert.
SOFT_SKIP = "78"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="daily-pipeline",
)
_ISSUE_STEP = "Open issue if any required step failed"


def _python(rc: int = 0) -> Stub:
    """Stand in for every ``python -m scripts.…`` the chain invokes."""
    return Stub(exit_code=rc)


def _run(step: str, tmp_path: Path, *, expressions=None, env=None, rc: int = 0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "calibration").mkdir(parents=True, exist_ok=True)
    return run_step(
        WORKFLOW, step, tmp_path,
        env={"LIVE_DIR": "cache/live", "CALIB_DIR": "cache/calibration",
             "REAL_PYTHON": sys.executable, **(env or {})},
        stubs={"python": _python(rc)},
        expressions={"steps.date.outputs.date": DATE, **(expressions or {})},
    )


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    """Pinning only the harness would let the workflow's own shell drift."""
    assert declares_bash_default(WORKFLOW)


# --------------------------------------------------------------------------
# Step 1b — backfill_progress: a stalled backfill is an alert, not a banner
# --------------------------------------------------------------------------

BACKFILL_PROGRESS = "Step 1b — assert backfill made progress (advisory)"


def _progress(
    tmp_path: Path,
    *,
    backfilled: int,
    pending: int,
    audit_only: int,
    submit_failed: int = 0,
):
    """Run step 1b with both of its external readers stubbed.

    ``grep`` supplies the summary line the backfill printed and ``jq`` answers
    the field reads. Stubbing both keeps the test off the fixed
    ``/tmp/backfill_live_outcomes.stdout`` path, which parallel workers share.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    jq = Stub(script=(
        'case "$2" in\n'
        f"  *records_backfilled*) echo {backfilled} ;;\n"
        f"  *records_pending_close*) echo {pending} ;;\n"
        f"  *records_audit_only*) echo {audit_only} ;;\n"
        f"  *records_submit_failed*) echo {submit_failed} ;;\n"
        "  *) echo 0 ;;\n"
        "esac"
    ))
    return run_step(
        WORKFLOW, BACKFILL_PROGRESS, tmp_path,
        env={"REAL_PYTHON": sys.executable},
        stubs={"grep": Stub(stdout='{"backfill": {}}'), "jq": jq},
        expressions={"steps.date.outputs.date": DATE},
    )


def test_a_stalled_backfill_publishes_a_failing_rc_and_opens_the_issue(
    tmp_path: Path,
) -> None:
    """F-V3-15 phase 2 (2026-08-07 audit).

    For 98 days this printed a ``::warning::`` and published nothing, in a job
    that stays green either way — so a quota/auth/input-path regression on the
    outcome-close path was invisible. The alert is the issue, and the issue
    only fires on a published ``rc``.
    """
    result = _progress(tmp_path, backfilled=0, pending=5, audit_only=1)
    assert result.outputs["rc"] == "1", result.outputs
    assert result.returncode != 0, "the step itself must fail, not just narrate"
    assert evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"backfill.rc": "0", "backfill_progress.rc": "1"}
    ), "a stalled backfill must open the issue"


def test_a_progressing_backfill_stays_quiet(tmp_path: Path) -> None:
    """The control direction: real progress must not alert."""
    result = _progress(tmp_path, backfilled=3, pending=5, audit_only=1)
    assert result.outputs["rc"] == "0"
    assert result.returncode == 0
    assert not evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"backfill.rc": "0", "backfill_progress.rc": "0"}
    )


def test_an_audit_only_day_is_not_a_backfill_regression(tmp_path: Path) -> None:
    """audit_only intents never reached a broker (C13 T1 NO-GO) and can never
    close. Counting them as closable would alert every single paper day."""
    result = _progress(tmp_path, backfilled=0, pending=2, audit_only=2)
    assert result.outputs["rc"] == "0", result.outputs
    assert not evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"backfill.rc": "0", "backfill_progress.rc": "0"}
    )


def test_submit_failed_day_is_not_a_backfill_regression(tmp_path: Path) -> None:
    """Issue #4538: failed submissions are terminal and can never close."""
    result = _progress(
        tmp_path,
        backfilled=0,
        pending=5,
        audit_only=0,
        submit_failed=5,
    )
    assert result.outputs["rc"] == "0", result.outputs
    assert result.returncode == 0
    assert "excluded from closable pending" in result.stdout
    assert not evaluate_condition(
        _CONDITIONS[_ISSUE_STEP],
        {"backfill.rc": "0", "backfill_progress.rc": "0"},
    )


# --------------------------------------------------------------------------
# Step 2 — drift_input: `rc` is the exit code, not a constant
# --------------------------------------------------------------------------

def test_drift_input_publishes_the_real_exit_code(tmp_path: Path) -> None:
    """The whole chain hangs on this number being the command's, not a literal."""
    result = _run(DRIFT_INPUT, tmp_path, rc=4)
    assert result.outputs["rc"] == "4", result.outputs
    assert result.called_with("scripts.build_backtest_reference", "drift-input")


def test_drift_input_publishes_zero_when_it_worked(tmp_path: Path) -> None:
    """The control direction: without it, `rc=4` could be a constant too."""
    assert _run(DRIFT_INPUT, tmp_path, rc=0).outputs["rc"] == "0"


def test_a_failed_drift_input_stops_the_chain_and_opens_an_issue(tmp_path: Path) -> None:
    """What the number is *for*, evaluated against the workflow's own `if:`.

    Running the block does not check the condition; asserting the condition's
    text does not check the block. Feeding the executed output back through the
    real expression is the only thing that covers both.
    """
    rc = _run(DRIFT_INPUT, tmp_path, rc=4).outputs["rc"]
    outputs = {"drift_input.rc": rc, "backfill.rc": "0"}
    assert not evaluate_condition(_CONDITIONS[BACKTEST_REF], outputs), (
        "step 3 must not run on a drift-input that failed"
    )
    assert evaluate_condition(_CONDITIONS[_ISSUE_STEP], outputs), (
        "a failed advisory step must open the issue -- it is the only way "
        "anyone learns the chain broke"
    )


def test_a_successful_drift_input_opens_no_issue(tmp_path: Path) -> None:
    """The control direction for the issue: green runs must stay quiet."""
    rc = _run(DRIFT_INPUT, tmp_path, rc=0).outputs["rc"]
    assert not evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"drift_input.rc": rc, "backfill.rc": "0"}
    )


# --------------------------------------------------------------------------
# Step 3 — backtest_ref: the soft skip is not a failure
# --------------------------------------------------------------------------

def _calibration_inputs(tmp_path: Path) -> None:
    calib = tmp_path / "cache" / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    (calib / f"walk_forward_{DATE}.json").write_text("{}", encoding="utf-8")
    (calib / f"bootstrap_ci_{DATE}.json").write_text("{}", encoding="utf-8")


def test_a_missing_walk_forward_artefact_soft_skips(tmp_path: Path) -> None:
    """78 means "nothing to do", and the issue condition excludes it by hand.

    Reported as a plain failure it would page someone every day the upstream
    artefact is late; reported as 0 the chain would rebuild drift against a
    backtest reference that was never refreshed.
    """
    result = _run(BACKTEST_REF, tmp_path)
    assert result.outputs["rc"] == SOFT_SKIP, result.outputs
    assert result.returncode == 78
    assert not result.called_with("backtest-reference"), (
        "the soft skip must not spend the run on a build it has no inputs for"
    )
    assert not evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"backtest_ref.rc": result.outputs["rc"], "backfill.rc": "0"}
    ), "a soft skip must not open an issue"


def test_a_missing_bootstrap_ci_alone_also_soft_skips(tmp_path: Path) -> None:
    """Either artefact missing is enough -- the condition is an `or`."""
    calib = tmp_path / "cache" / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    (calib / f"walk_forward_{DATE}.json").write_text("{}", encoding="utf-8")
    assert _run(BACKTEST_REF, tmp_path).outputs["rc"] == SOFT_SKIP


def test_backtest_ref_builds_when_both_artefacts_are_there(tmp_path: Path) -> None:
    _calibration_inputs(tmp_path)
    result = _run(BACKTEST_REF, tmp_path, rc=0)
    assert result.outputs["rc"] == "0"
    assert result.called_with("scripts.build_backtest_reference", "backtest-reference")


def test_a_real_backtest_ref_failure_is_not_a_soft_skip(tmp_path: Path) -> None:
    """The distinction the whole step is built around: 78 vs a real failure."""
    _calibration_inputs(tmp_path)
    result = _run(BACKTEST_REF, tmp_path, rc=1)
    assert result.outputs["rc"] == "1", result.outputs
    assert evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"backtest_ref.rc": "1", "backfill.rc": "0"}
    ), "a real build failure must open the issue, unlike the soft skip"


# --------------------------------------------------------------------------
# Step 4 — drift: whether the slippage reference is passed at all
# --------------------------------------------------------------------------

def _drift(tmp_path: Path, *, slippage_rc: str, slippage_file: bool, rc: int = 0):
    calib = tmp_path / "cache" / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    if slippage_file:
        (calib / f"backtest_slippage_samples_{DATE}.json").write_text("{}", encoding="utf-8")
    return _run(DRIFT, tmp_path, rc=rc,
                expressions={"steps.slippage_sample.outputs.rc": slippage_rc})


def test_drift_passes_the_slippage_reference_when_it_exists(tmp_path: Path) -> None:
    """The step's own comment: without it drift falls back to synthetic_normal
    and the Phase-B gate stays BLOCKED. Both branches call the same script with
    the same output path, so only the argv distinguishes them.
    """
    result = _drift(tmp_path, slippage_rc="0", slippage_file=True)
    assert result.called_with("--slippage-reference"), result.calls


def test_drift_omits_the_slippage_reference_when_the_sample_step_failed(tmp_path: Path) -> None:
    result = _drift(tmp_path, slippage_rc="1", slippage_file=True)
    assert not result.called_with("--slippage-reference"), (
        "a slippage sample from a failed step must not be fed to drift"
    )
    assert result.called_with("scripts.compute_live_drift"), "drift must still run"


def test_drift_omits_the_slippage_reference_when_the_file_is_absent(tmp_path: Path) -> None:
    """rc=0 with no file is the case a status check alone would miss."""
    result = _drift(tmp_path, slippage_rc="0", slippage_file=False)
    assert not result.called_with("--slippage-reference")
    assert "synthetic_normal" in result.stdout, result.stdout


def test_drift_publishes_the_real_exit_code(tmp_path: Path) -> None:
    assert _drift(tmp_path, slippage_rc="0", slippage_file=True, rc=3).outputs["rc"] == "3"


def test_a_failed_drift_stops_families_and_emit(tmp_path: Path) -> None:
    rc = _drift(tmp_path, slippage_rc="0", slippage_file=True, rc=3).outputs["rc"]
    for name in (FAMILIES, EMIT_PUBLIC):
        assert not evaluate_condition(_CONDITIONS[name], {"drift.rc": rc}), name


# --------------------------------------------------------------------------
# Step 5a — families: evidence ownership fails closed
# --------------------------------------------------------------------------

def test_a_missing_variant_family_map_fails_and_opens_issue(tmp_path: Path) -> None:
    result = _run(FAMILIES, tmp_path, env={"VARIANT_FAMILY_MAP": "configs/absent.json"})
    assert result.outputs["rc"] == "1"
    assert result.returncode == 1
    assert not result.called_with("build_families_telemetry")
    assert evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"families.rc": "1", "backfill.rc": "0"}
    )


def test_families_builds_when_the_map_is_there(tmp_path: Path) -> None:
    (tmp_path / "map.json").write_text("{}", encoding="utf-8")
    result = _run(FAMILIES, tmp_path, env={"VARIANT_FAMILY_MAP": "map.json"}, rc=0)
    assert result.outputs["rc"] == "0"
    assert result.called_with("scripts.build_families_telemetry", "--variant-family-map")
    assert result.called_with("--strict-unknown-variants")
    assert result.called_with("--modeled-returns-json")


# --------------------------------------------------------------------------
# Step 5b — emit_public: families telemetry is included only when real
# --------------------------------------------------------------------------

def _emit(tmp_path: Path, *, families_rc: str, families_file: bool, rc: int = 0):
    live = tmp_path / "cache" / "live"
    live.mkdir(parents=True, exist_ok=True)
    if families_file:
        (live / f"families_telemetry_{DATE}.json").write_text("{}", encoding="utf-8")
    return _run(EMIT_PUBLIC, tmp_path, rc=rc,
                expressions={"steps.families.outputs.rc": families_rc})


def test_emit_includes_families_when_the_telemetry_is_real(tmp_path: Path) -> None:
    result = _emit(tmp_path, families_rc="0", families_file=True)
    assert result.called_with("--include-families"), result.calls


def test_emit_fails_closed_after_families_failure(tmp_path: Path) -> None:
    result = _emit(tmp_path, families_rc="2", families_file=False)
    assert not result.called_with("--include-families")
    assert not result.called_with("scripts.emit_public_calibration_report")
    assert result.outputs["rc"] == "1"
    assert result.returncode == 1


def test_emit_drops_families_when_the_file_is_missing_despite_rc_zero(tmp_path: Path) -> None:
    result = _emit(tmp_path, families_rc="0", families_file=False)
    assert not result.called_with("--include-families")
    assert not result.called_with("scripts.emit_public_calibration_report")
    assert result.outputs["rc"] == "1"


def test_emit_publishes_the_real_exit_code(tmp_path: Path) -> None:
    result = _emit(tmp_path, families_rc="0", families_file=True, rc=5)
    assert result.outputs["rc"] == "5"
    assert evaluate_condition(
        _CONDITIONS[_ISSUE_STEP], {"emit_public.rc": "5", "backfill.rc": "0"}
    ), "emit_public has no soft-skip path, so any non-zero rc must open the issue"


def test_every_rc_publishing_step_is_wired_into_the_issue_gate() -> None:
    """The issue gate's step list is DERIVED, not hand-maintained.

    2026-08-18 (Doppelgaenger-Sweep E2): ``slippage_sample`` (step 3b) and
    ``corpus`` (step 4b) published ``rc=`` to ``$GITHUB_OUTPUT`` but appeared
    in neither the issue-opening ``if:`` nor the issue body — a permanently
    failing advisory step stayed green-with-::warning:: forever, exactly the
    invisibility this workflow already documents (and fixed) for
    ``backfill_progress``. The two hand-written lists cannot forget the next
    rc-publishing step while this derivation holds.
    """
    import re

    import yaml

    workflow_path = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW
    )
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = [s for s in doc["jobs"]["daily-pipeline"]["steps"] if isinstance(s, dict)]

    rc_ids = [
        step["id"]
        for step in steps
        if step.get("id")
        and "GITHUB_OUTPUT" in str(step.get("run", ""))
        and re.search(r'(?m)^\s*echo "?rc=', str(step.get("run", "")))
    ]
    assert len(rc_ids) >= 5, (
        f"only {rc_ids} rc-publishing steps found — the derivation went vacuous; "
        "check the run-block pattern against the workflow."
    )

    issue_steps = [s for s in steps if s.get("name") == _ISSUE_STEP]
    assert len(issue_steps) == 1, f"issue step not found once: {issue_steps}"
    gate_condition = str(issue_steps[0].get("if", ""))
    issue_body = str(issue_steps[0].get("run", ""))

    unmonitored = [
        sid for sid in rc_ids if f"steps.{sid}.outputs.rc" not in gate_condition
    ]
    unreported = [
        sid for sid in rc_ids if f"steps.{sid}.outputs.rc" not in issue_body
    ]
    assert not unmonitored and not unreported, (
        f"rc-publishing steps missing from the issue gate: if={unmonitored} "
        f"body={unreported}. Every step that publishes an rc must be listed in "
        "both, or its permanent failure degrades to an unread ::warning::."
    )

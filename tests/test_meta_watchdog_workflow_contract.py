"""Structural pin for ``.github/workflows/meta-watchdog.yml``.

Watchdog-der-Watchdogs (Workflow-Audit 2026-06): the freshness monitor
watches the producer crons, but nothing watched the monitors themselves.
This contract pins the properties that make the meta-watchdog itself
immune to the silent-skip failure class it detects:

* it reuses ``scripts/check_workflow_freshness.py`` (no new code path),
* every watchlist entry uses the ``:any`` mode (a RED monitor run is a
  sign of life; the alarm is the ABSENCE of completed runs),
* the probe rc is captured and re-surfaced by a final fail-loud step,
* stale/error states file an operator issue.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "meta-watchdog.yml"
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_probe_step_invokes_freshness_script(workflow_text: str) -> None:
    assert "python scripts/check_workflow_freshness.py" in workflow_text, (
        "meta-watchdog must reuse scripts/check_workflow_freshness.py"
    )
    assert "--output artifacts/ci/meta_watchdog.json" in workflow_text, (
        "meta-watchdog must write its report to the canonical artifact path"
    )


# All `:any`-mode entries across BOTH probe steps of meta-watchdog.yml.
# `:any` because a RED run is proof of life — only the ABSENCE of
# completed runs is the alarm.
#
# The first two form the meta-probe watchlist (the monitors that watch
# everything else — the workflow's raison d'être). The last two are
# advisory Library-Refresh DAG entries (`:any:weekday`, PR #2842) that
# can complete red BY DESIGN (f2 gate fails when a spec is rolled back;
# credential-health fails on TV-session expiry). NB: credential-health-
# check is additionally on the freshness monitor's own watchlist — its
# entry here is the weekday DAG view, not a replacement. (Comment fixed
# 2026-07-08; it previously claimed no entry overlapped that watchlist.)
_MONITORED_MONITORS = (
    "workflow-freshness-monitor.yml",
    "smc-export-cron-watchdog.yml",
    # Library-Refresh DAG (`:any:weekday`, added 2026-06-17 PR #2842):
    "credential-health-check.yml",
    "f2-promotion-gate-daily.yml",
)

# Core pipeline steps in the Library-Refresh DAG that must SUCCEED each
# weekday.  These use `:success:weekday` mode in the DAG probe step.
_MONITORED_PIPELINES = (
    "smc-databento-production-export-sharded.yml",
    "smc-library-refresh.yml",
)


@pytest.mark.parametrize("monitored", _MONITORED_MONITORS)
def test_each_monitor_is_watched_in_any_mode(
    workflow_text: str, monitored: str
) -> None:
    assert re.search(rf"{re.escape(monitored)}=\d+:any\b", workflow_text), (
        f"{monitored} must be on the meta-watchdog watchlist with an "
        f"`=<budget>:any` entry (a red monitor run is alive; only the "
        f"absence of completed runs is the alarm)."
    )


@pytest.mark.parametrize("pipeline", _MONITORED_PIPELINES)
def test_each_pipeline_is_watched_in_success_mode(
    workflow_text: str, pipeline: str
) -> None:
    assert re.search(rf"{re.escape(pipeline)}=\d+:success", workflow_text), (
        f"{pipeline} must be on the DAG probe watchlist with an "
        f"`=<budget>:success` entry so failures are surfaced."
    )


def test_watchlist_inventory_is_complete(workflow_text: str) -> None:
    """Fail loud if a NEW `<name>.yml=<hours>` arg appears without a pin."""
    # Also match `.yaml` and uppercase so e.g. `Foo.yaml=30:any` cannot
    # slip past the ledger (the freshness script accepts both).
    pattern = re.compile(r"\b([A-Za-z0-9_-]+\.ya?ml)=\d+")
    found = set(pattern.findall(workflow_text))
    new = found - set(_MONITORED_MONITORS) - set(_MONITORED_PIPELINES)
    assert not new, (
        f"meta-watchdog watches new workflows {sorted(new)} that are not in "
        f"this test's `_MONITORED_MONITORS` ledger — add them so the pin and "
        f"the workflow stay in lockstep."
    )


def test_probe_rc_is_captured_and_resurfaced(workflow_text: str) -> None:
    assert "rc=$?" in workflow_text, "probe step must capture $? immediately"
    assert "Fail job on stale, broken, or error" in workflow_text, (
        "the final fail-loud step must exist — without it a stale monitor "
        "would leave the meta-watchdog itself green (the exact silent-skip "
        "failure mode this workflow exists to prevent)"
    )
    assert re.search(
        r"exit\s+(?:1|\"\$\{\{\s*steps\.probe\.outputs\.rc\s*\}\}\")",
        workflow_text,
    ), (
        "final step must hard-fail the job — either 'exit 1' (when if-condition "
        "already filters rc != 0) or 'exit \"${{ steps.probe.outputs.rc }}\"'"
    )


def test_stale_or_error_files_operator_issue(workflow_text: str) -> None:
    assert "gh issue create" in workflow_text and "gh issue comment" in workflow_text, (
        "stale/error must file (or update) an operator issue — a failed run "
        "alone is not an alert channel anyone watches"
    )


def test_issue_title_names_both_axes(workflow_text: str) -> None:
    """The alert title must not read as an all-clear while the DAG is down.

    This step fires on (monitor stale|error) OR (dag broken|error), so a title
    built from ``overall`` alone says "meta-watchdog: fresh" whenever only the
    DAG is red -- which is exactly how #3645 was titled while the Library-
    Refresh pipeline had not published for days.
    """
    assert 'TITLE="meta-watchdog: monitors=${OVERALL}, dag=${DAG_STATUS}' in workflow_text
    assert 'TITLE="meta-watchdog: ${OVERALL} --' not in workflow_text, (
        "title must name the DAG axis too, not just the monitor probe"
    )


def test_dag_status_is_bound_as_env_for_the_issue_step(workflow_text: str) -> None:
    assert "DAG_STATUS: ${{ steps.dag.outputs.dag_status }}" in workflow_text, (
        "the issue step must bind dag_status as env so title and body can "
        "branch on it"
    )


def test_stale_monitor_claim_is_conditional(workflow_text: str) -> None:
    """The body must only assert the axis that is actually red (#3645)."""
    issue_block = workflow_text.split("Open / update issue on stale or error", 1)[1]
    claim = "found at least one MONITOR workflow"
    assert claim in issue_block
    assert 'case "$OVERALL" in' in issue_block
    assert 'case "$DAG_STATUS" in' in issue_block
    assert issue_block.index('case "$OVERALL" in') < issue_block.index(claim), (
        "the stale-monitor sentence must live inside the stale|error arm — "
        "unconditionally it claims a dead monitor on a DAG-only alert"
    )
    assert "no monitor is stale" in issue_block, (
        "a DAG-only alert must say the monitors are fine, not imply otherwise"
    )


# --- the probe's verdict, executed rather than described ---------------------
#
# `probe` publishes rc and overall; the summary, the issue-ping and the final
# explicit-exit step all read one of them. Measured 2026-08-04 with a
# value-preserving arm swap on the freshness thresholds: all 293 assertions
# across the 3 files that name this workflow stayed green.
#
# A watchdog is the worst place for this. Its whole job is to go red when
# something else is overdue; one that reports "fresh" forever is indis-
# tinguishable from a healthy fleet.

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_PROBE_STEP = "Probe monitor freshness"


def _probe(tmp_path: Path, *, script_rc: int, overall: str | None):
    """Run the real step with check_workflow_freshness.py shadowed.

    Its exit-code contract (0 fresh / 2 stale / 1 API error) and its report are
    supplied here; what gets measured is the step's handling of them. The script
    itself is covered by tests/test_check_workflow_freshness.py.
    """
    writes = "" if overall is None else (
        'mkdir -p "$(dirname "$out")"; printf \'{"overall":"%s"}\' "$OVERALL" > "$out"'
    )
    return run_step(
        "meta-watchdog.yml", _PROBE_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable, "OVERALL": overall or "",
             "GITHUB_REPOSITORY": "skipp-dev/skipp-algo", "GITHUB_TOKEN": "stub-token"},
        stubs={"python": Stub(script=f'''
case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac
out=""; prev=""
for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done
[ -n "$out" ] && {{ {writes or "true"}; }}
exit {script_rc}
''')},
    )


def test_a_fresh_fleet_reports_fresh(tmp_path: Path) -> None:
    result = _probe(tmp_path, script_rc=0, overall="ok")
    assert result.returncode == 0, result.stderr
    assert result.outputs["rc"] == "0"
    assert result.outputs["overall"] == "ok"


def test_a_stale_monitor_survives_to_the_outputs(tmp_path: Path) -> None:
    """rc=2 must reach the outputs, not abort the step.

    The `set +e` around the script exists so the report and summary are appended
    BEFORE the job fails. A step that died here would take its own verdict with
    it and the run would show no reason.
    """
    result = _probe(tmp_path, script_rc=2, overall="stale")
    assert result.returncode == 0, "the probe must not abort on a stale verdict"
    assert result.outputs["rc"] == "2"
    assert result.outputs["overall"] == "stale"


def test_a_missing_report_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """No report means the probe could not measure -- never that all is well."""
    result = _probe(tmp_path, script_rc=1, overall=None)
    assert result.outputs["rc"] == "1"
    assert result.outputs["overall"] == "error", (
        f"an absent report must not read as healthy; got {result.outputs}"
    )


# The tests above stub check_workflow_freshness.py, so they measure how the
# step HANDLES a verdict -- and are blind to what it ASKS FOR. Measured
# 2026-08-04: swapping the freshness thresholds (30 <-> 80 in `probe`, 14 <-> 30
# in `dag`) left them green along with all 292 other assertions. A watchdog that
# asks the wrong question answers it correctly and reports nothing.
#
# So pin the specs off the recorded invocation. Executed, not grepped: the
# strings below have to survive line continuations, quoting and argument order
# and actually arrive on the command line.

_PROBE_SPECS = (
    "workflow-freshness-monitor.yml=30:any",
    "smc-export-cron-watchdog.yml=80:any",
)
_DAG_SPECS = (
    "smc-databento-production-export-sharded.yml=14:success:weekday",
    "smc-library-refresh.yml=30:success:weekday",
    "f2-promotion-gate-daily.yml=30:any:weekday",
    # 2026-08-18 (Grenzgänger-Sweep A4): credential-health runs SEVEN days a
    # week (cron "0 6 * * *"), so the :weekday tag subtracted up to 48h of
    # weekend from its measured age — a Friday death stayed "fresh" until
    # Tuesday, a blind spot sitting exactly in front of the 72h TV-cookie
    # TTL this prober guards. The freshness monitor's own watchlist already
    # carried the correct untagged entry.
    "credential-health-check.yml=30:any",
)


def test_the_probe_asks_for_the_documented_thresholds(tmp_path: Path) -> None:
    call = _probe(tmp_path, script_rc=0, overall="ok").called_with(
        "check_workflow_freshness.py"
    )
    assert call, "the probe never invoked the freshness checker"
    for spec in _PROBE_SPECS:
        assert spec in call[0], (
            f"the probe no longer asks for {spec!r}. A changed threshold is a "
            f"changed contract with whatever that monitor guards. Asked: {call[0]}"
        )


def test_the_dag_probe_asks_for_the_documented_thresholds(tmp_path: Path) -> None:
    """The core chain is checked on SUCCESS runs, the advisory pair on any run.

    That distinction is the whole point of the dag probe: a core producer that
    ran and failed is not fresh. Pinning the specs pins that distinction too --
    `:success:` versus `:any:` is one token.
    """
    result = run_step(
        "meta-watchdog.yml", "Check Library-Refresh DAG health", tmp_path,
        env={"REAL_PYTHON": sys.executable,
             "GITHUB_REPOSITORY": "skipp-dev/skipp-algo", "GITHUB_TOKEN": "stub-token"},
        stubs={"python": Stub(script='''
case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac
exit 0
'''), "python3": Stub(passthrough=sys.executable)},
    )
    call = result.called_with("check_workflow_freshness.py")
    assert call, "the dag probe never invoked the freshness checker"
    for spec in _DAG_SPECS:
        assert spec in call[0], (
            f"the dag probe no longer asks for {spec!r}. Asked: {call[0]}"
        )


# --- governance step (Geburtsfehler-Sweep 2026-08-28) ------------------------
#
# scripts/verify_branch_protection.py existierte seit ADR-0011 und lief in
# KEINEM Workflow; die 27.8.-Drift (gate-Kontext, #5160) bewies die Luecke
# live. Dieser Block pinnt die Verdrahtung AUSGEFUEHRT: der echte Step-Text
# unter der echten Default-Shell, python gestubbt auf die drei rc-Vertraege.

_GOVERNANCE_STEP = "Verify the branch-protection governance baseline"


def _governance(tmp_path: Path, *, script_rc: int):
    return run_step(
        "meta-watchdog.yml", _GOVERNANCE_STEP, tmp_path,
        env={"GITHUB_TOKEN": "stub-token"},
        stubs={"python": Stub(exit_code=script_rc)},
    )


def test_a_clean_governance_baseline_stays_green(tmp_path: Path) -> None:
    result = _governance(tmp_path, script_rc=0)
    assert result.returncode == 0, result.stderr
    assert result.outputs["governance_rc"] == "0"
    assert "::error" not in result.stdout


def test_a_governance_finding_reaches_the_outputs_not_the_step_rc(tmp_path: Path) -> None:
    """rc=1 muss als governance_rc publiziert werden, nicht den Step toeten.

    Die Wertung passiert im Fail-Step; stirbt der Step hier, nimmt er sein
    eigenes Verdict mit (dieselbe -e-Falle wie Lauf 32821936783).
    """
    result = _governance(tmp_path, script_rc=1)
    assert result.returncode == 0, "der rc-Fang darf unter -e nicht sterben"
    assert result.outputs["governance_rc"] == "1"
    assert "::error" in result.stdout, "ein Governance-Finding muss annotiert sein"


def test_an_unmeasurable_governance_probe_warns_but_does_not_verdict(tmp_path: Path) -> None:
    """rc=2 (Netz/Auth) ist 'nicht messbar' — Warnung, weder rot noch gruen."""
    result = _governance(tmp_path, script_rc=2)
    assert result.returncode == 0
    assert result.outputs["governance_rc"] == "2"
    assert "::warning" in result.stdout and "KEIN Bestehen" in result.stdout
    assert "::error" not in result.stdout


def test_the_fail_step_reads_the_governance_verdict(workflow_text: str) -> None:
    """Nur rc=1 faerbt den Job; rc=2 darf es ausdruecklich nicht."""
    fail_block = workflow_text.split("Fail job on stale, broken, or error", 1)[1]
    assert "steps.governance.outputs.governance_rc == '1'" in fail_block, (
        "der Fail-Step liest das Governance-Verdict nicht mehr -- damit waere "
        "der Step wieder eine Notiz statt eines Waechters"
    )
    assert "governance_rc == '2'" not in fail_block, (
        "rc=2 heisst 'nicht messbar' und darf den Watchdog nicht rot faerben "
        "(sonst geht jede Netzstoerung als Governance-Bruch durch)"
    )


def test_the_governance_step_invokes_the_verifier(tmp_path: Path) -> None:
    """Ausgefuehrt, nicht gegreppt: der Aufruf muss auf der Kommandozeile ankommen."""
    call = _governance(tmp_path, script_rc=0).called_with("verify_branch_protection")
    assert call, "der Step ruft scripts/verify_branch_protection nicht mehr auf"

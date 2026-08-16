"""Contract tests for the commercial-shadow launchd driver (2026-08-16, P0).

The driver is the live ownership of the pilot doc's "collect the required
unique observations" launch gate, and it carries a DORMANT broker-connected
paper stage. These tests pin the safety topology at the source level, the
way the other C13 driver guards do (smoke-sentinel scope, branch guard):

* the audit-only campaign path has no submission flag anywhere near it;
* the paper stage sits behind BOTH interlocks — the dated operator flip in
  ``configs/commercial_paper_submission.json`` AND the campaign observation
  gate PASS — and a missing/failed interlock read fails CLOSED (dormant);
* every failure path writes a DEGRADED marker before exiting;
* the campaign report is pushed via the shared data-branch helper BEFORE
  the interlock decision, so observation progress is visible during the
  audit-only weeks;
* the shipped flip config is disabled — enabling it is a dated PR, never a
  default.
"""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "automation" / "launchd" / "run-c13-commercial-shadow.sh"
PLIST = (
    REPO / "automation" / "launchd" / "com.skippalgo.c13.commercial-shadow.plist"
)
RECONCILE = REPO / "automation" / "launchd" / "run-c13-reconcile.sh"
SUBMISSION_CONFIG = REPO / "configs" / "commercial_paper_submission.json"


def _driver() -> str:
    return DRIVER.read_text(encoding="utf-8")


def test_the_shipped_flip_config_is_disabled() -> None:
    config = json.loads(SUBMISSION_CONFIG.read_text(encoding="utf-8"))

    assert config["enabled"] is False
    assert config["flippedAt"] is None
    assert "observation_gate" in config["interlock"]


def test_the_paper_stage_sits_behind_both_interlocks() -> None:
    source = _driver()
    dormant_gate = source.split("# 3. Paper stage", 1)[1]
    decision = dormant_gate.split("exit 0", 1)[0]

    assert '"${_submission_enabled}" != "true"' in decision
    assert '"${_campaign_verdict}" != "PASS"' in decision
    # An unreadable config or report resolves to the DORMANT side.
    assert "print('false')" in decision
    assert "print('ABSENT')" in decision


def test_the_submit_flag_appears_only_after_the_interlock() -> None:
    source = _driver()
    before, after = source.split("# 3. Paper stage", 1)
    # Comments may describe the flag anywhere; only executable lines count.
    code_before = "\n".join(
        line
        for line in before.splitlines()
        if not line.lstrip().startswith("#")
    )

    assert "--place-paper-orders" not in code_before
    assert "--place-paper-orders" in after
    assert "--prospective-paper-pilot" in after
    # The audit-only campaign attempt has no submission capability at all.
    assert "run_commercial_shadow_campaign" in code_before


def test_the_report_push_precedes_the_interlock_decision() -> None:
    source = _driver()
    before = source.split("# 3. Paper stage", 1)[0]

    assert "push_to_data_branch" in before
    assert "campaign_report.json" in before


def test_every_failure_path_writes_a_degraded_marker() -> None:
    source = _driver()
    for token in (
        "venv-missing",
        "python-not-executable",
        "smoke-halt-sentinel",
        "databento-pull-failed",
        "campaign-attempt-failed",
        "portfolio-snapshot-failed",
        "producer-failed",
        "commercial-submit-failed",
    ):
        assert f'_write_marker "DEGRADED" "{token}' in source, token


def test_the_driver_honours_the_smoke_sentinel_and_et_gate() -> None:
    source = _driver()

    assert "smoke_HALT" in source
    assert "lib_c13_et_gate.sh" in source
    assert "c13_require_et_window" in source
    # `cmd || var=$?` idiom — a bare `cmd; var=$?` is dead code under set -e.
    assert "|| _pull_exit=$?" in source
    assert "|| _campaign_exit=$?" in source
    assert "|| _run_exit=$?" in source


def test_the_plist_invokes_the_driver_on_weekdays_only() -> None:
    with PLIST.open("rb") as fh:
        plist = plistlib.load(fh)

    assert plist["Label"] == "com.skippalgo.c13.commercial-shadow"
    assert plist["ProgramArguments"][0] == "/bin/bash"
    assert plist["ProgramArguments"][1].endswith(
        "automation/launchd/run-c13-commercial-shadow.sh"
    )
    intervals = plist["StartCalendarInterval"]
    assert intervals, "no StartCalendarInterval entries"
    assert {entry["Weekday"] for entry in intervals} == {1, 2, 3, 4, 5}
    assert plist["RunAtLoad"] is False


def test_the_reconcile_driver_covers_the_commercial_audit_file() -> None:
    source = RECONCILE.read_text(encoding="utf-8")

    assert "incubation_commercial_${DATE}.jsonl" in source
    assert "commercial-reconcile-failed" in source
    # Guarded on existence: an absent file means the paper stage is dormant,
    # which must stay a quiet no-op, not a DEGRADED day.
    assert '[[ -f "${COMMERCIAL_AUDIT}" ]]' in source

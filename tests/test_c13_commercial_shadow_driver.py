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


def test_the_dataset_default_is_the_licensed_feed() -> None:
    # XNAS.ITCH current-day history requires a live license this account does
    # not hold (403 measured 2026-08-17 23:42Z); EQUS.MINI is covered by the
    # account's existing live license. A silent revert would kill every
    # intraday fire again, so the default is pinned.
    source = _driver()

    assert 'C13_COMMERCIAL_DATASET:-EQUS.MINI' in source
    assert 'C13_COMMERCIAL_DATASET:-XNAS.ITCH' not in source


def test_the_campaign_runs_with_the_vendor_honest_freshness_budgets() -> None:
    # 900s, not the 300s defaults: Databento historical availability trails
    # the wall clock intraday (measured 2026-08-17: XNAS.ITCH served up to
    # 14:00:00Z at a 14:05:00Z request), so an honest clamped PIT snapshot is
    # ~5-7 minutes old by construction and 300s would fail-close every
    # attempt. The campaign contract freezes whatever the driver passes, so
    # this pin is what keeps the recorded thresholds intentional.
    source = _driver()
    campaign_stage = source.split("run_commercial_shadow_campaign", 1)[1]
    campaign_stage = campaign_stage.split("# 3. Paper stage", 1)[0]

    assert "--max-setup-age-seconds 900" in campaign_stage
    assert "--max-source-age-p95-seconds 900" in campaign_stage


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


def test_the_pull_cli_resolves_its_key_from_the_checkout_env() -> None:
    """launchd inherits no secrets; the pull must load .env itself.

    Without this every intraday fire fails at step 1 with a missing
    DATABENTO_API_KEY — measured on 2026-08-17 before the first install.
    """
    pull_source = (REPO / "scripts" / "pull_databento_edge_input.py").read_text(
        encoding="utf-8"
    )
    main_body = pull_source.split("def main(", 1)[1]

    assert "load_dotenv(" in main_body


def test_the_driver_honours_the_smoke_sentinel_and_et_gate() -> None:
    source = _driver()

    assert "smoke_HALT" in source
    assert "lib_c13_et_gate.sh" in source
    # HOUR scope, not the default day scope: ~6 attempts per session is the
    # campaign design, and a failed attempt must only burn its own hour slot
    # (2026-08-17: the day marker let the failed 16:05 fire swallow the day).
    assert "c13_require_et_window \"$REPO\" 12 45 195 commercial-shadow hour" in source
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


def test_the_paper_stage_runs_with_the_vendor_honest_freshness_budget() -> None:
    # The paper stage submits from the SAME clamped PIT pull as the campaign
    # stage, so the submitter's 300s default would fail-close every honest
    # submission (2026-08-18 Verdrahtungs-Sweep K3: the driver had measured
    # and fixed this for the campaign stage only).
    source = _driver()
    paper_stage = source.split("# 3. Paper stage", 1)[1]

    assert "--max-setup-age-seconds 900" in paper_stage


def test_the_paper_stage_wires_the_wsh_earnings_filter() -> None:
    # Without --wsh-events-jsonl the EarningsFilter is None on the commercial
    # lane and the pilot doc's promised earnings-blocked audit rows can never
    # exist (2026-08-18 Verdrahtungs-Sweep K7). Mirrors run-c13-phase-a.sh
    # including the 4-day staleness rule.
    source = _driver()
    paper_stage = source.split("# 3. Paper stage", 1)[1]

    assert "--wsh-events-jsonl" in paper_stage
    assert "${WSH_FLAG}" in paper_stage
    assert '"${WSH_AGE_DAYS}" -le 4' in paper_stage


def test_the_commercial_paper_audit_has_a_data_branch_transport_edge() -> None:
    # The CI consumer reads cache/live/incubation_*.jsonl from the
    # data/phase-a-audit overlay (c13-daily-cron.yml); a file that is never
    # pushed can never reach the families telemetry or the Phase-1 gate.
    # This pins the transport EDGE the header promised but no driver carried
    # (2026-08-18 Verdrahtungs-Sweep K1): fresh push after submission in the
    # commercial driver, reconciled push in the reconcile driver.
    driver_source = _driver()
    paper_stage = driver_source.split("# 3. Paper stage", 1)[1]
    assert 'push_to_data_branch "chore(c13): commercial paper audit' in paper_stage
    assert '"cache/live/incubation_commercial_${DATE}.jsonl"' in paper_stage

    reconcile_source = RECONCILE.read_text(encoding="utf-8")
    push_block = reconcile_source.split("push_to_data_branch", 1)[1]
    assert '"cache/live/incubation_commercial_${DATE}.jsonl"' in push_block

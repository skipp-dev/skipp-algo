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


# Monitors that are NOT already on the freshness monitor's own watchlist
# (credential-health-check and the g23 A/B watchdog are covered there).
# Each entry must use `:any` — see module docstring.
_MONITORED_MONITORS = (
    "workflow-freshness-monitor.yml",
    "drift-watchdog.yml",
    "smc-export-cron-watchdog.yml",
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


def test_watchlist_inventory_is_complete(workflow_text: str) -> None:
    """Fail loud if a NEW `<name>.yml=<hours>` arg appears without a pin."""
    pattern = re.compile(r"\b([a-z0-9_-]+\.yml)=\d+")
    found = set(pattern.findall(workflow_text))
    new = found - set(_MONITORED_MONITORS)
    assert not new, (
        f"meta-watchdog watches new workflows {sorted(new)} that are not in "
        f"this test's `_MONITORED_MONITORS` ledger — add them so the pin and "
        f"the workflow stay in lockstep."
    )


def test_probe_rc_is_captured_and_resurfaced(workflow_text: str) -> None:
    assert "rc=$?" in workflow_text, "probe step must capture $? immediately"
    assert "Fail job on stale or error" in workflow_text, (
        "the final fail-loud step must exist — without it a stale monitor "
        "would leave the meta-watchdog itself green (the exact silent-skip "
        "failure mode this workflow exists to prevent)"
    )
    assert re.search(r"exit \"\$\{\{ steps\.probe\.outputs\.rc \}\}\"", workflow_text), (
        "final step must re-surface the captured probe rc via exit"
    )


def test_stale_or_error_files_operator_issue(workflow_text: str) -> None:
    assert "gh issue create" in workflow_text and "gh issue comment" in workflow_text, (
        "stale/error must file (or update) an operator issue — a failed run "
        "alone is not an alert channel anyone watches"
    )

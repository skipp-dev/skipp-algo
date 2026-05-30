"""ADR-0010: generic cron-workflow invariants suite (Option C — Hybrid).

This module is the *canonical home* for **universal** invariants that every
pure-cron workflow must satisfy, so that a newly-added cron is covered the
moment it lands rather than waiting for someone to remember to write a
bespoke contract test (the failure mode that let
``smc-measurement-benchmark-rolling.yml``'s freshness gap go unnoticed until
#2453).

Scope discipline
----------------
Several universal invariants are *already* enforced generically by dedicated
parametrized guards; this suite deliberately does NOT duplicate them (two
enforcement sites would drift):

* ``concurrency: cancel-in-progress: false``
      → ``test_workflow_concurrency_cron_no_cancel.py`` (F-V5-C2)
* top-level ``permissions:`` present / least-privilege
      → ``test_workflow_permissions_present.py``
* ``PYTHONUNBUFFERED`` for python crons
      → ``test_workflow_python_unbuffered.py`` (F-V5-A2)
* hosted-runner selector pin
      → ``test_workflow_runner_pinned.py``

The **net-new** universal invariant introduced here is the
``timeout-minutes`` runaway guard (F-V10): every job of a pure-cron workflow
MUST declare an explicit ``timeout-minutes``.  A cron job with no timeout can
hang indefinitely, silently burning Actions minutes and starving the runner
pool — a textbook silent-failure class with no artifact and no red check.
Per-workflow contract tests still pin *specific* values (ci=45,
credential-health<=10, …); this suite only enforces that the guard *exists*
and is sane.

If you add a new pure-cron workflow, give every job a ``timeout-minutes``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Triggers that, if present alongside ``schedule:``, mean the workflow is NOT
# pure-cron. Mirrors ``test_workflow_concurrency_cron_no_cancel`` so the two
# suites share one definition of "pure-cron".
_PR_LIKE_TRIGGERS = frozenset({"push", "pull_request", "pull_request_target"})

# Sane bounds for a cron job timeout. Lower bound rejects ``0`` (GitHub treats
# 0 as "no limit"); upper bound (6h) is generous vs the longest real cron
# (databento consumer = 120) yet still trips an obviously-runaway value.
_TIMEOUT_MIN = 1
_TIMEOUT_MAX = 360

# Regression floor for the discovery glob (see freshness-monitor near-miss).
# Keep comfortably below the real count so adding/removing a single cron does
# not churn this constant; raise it only if it would otherwise pass vacuously.
_MIN_EXPECTED_CRON_WORKFLOWS = 20


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _is_pure_cron(workflow: dict) -> bool:
    # PyYAML parses the bare key ``on:`` to the boolean True. Handle both.
    triggers = workflow.get("on") or workflow.get(True)
    if not isinstance(triggers, dict):
        return False
    if "schedule" not in triggers:
        return False
    return not (_PR_LIKE_TRIGGERS & set(triggers))


def _pure_cron_workflows() -> list[Path]:
    out: list[Path] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            data = _load_yaml(path)
        except yaml.YAMLError:
            continue
        if _is_pure_cron(data):
            out.append(path)
    return out


@pytest.mark.parametrize("workflow_path", _pure_cron_workflows(), ids=lambda p: p.name)
def test_cron_jobs_declare_timeout_minutes(workflow_path: Path) -> None:
    """F-V10: every job of a pure-cron workflow must declare a sane timeout."""
    data = _load_yaml(workflow_path)
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and jobs, (
        f"{workflow_path.name}: no `jobs:` mapping found."
    )

    offenders: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        # Reusable-workflow calls (``uses:`` at job level) inherit the called
        # workflow's own timeouts and cannot set ``timeout-minutes`` here.
        if "uses" in job and "steps" not in job:
            continue
        tmo = job.get("timeout-minutes")
        if not isinstance(tmo, int) or isinstance(tmo, bool):
            offenders.append(f"{job_id}: missing/invalid timeout-minutes ({tmo!r})")
        elif not (_TIMEOUT_MIN <= tmo <= _TIMEOUT_MAX):
            offenders.append(
                f"{job_id}: timeout-minutes={tmo} outside "
                f"[{_TIMEOUT_MIN}, {_TIMEOUT_MAX}]"
            )

    assert not offenders, (
        f"{workflow_path.name}: cron jobs must declare a runaway-guard "
        f"`timeout-minutes` (F-V10). Offending jobs:\n  "
        + "\n  ".join(offenders)
    )


def test_audit_finds_expected_cron_workflows() -> None:
    """Sanity floor: guard against an over-eager glob silently passing."""
    found = _pure_cron_workflows()
    assert len(found) >= _MIN_EXPECTED_CRON_WORKFLOWS, (
        f"Discovered only {len(found)} pure-cron workflows "
        f"(< floor {_MIN_EXPECTED_CRON_WORKFLOWS}); the audit filter is broken."
    )

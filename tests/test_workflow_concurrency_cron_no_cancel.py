"""Audit guard for F-V5-C2 (2026-05-01).

Cron-triggered workflows must NOT cancel an in-flight run when the next
scheduled tick fires.  A scheduled batch that is killed mid-run typically
leaves a half-written artifact, an orphaned PR branch, or a truncated
measurement series — exactly the kind of silent breakage the V5 audit
flagged under finding F-V5-C2.

The rule we enforce here:

* Workflows triggered ONLY by ``schedule:`` (plus the universally-allowed
  ``workflow_dispatch:``) MUST declare a top-level ``concurrency`` block
  with ``cancel-in-progress: false``.
* PR-triggered workflows are deliberately excluded — fast feedback there
  is preferred over preservation of a soon-to-be-stale run.
* Workflows listed in ``_QUEUE_MAX_WORKFLOWS`` must additionally set
  ``queue: max``.  2026-08-06: ``cancel-in-progress: false`` governs only the
  RUNNING run.  A group still holds exactly one PENDING run under the default
  ``queue: single``, and the next tick CANCELS that waiter — so the guard above
  alone never delivered the queueing this module promises.  ``queue: max``
  raises the waiting room to 100 runs, served FIFO (best-effort).

If you add a new pure-cron workflow, make sure it follows the pattern
documented in `.github/workflows/c13-daily-cron.yml`:

```yaml
concurrency:
  group: <workflow-filename-without-yml>
  cancel-in-progress: false
  queue: max
```
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Triggers that, if present alongside ``schedule:``, indicate the workflow is
# NOT pure-cron and therefore exempt from the queue-instead-of-kill rule.
_PR_LIKE_TRIGGERS = frozenset({"push", "pull_request", "pull_request_target"})

# Pure-cron exemptions.  Add only with an explicit reason and a tracking
# finding ID so the audit ledger stays honest.
_EXEMPT_WORKFLOWS = {
    # F-V5-C1 (#2011): smc-live-news-refresh.yml is the *one* cron whose
    # operator preference is to let a fresh poll preempt a stuck old one (the
    # whole point of the workflow is freshness, not artifact integrity).
    "smc-live-news-refresh.yml",
}


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_pure_cron(workflow: dict) -> bool:
    # PyYAML parses the bare key ``on:`` to the boolean True.  Handle both.
    triggers = workflow.get("on") or workflow.get(True)
    if not isinstance(triggers, dict):
        return False
    if "schedule" not in triggers:
        return False
    return not (_PR_LIKE_TRIGGERS & set(triggers))


def _pure_cron_workflows() -> list[Path]:
    out: list[Path] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if path.name in _EXEMPT_WORKFLOWS:
            continue
        try:
            data = _load_yaml(path)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and _is_pure_cron(data):
            out.append(path)
    return out


@pytest.mark.parametrize("workflow_path", _pure_cron_workflows(), ids=lambda p: p.name)
def test_cron_workflow_does_not_cancel_in_progress(workflow_path: Path) -> None:
    """F-V5-C2: a cron workflow must queue overlapping runs, not kill them."""
    data = _load_yaml(workflow_path)
    concurrency = data.get("concurrency")
    assert isinstance(concurrency, dict), (
        f"{workflow_path.name}: missing top-level `concurrency:` block. "
        "F-V5-C2 (2026-05-01) requires every cron-only workflow to declare\n"
        "    concurrency:\n"
        "      group: <workflow-name>\n"
        "      cancel-in-progress: false\n"
        "so an overlapping cron tick queues instead of killing the in-flight run."
    )
    cip = concurrency.get("cancel-in-progress")
    assert cip is False, (
        f"{workflow_path.name}: cancel-in-progress must be `false` for cron-only "
        f"workflows (F-V5-C2). Got: {cip!r}."
    )


def test_audit_finds_at_least_one_cron_workflow() -> None:
    """Sanity check: regression guard against an over-eager glob filter."""
    assert _pure_cron_workflows(), (
        "Did not discover any pure-cron workflows — the audit filter is broken."
    )


# 2026-08-06: workflows that COMMIT, PUSH or OPEN A PR.  For these a dropped
# pending tick is a lost day of data, not a skipped poll, so they must queue.
# Extending this set to the remaining pure-cron workflows is tracked separately.
_QUEUE_MAX_WORKFLOWS = frozenset(
    {
        "adr0023-magnitude-shadow-daily.yml",
        "adr0023-magnitude-stage1-weekly.yml",
        "ats-baseline-daily.yml",
        "c13-daily-cron.yml",
        "edge-pipeline-real-run.yml",
        "evidence-freshness-snapshot.yml",
        "f2-frozen-artifact-bootstrap.yml",
        "fvg-quality-quartile-gate.yml",
        "g23-ab-watchdog.yml",
        "open-prep-outcome-backfill.yml",
        "promotion-gate-daily.yml",
        "run-open-prep-daily.yml",
        "sweep-trap-shadow-daily.yml",
    }
)


@pytest.mark.parametrize("name", sorted(_QUEUE_MAX_WORKFLOWS))
def test_writing_workflow_queues_pending_runs(name: str) -> None:
    """F-V5-C2: `cancel-in-progress: false` guards the running run only."""
    path = WORKFLOWS_DIR / name
    assert path.is_file(), f"{name}: listed in _QUEUE_MAX_WORKFLOWS but not on disk."
    concurrency = _load_yaml(path).get("concurrency")
    assert isinstance(concurrency, dict), f"{name}: missing top-level `concurrency:`."
    assert concurrency.get("queue") == "max", (
        f"{name}: needs `queue: max`. Without it the group holds exactly one "
        "pending run and the next tick cancels that waiter, silently dropping "
        "a run that writes to the repo. Got: {!r}.".format(concurrency.get("queue"))
    )

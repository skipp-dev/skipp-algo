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

If you add a new pure-cron workflow, make sure it follows the pattern
documented in `.github/workflows/c13-daily-cron.yml`:

```yaml
concurrency:
  group: <workflow-filename-without-yml>
  cancel-in-progress: false
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
    # F-V5-C1 (#2011): smc-live-newsapi-refresh.yml is the *one* cron whose
    # operator preference is to let a fresh poll preempt a stuck old one (the
    # whole point of the workflow is freshness, not artifact integrity).
    "smc-live-newsapi-refresh.yml",
}


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
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

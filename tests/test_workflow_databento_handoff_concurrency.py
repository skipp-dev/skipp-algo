"""Pin: workflow-level concurrency guards on the Databento → library handoff.

Audit follow-up to **F-V8-C3.1 PR D (2026-05-02)**.

Background
----------
PR #2027 raised the producer (``smc-databento-production-export``) timeout
cap from 60 → 120 minutes after a streak of 12 consecutive runs were
killed by the prior cap. With the cap now equal to the 2-hour cron
interval, two consecutive ticks could in principle overlap if a single
run takes its full budget. The same risk applies to the consumer
(``smc-library-refresh``).

A workflow-level ``concurrency:`` block with ``cancel-in-progress: false``
serializes runs per ``github.ref`` so a slow run is followed by a queued
run rather than a parallel race. ``cancel-in-progress: false`` is
critical: cancelling a half-finished producer leaves a stale/partial
artifact for the consumer to ingest; cancelling a half-finished consumer
leaves a half-written artifact tree and possibly a zombie PR branch.

This module pins those properties so a future "harmless cleanup" cannot
silently re-open the race.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

_HANDOFF_WORKFLOWS = {
    "smc-databento-production-export": {
        "expected_group": "smc-databento-production-export-${{ github.ref }}",
    },
    "smc-library-refresh": {
        "expected_group": "smc-library-refresh-${{ github.ref }}",
    },
}


def _load(path: Path) -> dict:
    # F-V8-C3.1-D round-3 (Copilot review): pin UTF-8 to match sibling
    # workflow-YAML pin tests (e.g. test_workflow_databento_handoff_timeouts.py)
    # so the test is deterministic across environments with non-UTF-8 locales.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("workflow_name,expected", list(_HANDOFF_WORKFLOWS.items()))
def test_handoff_workflow_has_concurrency_guard(workflow_name: str, expected: dict) -> None:
    """Each handoff workflow must declare a workflow-level concurrency block.

    Required shape (F-V8-C3.1-D):

    .. code-block:: yaml

       concurrency:
         group: <workflow-name>-${{ github.ref }}
         cancel-in-progress: false
    """
    path = _WORKFLOWS / f"{workflow_name}.yml"
    data = _load(path)

    assert "concurrency" in data, (
        f"{workflow_name}: missing workflow-level `concurrency:` block. "
        "F-V8-C3.1-D requires a per-ref guard so back-to-back cron ticks "
        "cannot run in parallel when a single run uses its full timeout."
    )

    block = data["concurrency"]
    assert isinstance(block, dict), (
        f"{workflow_name}: `concurrency` must be a mapping with `group` "
        f"and `cancel-in-progress`, got {type(block).__name__}."
    )

    assert block.get("group") == expected["expected_group"], (
        f"{workflow_name}: concurrency.group must be "
        f"{expected['expected_group']!r} (per-ref serialization), "
        f"got {block.get('group')!r}."
    )

    cancel = block.get("cancel-in-progress")
    assert cancel is False, (
        f"{workflow_name}: concurrency.cancel-in-progress MUST be false. "
        "Cancelling a half-finished run leaves stale/partial artifacts "
        "that poison the next handoff window. The follow-on tick should "
        "queue, not race."
    )

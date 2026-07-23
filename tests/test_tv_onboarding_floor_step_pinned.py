"""Structural pin: the tv-preflight add-to-chart floor test must actually run.

PR #3967 added ``tv_preflight_add_to_chart_floor.test.ts`` but it ran nowhere;
PR #3970 wired it into ``.github/workflows/tv-onboarding-packages.yml`` as an
executed step *and* into the workflow's ``paths`` triggers. This pin fails the
required ``fast-gates`` check if either half of that wiring is removed, so the
"the pin exists but runs nowhere" regression that #3970 closed cannot silently
return.

Failure semantics: an assertion here means the floor pin's execution wiring was
dropped. The fix is to restore the step / path trigger, not to edit this pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tv-onboarding-packages.yml"
FLOOR_TEST = "automation/tradingview/tests/tv_preflight_add_to_chart_floor.test.ts"
PREFLIGHT_SOURCE = "scripts/tv_preflight.ts"


@pytest.fixture(scope="module")
def workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "tv-onboarding-packages.yml must parse as a mapping"
    return data


def _package_steps(workflow: dict) -> list[dict]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and "package" in jobs, (
        "tv-onboarding-packages.yml MUST keep the `package` job that runs the pin."
    )
    steps = jobs["package"].get("steps")
    assert isinstance(steps, list) and steps, "the `package` job MUST declare steps"
    return [step for step in steps if isinstance(step, dict)]


def test_floor_pin_is_executed_as_a_step(workflow: dict) -> None:
    runs = [str(step.get("run", "")) for step in _package_steps(workflow)]
    floor_runs = [run for run in runs if FLOOR_TEST in run]
    assert floor_runs, (
        "tv-onboarding-packages.yml MUST run the add-to-chart floor pin as a step "
        f"({FLOOR_TEST}). #3970 wired it in to close #3967; dropping the step "
        "re-opens 'the pin exists but runs nowhere'."
    )
    assert any("tsx" in run and "--test" in run for run in floor_runs), (
        "the floor step MUST execute the pin via `tsx --test`, not merely name the file."
    )


def test_floor_pin_and_source_are_path_triggers(workflow: dict) -> None:
    # A push/PR touching the floor test or its guarded source (tv_preflight.ts)
    # MUST trigger this workflow, else the pin could rot while the code it guards
    # changes underneath it — the `paths` filter is the other half of #3970.
    on_block = workflow.get("on") if "on" in workflow else workflow.get(True)
    assert isinstance(on_block, dict), "workflow MUST declare `on:` as a mapping"
    for trigger in ("push", "pull_request"):
        block = on_block.get(trigger)
        assert isinstance(block, dict), f"workflow MUST configure `{trigger}` as a mapping"
        paths = block.get("paths")
        assert isinstance(paths, list), f"`{trigger}` MUST declare a `paths` filter"
        assert FLOOR_TEST in paths, (
            f"`{trigger}.paths` MUST include {FLOOR_TEST} so editing the pin re-runs it."
        )
        assert PREFLIGHT_SOURCE in paths, (
            f"`{trigger}.paths` MUST include {PREFLIGHT_SOURCE} so changing the guarded "
            "source re-runs the floor pin."
        )

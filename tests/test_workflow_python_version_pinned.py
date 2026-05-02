"""Pin tests for F-V8-B3.1 (2026-05-02) — single source of Python version.

The composite action `.github/actions/setup-python-pinned/action.yml` is
the canonical source of truth for the Python toolchain version used by
every CI workflow in this repo.

These tests enforce two invariants:

1. The composite action exists, is well-formed, and pins exactly one
   `python-version`.
2. Every Phase-1 workflow (the 5 representative workflows migrated in the
   first PR) uses the composite — i.e. has zero raw `python-version:`
   keys inside `actions/setup-python` steps.

Phase 2 will add the remaining 23 workflows to `_PHASE1_WORKFLOWS` and
extend (or replace) this test to cover the full set.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COMPOSITE_PATH = _REPO_ROOT / ".github" / "actions" / "setup-python-pinned" / "action.yml"
_PHASE1_WORKFLOWS = (
    _REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml",
    _REPO_ROOT / ".github" / "workflows" / "c13-daily-cron.yml",
    _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml",
    _REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml",
    _REPO_ROOT / ".github" / "workflows" / "f2-promotion-gate-daily.yml",
)
_COMPOSITE_USES_REF = "./.github/actions/setup-python-pinned"


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_composite_action_exists_and_pins_one_python_version() -> None:
    assert _COMPOSITE_PATH.is_file(), (
        f"Missing composite action {_COMPOSITE_PATH.relative_to(_REPO_ROOT)}; "
        "F-V8-B3.1 requires this file as the single source of truth."
    )
    composite = _load(_COMPOSITE_PATH)
    runs = composite.get("runs", {})
    assert runs.get("using") == "composite", "Composite action must use 'composite' runner"
    steps = runs.get("steps") or []
    setup_python_steps = [
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]
    assert len(setup_python_steps) == 1, (
        "Composite must wrap exactly one actions/setup-python step "
        f"(found {len(setup_python_steps)})"
    )
    pinned_version = setup_python_steps[0].get("with", {}).get("python-version")
    # Copilot review on PR #2028: a non-empty assertion is too weak — it would
    # accept "${{ inputs.python-version }}", an env reference, or any random
    # string. Pin to the exact literal "3.12" (the canonical project version)
    # so a regression to a passthrough or a typo (e.g. "3.21") fails CI.
    assert pinned_version == "3.12", (
        "Composite must hardcode python-version: \"3.12\" (got "
        f"{pinned_version!r}). The whole point of F-V8-B3.1 is a single "
        "literal source of truth; a passthrough or env reference defeats that."
    )


@pytest.mark.parametrize("workflow_path", _PHASE1_WORKFLOWS, ids=lambda p: p.name)
def test_phase1_workflow_uses_composite_not_raw_setup_python(workflow_path: Path) -> None:
    """Phase-1 workflow must reference the composite and have no raw pin."""
    assert workflow_path.is_file(), f"Phase-1 workflow missing: {workflow_path}"
    workflow = _load(workflow_path)
    jobs = workflow.get("jobs", {}) or {}

    raw_setup_steps: list[tuple[str, int]] = []
    composite_uses_count = 0
    for job_name, job in jobs.items():
        for idx, step in enumerate(job.get("steps", []) or []):
            uses = str(step.get("uses", ""))
            if uses.startswith("actions/setup-python@"):
                raw_setup_steps.append((job_name, idx))
            elif uses == _COMPOSITE_USES_REF:
                composite_uses_count += 1

    assert not raw_setup_steps, (
        f"{workflow_path.name} still uses raw actions/setup-python at "
        f"{raw_setup_steps}; migrate to '{_COMPOSITE_USES_REF}' (F-V8-B3.1)."
    )
    assert composite_uses_count >= 1, (
        f"{workflow_path.name} does not reference '{_COMPOSITE_USES_REF}'; "
        "Phase-1 workflows MUST use the composite."
    )

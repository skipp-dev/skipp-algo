"""Pin the Python bootstrap contract for merge-critical workflows.

The composite action `.github/actions/setup-python-pinned/action.yml` remains
the single literal source of truth for Python 3.12. The merge-critical routed
workflows use that composite only on GitHub-hosted runners, then resolve a
local Python 3.12 interpreter explicitly when the selector chooses the Windows
self-hosted runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COMPOSITE_PATH = _REPO_ROOT / ".github" / "actions" / "setup-python-pinned" / "action.yml"
_MERGE_CRITICAL_WORKFLOWS = (
    _REPO_ROOT / ".github" / "workflows" / "ci.yml",
    _REPO_ROOT / ".github" / "workflows" / "docs-lint.yml",
    _REPO_ROOT / ".github" / "workflows" / "manifest-pytest-poison-scan.yml",
    _REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml",
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


@pytest.mark.parametrize("workflow_path", _MERGE_CRITICAL_WORKFLOWS, ids=lambda p: p.name)
def test_merge_critical_workflow_uses_hosted_bootstrap_and_portable_resolver(workflow_path: Path) -> None:
    """Merge-critical workflow must use hosted-only composite bootstrap and a self-hosted resolver."""
    assert workflow_path.is_file(), f"Merge-critical workflow missing: {workflow_path}"
    workflow = _load(workflow_path)
    jobs = workflow.get("jobs", {}) or {}
    assert "select-runner" in jobs, f"{workflow_path.name} must define select-runner"

    worker_jobs = {
        job_name: job
        for job_name, job in jobs.items()
        if isinstance(job, dict) and job_name != "select-runner"
    }
    assert worker_jobs, f"{workflow_path.name} must have at least one worker job"

    for job_name, job in worker_jobs.items():
        raw_setup_steps: list[tuple[str, int]] = []
        hosted_composite_steps: list[dict] = []
        for idx, step in enumerate(job.get("steps", []) or []):
            uses = str(step.get("uses", ""))
            if uses.startswith("actions/setup-python@"):
                raw_setup_steps.append((job_name, idx))
            elif uses == _COMPOSITE_USES_REF and "github-hosted" in str(step.get("if", "")):
                hosted_composite_steps.append(step)

        assert not raw_setup_steps, (
            f"{workflow_path.name}:{job_name} still uses raw actions/setup-python at "
            f"{raw_setup_steps}."
        )
        assert hosted_composite_steps, (
            f"{workflow_path.name}:{job_name} must use '{_COMPOSITE_USES_REF}' "
            "behind a github-hosted guard."
        )

        resolver_steps = [
            step
            for step in (job.get("steps", []) or [])
            if step.get("name") == "Resolve Python 3.12 interpreter"
        ]
        assert resolver_steps, (
            f"{workflow_path.name}:{job_name} must define a 'Resolve Python 3.12 interpreter' step"
        )
        run_text = str(resolver_steps[0].get("run", ""))
        assert "SMC_PYTHON_BIN" in run_text, (
            f"{workflow_path.name}:{job_name} resolver step must export SMC_PYTHON_BIN"
        )
        assert "py -3.12" in run_text, (
            f"{workflow_path.name}:{job_name} resolver step must probe py -3.12 on self-hosted Windows"
        )
        assert "github-hosted" in run_text, (
            f"{workflow_path.name}:{job_name} resolver step must branch on github-hosted vs self-hosted"
        )
        assert "Self-hosted runner is missing a usable Python 3.12 interpreter" in run_text, (
            f"{workflow_path.name}:{job_name} resolver step must fail loudly when Python 3.12 is unavailable"
        )

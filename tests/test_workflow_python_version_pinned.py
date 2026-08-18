"""Pin the Python bootstrap contract for merge-critical workflows.

The composite action `.github/actions/setup-python-pinned/action.yml` remains
the single literal source of truth for Python 3.12. CI is intentionally
GitHub-hosted. The remaining merge-critical routed workflows use that composite
on GitHub-hosted runners, then resolve a local Python 3.12 interpreter
explicitly when the selector chooses the Windows self-hosted runner.

On self-hosted, routed workflows currently fail loudly when no local Python
3.12 interpreter is found; the operator pre-provisions those runners. The
contract test below also permits a future workflow-local auto-install fallback,
but CI itself is no longer a self-hosted Policy-B example.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COMPOSITE_PATH = _REPO_ROOT / ".github" / "actions" / "setup-python-pinned" / "action.yml"
_HOSTED_ONLY_MERGE_CRITICAL_WORKFLOWS = (
    _REPO_ROOT / ".github" / "workflows" / "ci.yml",
)
_ROUTED_MERGE_CRITICAL_WORKFLOWS = (
    _REPO_ROOT / ".github" / "workflows" / "docs-lint.yml",
    _REPO_ROOT / ".github" / "workflows" / "manifest-pytest-poison-scan.yml",
    _REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml",
)
_COMPOSITE_USES_REF = "./.github/actions/setup-python-pinned"
_HOSTED_RUNS_ON = "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}"


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


@pytest.mark.parametrize("workflow_path", _HOSTED_ONLY_MERGE_CRITICAL_WORKFLOWS, ids=lambda p: p.name)
def test_hosted_only_merge_critical_workflow_uses_pinned_bootstrap(workflow_path: Path) -> None:
    """CI must stay on GitHub-hosted and use the pinned Python composite."""
    assert workflow_path.is_file(), f"Merge-critical workflow missing: {workflow_path}"
    workflow = _load(workflow_path)
    jobs = workflow.get("jobs", {}) or {}
    assert "select-runner" not in jobs, f"{workflow_path.name} must not route CI through self-hosted selector"
    validate = jobs.get("validate")
    assert isinstance(validate, dict), f"{workflow_path.name} must define validate job"
    assert validate.get("runs-on") == _HOSTED_RUNS_ON
    assert any(step.get("uses") == _COMPOSITE_USES_REF for step in validate.get("steps", []) or [])
    assert not any(str(step.get("uses", "")).startswith("actions/setup-python@") for step in validate.get("steps", []) or [])


#: Tokens that mean a step needs the interpreter, so the job must bootstrap the
#: pinned one. Narrow on purpose: `uses:` counts unconditionally because a
#: third-party action may run Python without ever spelling it.
_PYTHON_TOKENS = ("python", "pytest", "pip ", "pip3", "uv ", "coverage")


def _runs_python(job: dict) -> bool:
    """Does this job execute any Python at all?

    Added 2026-08-06 for the `gate` job, whose whole point is to be the one
    thing that cannot fail for an unrelated reason: it checks out nothing,
    installs nothing and reads two `needs.*.result` strings in bash. Requiring
    it to bootstrap an interpreter it never calls would hand the required merge
    check extra ways to break.

    Scoped so a job that DOES touch Python can never slip through: any `uses:`
    at all, or any Python token in a `run:` body, puts the job back in scope.
    """
    for step in job.get("steps", []) or []:
        if step.get("uses"):
            return True
        body = str(step.get("run", "")).lower()
        if any(token in body for token in _PYTHON_TOKENS):
            return True
    return False


@pytest.mark.parametrize("workflow_path", _ROUTED_MERGE_CRITICAL_WORKFLOWS, ids=lambda p: p.name)
def test_merge_critical_workflow_uses_hosted_bootstrap_and_portable_resolver(workflow_path: Path) -> None:
    """Merge-critical workflow must use hosted-only composite bootstrap and a self-hosted resolver."""
    assert workflow_path.is_file(), f"Merge-critical workflow missing: {workflow_path}"
    workflow = _load(workflow_path)
    jobs = workflow.get("jobs", {}) or {}
    assert "select-runner" in jobs, f"{workflow_path.name} must define select-runner"

    worker_jobs = {
        job_name: job
        for job_name, job in jobs.items()
        if isinstance(job, dict) and job_name != "select-runner" and _runs_python(job)
    }
    assert worker_jobs, f"{workflow_path.name} must have at least one worker job"

    for job_name, job in worker_jobs.items():
        raw_setup_steps: list[tuple[str, int]] = []
        hosted_composite_steps: list[dict] = []
        selfhosted_install_composite_steps: list[dict] = []
        for idx, step in enumerate(job.get("steps", []) or []):
            uses = str(step.get("uses", ""))
            if uses.startswith("actions/setup-python@"):
                raw_setup_steps.append((job_name, idx))
            elif uses == _COMPOSITE_USES_REF:
                if_expr = str(step.get("if", ""))
                # Distinguish hosted-only invocation (== 'github-hosted')
                # from the self-hosted install fallback (!= 'github-hosted').
                # Both expressions contain the substring "github-hosted", so
                # comparison-operator detection is required.
                if "== 'github-hosted'" in if_expr or '== "github-hosted"' in if_expr:
                    hosted_composite_steps.append(step)
                elif "!= 'github-hosted'" in if_expr or '!= "github-hosted"' in if_expr:
                    selfhosted_install_composite_steps.append(step)
                elif "github-hosted" in if_expr:
                    # Unknown guard shape — treat as hosted to preserve the
                    # existing-policy assertion below.
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

        # Policy A (loud-fail) OR Policy B (auto-install via composite
        # fallback). Exactly one of these two outcomes must be guaranteed
        # so that downstream steps never silently run without Python 3.12.
        loud_fail_message = "Self-hosted runner is missing a usable Python 3.12 interpreter"
        has_loud_fail = loud_fail_message in run_text
        has_install_fallback = bool(selfhosted_install_composite_steps)
        assert has_loud_fail or has_install_fallback, (
            f"{workflow_path.name}:{job_name} must either fail loudly with the message "
            f"{loud_fail_message!r} when Python 3.12 is missing on self-hosted, "
            f"or install it via the '{_COMPOSITE_USES_REF}' composite as a fallback."
        )


def test_every_workflow_python_version_literal_matches_the_composite() -> None:
    """DERIVED population: no workflow may pin a different interpreter.

    2026-08-18 (Doppelgaenger-Sweep A4): the composite declared itself the
    single source of truth ("3.12") while NINE cron workflows had drifted to a
    hard "3.13" — two interpreters running against one requirements.lock that
    was resolved for exactly one of them. The old guard listed 4 workflows by
    name; this one scans them all, so the next drift fails on the PR that
    introduces it.

    Scope (2026-08-19, review follow-up to #4823): `${{ … }}` expressions
    (matrix REFERENCES, vars) are skipped as deliberate constructs. A matrix
    AXIS that spells versions inline (e.g. ["3.12", "3.13"]) is judged per
    version and named as such — a second interpreter against the one
    requirements.lock is exactly this defect class, so even a matrix must
    arrive via the composite decision. A block-style axis (values on their own
    `- "…"` lines) is refused outright: this scan is line-based on purpose
    (immune to YAML's 3.10-as-float trap) and must not grow a shape it cannot
    read. The vacuity witness counts composite adoptions too, so migrating
    workflows onto `setup-python-pinned` — the preferred fix — never reads as
    a vacuous scan.
    """
    composite = _load(_COMPOSITE_PATH)
    steps = composite["runs"]["steps"]
    pinned = next(
        step["with"]["python-version"]
        for step in steps
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )

    pattern = re.compile(r"python-version:\s*['\"]?([^\s'\"]+)")
    bare_key = re.compile(r"^\s*python-version:\s*$")
    offenders: list[str] = []
    scanned = 0
    composite_adoptions = 0
    workflows_dir = _REPO_ROOT / ".github" / "workflows"
    # *.yml AND *.yaml — GitHub runs both; the sibling population guards
    # (test_workflow_auth_pattern.py etc.) chain both globs for the same reason.
    for workflow in sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]):
        for lineno, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("#")[0]
            if _COMPOSITE_USES_REF in stripped:
                composite_adoptions += 1
                continue
            if bare_key.match(stripped.rstrip()):
                offenders.append(
                    f"{workflow.name}:{lineno} -> block-style python-version list; "
                    "use a flow-style axis this scan can read, or the composite"
                )
                continue
            match = pattern.search(stripped)
            if not match:
                continue
            value = match.group(1)
            if value.startswith("${{"):
                continue  # expression (matrix reference/vars) — a deliberate construct, not a drifted literal
            if value.startswith("["):
                axis_raw = stripped.split(":", 1)[1].strip().strip("[]")
                axis_versions = [
                    v.strip().strip("'\"") for v in axis_raw.split(",") if v.strip().strip("'\"")
                ]
                scanned += len(axis_versions)
                offenders.extend(
                    f"{workflow.name}:{lineno} -> matrix axis {version!r}"
                    for version in axis_versions
                    if version != pinned
                )
                continue
            scanned += 1
            if value != pinned:
                offenders.append(f"{workflow.name}:{lineno} -> {value!r}")
    witness = scanned + composite_adoptions
    assert witness >= 15, (
        f"only {scanned} python-version literals + {composite_adoptions} composite "
        "adoptions found — either the scan went vacuous (glob/regex broke) or the "
        "population truly shrank; if so, lower this floor in the same PR and say why."
    )
    assert not offenders, (
        f"workflows pin a different interpreter than the composite ({pinned!r}): "
        f"{offenders}. Edit the composite to bump the toolchain — never one "
        "workflow alone."
    )

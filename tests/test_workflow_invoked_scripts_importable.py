"""Prevention tests for workflow ↔ scripts/ import contract (F-11 from 2026-04-30 audit).

These tests guard against a class of latent bugs we hit on 2026-04-30:
``scripts/foo.py`` containing ``from scripts.bar import baz`` *before* any
``sys.path.insert(REPO_ROOT)``. The pattern works under
``python -m scripts.foo`` and under pytest (because pyproject.toml sets
``[tool.pytest.ini_options].pythonpath = ["."]``) but crashes with
``ModuleNotFoundError: No module named 'scripts'`` when invoked as
``python scripts/foo.py``, which is exactly what 17 of our workflows do.

These failures were silently masked in CI because many workflow steps
wrap calls in ``set +e ... || true`` or use ``if-no-files-found: ignore``
on the artifact upload — the workflow stays green, but the artifact is
empty. To prevent regressions:

1. ``test_workflows_invoking_scripts_set_pythonpath`` — every workflow
   that direct-invokes ``python scripts/X.py`` must declare
   ``PYTHONPATH`` in its env (workflow-level or job-level). This is the
   structural guard that ensures the import contract.

2. ``test_workflow_invoked_scripts_are_importable`` — for every script
   referenced by ``python scripts/X.py``, run ``--help`` with
   ``PYTHONPATH=REPO_ROOT`` and assert we don't get
   ``ModuleNotFoundError`` on ``scripts``. This is the behavioural guard
   that catches the actual bug class even if the structural guard is
   bypassed.

3. ``test_jobs_invoking_scripts_check_out_the_repo`` — every JOB that
   direct-invokes ``python scripts/X.py`` must run ``actions/checkout``
   before it. Added 2026-08-23: both guards above were green for a script
   that was not on the runner AT ALL. ``tv-post-mutation-verify.yml``
   direct-invoked ``scripts/tv_repair_watchdog_decision.py`` from a job
   with no checkout — the workflow's own header comment said "This job
   checks out nothing" — so the call would have died with ``can't open
   file``, exit 2 under ``set -euo pipefail``, taking the job red and the
   watchdog's dispatch output with it. PYTHONPATH is about *how* a present
   script imports; this is about whether it is present. Sweeping every
   workflow is the positive control: 54 such jobs across 51 workflows,
   exactly one of them without a checkout.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests._subprocess_budget import budget_seconds, overrun_message

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Matches ``python scripts/<name>.py`` and ``python3 scripts/<name>.py`` but
# *not* ``python -m scripts.<name>`` (which doesn't have the same import
# bootstrap problem).
_DIRECT_INVOKE_RE = re.compile(r"\bpython3?\s+(scripts/[A-Za-z0-9_]+\.py)\b")


def _discover_invocations() -> list[tuple[Path, str]]:
    """Return list of (workflow_path, script_relpath) tuples."""
    pairs: list[tuple[Path, str]] = []
    if not WORKFLOW_DIR.is_dir():
        return pairs
    # F1 (audit 2026-05-02): also match `.yaml` so future renames don't silently bypass this guard.
    for wf in sorted(set(WORKFLOW_DIR.glob("*.yml")) | set(WORKFLOW_DIR.glob("*.yaml"))):
        text = wf.read_text(encoding="utf-8")
        for match in _DIRECT_INVOKE_RE.finditer(text):
            pairs.append((wf, match.group(1)))
    return pairs


def _workflow_env_keys(wf: Path) -> set[str]:
    """Collect every env-key declared at workflow- or job-level in a workflow.

    We deliberately do *not* descend into per-step env, because PYTHONPATH
    set on an individual step would not protect sibling steps in the same
    job — the structural guarantee we want is at workflow- or job-level.
    """
    try:
        loaded = yaml.safe_load(wf.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - YAML syntax already covered elsewhere
        pytest.fail(f"{wf.name}: invalid YAML: {exc}")
    if not isinstance(loaded, dict):
        return set()

    keys: set[str] = set()
    top_env = loaded.get("env")
    if isinstance(top_env, dict):
        keys.update(top_env.keys())

    jobs = loaded.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            if isinstance(job, dict):
                job_env = job.get("env")
                if isinstance(job_env, dict):
                    keys.update(job_env.keys())
    return keys


_INVOCATIONS = _discover_invocations()
_WORKFLOWS_INVOKING_SCRIPTS = sorted({wf for wf, _ in _INVOCATIONS})
_UNIQUE_SCRIPTS = sorted({script for _, script in _INVOCATIONS})


def _discover_invoking_jobs() -> list[tuple[Path, str, int | None, int, list[str]]]:
    """Every JOB that direct-invokes ``python scripts/X.py``.

    Returns ``(workflow, job_id, first_checkout_index, first_invoke_index,
    scripts)``. ``first_checkout_index`` is ``None`` when the job has no
    ``actions/checkout`` step at all — the C1 failure shape.

    Parsed per job rather than per file on purpose: a checkout in a *sibling*
    job does not put the script on this job's runner, and each job gets a fresh
    workspace. The one real defect this found lived in a workflow whose other
    jobs would not have helped either — it had none.
    """
    found: list[tuple[Path, str, int | None, int, list[str]]] = []
    if not WORKFLOW_DIR.is_dir():
        return found
    for wf in sorted(set(WORKFLOW_DIR.glob("*.yml")) | set(WORKFLOW_DIR.glob("*.yaml"))):
        try:
            loaded = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - covered elsewhere
            pytest.fail(f"{wf.name}: invalid YAML: {exc}")
        if not isinstance(loaded, dict):
            continue
        jobs = loaded.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                # A `uses:` job calls a reusable workflow; that file is swept
                # on its own pass.
                continue
            checkout_at: int | None = None
            invoke_at: int | None = None
            scripts: list[str] = []
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if (
                    isinstance(uses, str)
                    and uses.split("@", 1)[0].strip() == "actions/checkout"
                    and checkout_at is None
                ):
                    checkout_at = index
                run = step.get("run")
                if isinstance(run, str):
                    for match in _DIRECT_INVOKE_RE.finditer(run):
                        scripts.append(match.group(1))
                        if invoke_at is None:
                            invoke_at = index
            if invoke_at is not None:
                found.append((wf, str(job_id), checkout_at, invoke_at, sorted(set(scripts))))
    return found


_INVOKING_JOBS = _discover_invoking_jobs()


def test_at_least_one_workflow_invokes_scripts_directly() -> None:
    """Sanity check: if this becomes empty, the discovery regex regressed."""
    assert _INVOCATIONS, (
        "Expected to discover at least one ``python scripts/X.py`` "
        "invocation across .github/workflows/. Either every workflow "
        "switched to ``python -m scripts.X`` (great — delete this test) "
        "or the regex regressed."
    )


@pytest.mark.parametrize("workflow", _WORKFLOWS_INVOKING_SCRIPTS, ids=lambda p: p.name)
def test_workflows_invoking_scripts_set_pythonpath(workflow: Path) -> None:
    """F-01 structural guard.

    Any workflow that runs ``python scripts/X.py`` must declare
    ``PYTHONPATH`` in its env (workflow-level or job-level), otherwise
    the script crashes with ``ModuleNotFoundError: No module named
    'scripts'`` for any module that does ``from scripts.<x> import …``
    before bootstrapping ``sys.path``.

    The canonical declaration is::

        env:
          PYTHONPATH: ${{ github.workspace }}

    placed at workflow level so it propagates to every job/step.
    """
    keys = _workflow_env_keys(workflow)
    assert "PYTHONPATH" in keys, (
        f"{workflow.name} runs ``python scripts/X.py`` but does not "
        f"declare PYTHONPATH at workflow- or job-level env. Without "
        f"this, scripts that do ``from scripts.<x> import …`` crash "
        f"with ``ModuleNotFoundError: No module named 'scripts'``. "
        f"Add to the workflow:\n\n"
        f"  env:\n"
        f"    PYTHONPATH: ${{{{ github.workspace }}}}\n"
    )


def test_the_invoking_job_sweep_covers_every_invoking_workflow() -> None:
    """Positive control for the per-job parser.

    The whole-file regex above and the YAML walk below must agree on WHICH
    workflows invoke a script. If the walk silently stopped seeing a workflow —
    a schema change, an anchor, a job shape it does not handle — the checkout
    guard would go quietly vacuous for it, which is precisely the failure mode
    that let C1 through in the first place.
    """
    assert _INVOKING_JOBS, "the per-job sweep found nothing — the YAML walk regressed"
    from_regex = {wf.name for wf in _WORKFLOWS_INVOKING_SCRIPTS}
    from_walk = {wf.name for wf, _, _, _, _ in _INVOKING_JOBS}
    assert from_regex == from_walk, (
        "the whole-file regex and the per-job YAML walk disagree about which "
        "workflows direct-invoke a scripts/*.py. Only seen by the regex: "
        f"{sorted(from_regex - from_walk)}; only by the walk: "
        f"{sorted(from_walk - from_regex)}. Every workflow the regex sees must "
        "be reachable by the walk, or the checkout guard below is blind to it."
    )


@pytest.mark.parametrize(
    ("workflow", "job_id", "checkout_at", "invoke_at", "scripts"),
    _INVOKING_JOBS,
    ids=[f"{wf.name}::{job}" for wf, job, _, _, _ in _INVOKING_JOBS],
)
def test_jobs_invoking_scripts_check_out_the_repo(
    workflow: Path,
    job_id: str,
    checkout_at: int | None,
    invoke_at: int,
    scripts: list[str],
) -> None:
    """C1 guard (2026-08-23): the script has to BE on the runner.

    PYTHONPATH answers "how does a present script import its siblings". It
    says nothing about presence, and it was declared — correctly — in the very
    workflow whose job had no checkout. Both existing guards were green while
    the invocation could only ever have produced ``can't open file``.

    The checkout must also come BEFORE the invocation, and not merely exist in
    the job: ``actions/checkout`` defaults to ``clean: true`` (``git clean
    -ffdx``), so a checkout placed after a step that downloaded an artifact
    into the workspace deletes it. Measured over the whole population when
    this was written: 54 invoking jobs, 0 of them ordered the other way, so
    the stricter rule costs nothing today and closes the hole for tomorrow.
    """
    assert checkout_at is not None, (
        f"{workflow.name}::{job_id} runs {scripts} but has no actions/checkout "
        f"step. The job's workspace is empty, so the invocation fails with "
        f"``can't open file '<workspace>/{scripts[0]}'`` (exit 2, which takes "
        f"the whole step down under ``set -euo pipefail``). Add:\n\n"
        f"  - name: Checkout\n"
        f"    uses: actions/checkout@<sha> # v7\n"
        f"    with:\n"
        f"      persist-credentials: false\n"
    )
    assert checkout_at < invoke_at, (
        f"{workflow.name}::{job_id} checks out at step {checkout_at} but "
        f"already invokes {scripts} at step {invoke_at}. Move the checkout "
        f"ahead of the invocation — and note that actions/checkout cleans the "
        f"workspace (git clean -ffdx), so a late checkout can also delete "
        f"artifacts an earlier step downloaded."
    )


@pytest.mark.parametrize("script_relpath", _UNIQUE_SCRIPTS)
def test_workflow_invoked_scripts_are_importable(script_relpath: str) -> None:
    """F-01 behavioural guard.

    For every ``scripts/X.py`` referenced by a workflow, verify that
    ``python scripts/X.py --help`` does not crash with
    ``ModuleNotFoundError`` on ``scripts``. We deliberately set
    ``PYTHONPATH=REPO_ROOT`` to mirror the workflow-level fix; if a
    script fails *with* ``PYTHONPATH`` already set, the bug is more
    severe than just import-order drift and demands a real fix.

    We accept any non-import-error exit (including argparse exit 2 for
    unknown flags) because some scripts deliberately reject ``--help``
    in favour of subcommand parsers. Only ``ModuleNotFoundError`` /
    ``ImportError`` on ``scripts`` is treated as failure.
    """
    script_path = REPO_ROOT / script_relpath
    # If a workflow references a script that does not exist, that is a real
    # bug (the workflow will fail at runtime). Fail the test instead of
    # skipping so it shows up in the pytest.skip budget ledger as zero.
    assert script_path.exists(), (
        f"{script_relpath} referenced by workflow but missing in tree"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Avoid touching real cache/state directories during --help probes.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    proc = subprocess.Popen(
        [sys.executable, str(script_path), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        start_new_session=True,
    )
    probe_budget = budget_seconds(60)
    try:
        stdout, stderr = proc.communicate(timeout=probe_budget)
    except subprocess.TimeoutExpired:
        # Killing only the direct child can leave grandchildren holding the
        # captured stdout/stderr pipes open forever.  That made main CI reach
        # 99% and then sit until the 45-minute job timeout.  The probe owns a
        # fresh process group, so terminate the whole group before draining.
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        # Do not blame the script: this probe shares a machine with ~89
        # sibling interpreters and the overrun is usually starvation
        # (2026-08-29). The whole process group is killed either way.
        pytest.fail(
            overrun_message(
                f"{script_relpath} --help",
                probe_budget,
                detail=f"--- stdout ---\n{stdout}\n\n--- stderr ---\n{stderr}\n",
            )
        )
    combined = (stdout or "") + "\n" + (stderr or "")
    if "ModuleNotFoundError: No module named 'scripts'" in combined:
        pytest.fail(
            f"{script_relpath} crashes with ``ModuleNotFoundError: No "
            f"module named 'scripts'`` even with PYTHONPATH set. This "
            f"indicates a deeper packaging issue than F-01.\n\n"
            f"--- stderr ---\n{stderr}\n"
        )
    # ImportError variants that explicitly mention 'scripts' are also F-01-like.
    if "ImportError" in combined and "scripts" in combined and "from scripts" in combined:
        pytest.fail(
            f"{script_relpath} cannot import a sibling under scripts/ "
            f"even with PYTHONPATH set:\n\n"
            f"--- stderr ---\n{stderr}\n"
        )

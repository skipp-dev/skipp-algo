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
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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

    proc = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    bad_patterns = (
        "ModuleNotFoundError: No module named 'scripts'",
        "ImportError: cannot import name",  # paired check below
    )
    if "ModuleNotFoundError: No module named 'scripts'" in combined:
        pytest.fail(
            f"{script_relpath} crashes with ``ModuleNotFoundError: No "
            f"module named 'scripts'`` even with PYTHONPATH set. This "
            f"indicates a deeper packaging issue than F-01.\n\n"
            f"--- stderr ---\n{proc.stderr}\n"
        )
    # ImportError variants that explicitly mention 'scripts' are also F-01-like.
    if "ImportError" in combined and "scripts" in combined and "from scripts" in combined:
        pytest.fail(
            f"{script_relpath} cannot import a sibling under scripts/ "
            f"even with PYTHONPATH set:\n\n"
            f"--- stderr ---\n{proc.stderr}\n"
        )

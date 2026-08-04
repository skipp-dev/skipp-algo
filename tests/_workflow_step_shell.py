"""Execute one workflow step's shell instead of reading its text.

``tests/_fast_gates_gate.py`` does this for the two gate steps that decide
whether the heavy suite runs. The same blind spot exists wherever a step
decides something in shell and a test asserts on the source: a substring test
cannot tell "publishes on push" from "never publishes".

Measured on 2026-08-04 against the two Grafana publishers, both of which sit on
the required lane (``tests/_fast_inventory.py`` lines 72-74):

* ``live-overlay-alert-rules-publish.yml`` -- inverting
  ``if [[ "${dry_run}" == "true" ]]`` to ``== "false"`` makes every push to
  ``main`` exit before the upsert, so committed alert-rule changes stop
  reaching Grafana entirely. That is verbatim the gap the workflow's own header
  says it was built to close. All five assertions in
  ``test_upsert_step_contract`` stay green: none of them names that line.
* ``live-overlay-dashboard-publish.yml`` -- same inversion, same silence.

So run the block. This module keeps the shell contract in one place; the
assertions live next to the workflow they describe.

Deliberately generic: 42 decision steps across 37 workflows write to
``$GITHUB_OUTPUT`` or branch in shell, and exactly two of them were executed by
a test before this module existed.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# What Actions expands `defaults: run: shell: bash` to -- NOT the implicit
# default (`bash -e {0}`, no pipefail). Steps under a workflow that declares the
# default rely on pipefail, and running them without it would hide exactly the
# failures these tests exist to catch. Pinned here and asserted against the
# workflow's own declaration by the callers.
BASH = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")


@dataclass(frozen=True)
class StepRun:
    """What the step did, rather than what its source says it does."""

    returncode: int
    stdout: str
    stderr: str
    calls: tuple[str, ...]  # one line per stubbed-executable invocation, argv joined
    outputs: dict[str, str]  # whatever it wrote to $GITHUB_OUTPUT

    def called_with(self, *fragments: str) -> tuple[str, ...]:
        """Every recorded call containing all of ``fragments``."""
        return tuple(c for c in self.calls if all(f in c for f in fragments))


def step_by_name(workflow: str, name: str) -> dict:
    """One step, located structurally.

    Loaded through YAML rather than sliced out of the text, so indentation and
    comment churn cannot break it, and a renamed step is a named failure rather
    than a silently empty script.
    """
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == name:
                return dict(step)
    raise AssertionError(f"{workflow} has no step named {name!r}")


def declares_bash_default(workflow: str) -> bool:
    """True iff the workflow sets ``defaults: run: shell: bash``.

    Pinned by the callers alongside :data:`BASH`. Pinning only one side leaves
    the other free to drift -- a review measured exactly that on the fast-gates
    harness, where gutting the shell tuple killed no test.
    """
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return ((doc.get("defaults") or {}).get("run") or {}).get("shell") == "bash"


def run_step(
    workflow: str,
    step_name: str,
    tmp_path: Path,
    *,
    env: dict[str, str],
    stubs: dict[str, int] | None = None,
) -> StepRun:
    """Run the step's shell with ``stubs`` shadowing real executables.

    ``stubs`` maps an executable name to the exit code its stub returns. Every
    invocation is appended to a log with its full argv, so a test can assert on
    *what the step actually asked for* -- e.g. that a real publish ran, not just
    that the word "publish" appears in the source.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")

    for name, exit_code in (stubs or {}).items():
        stub = bin_dir / name
        # `printf '%s '` over "$@" rather than `echo "$*"`: a dashboard path
        # beginning with `-e` would otherwise be eaten by echo instead of
        # recorded, and this harness's whole job is to have no blind spots.
        stub.write_text(
            "#!/bin/sh\n"
            f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{call_log}"\n'
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")

    result = subprocess.run(
        [*BASH, "-c", str(step_by_name(workflow, step_name)["run"])],
        # Deliberately not `{**os.environ, ...}`: `bash -c` sources BASH_ENV
        # even under --noprofile --norc, so a developer's shell could change
        # what this measures. PATH is kept, stub dir first, because the step
        # legitimately needs to find the tools it shadows.
        env={
            **env,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_OUTPUT": str(github_output),
        },
        capture_output=True,
        text=True,
        cwd=tmp_path,
        # These blocks are branch logic over stubs; anything slower is a hang,
        # and a hang would burn the job's whole timeout instead of failing.
        timeout=60,
    )

    return StepRun(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        calls=tuple(
            line.strip()
            for line in call_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ),
        outputs=dict(
            line.split("=", 1)
            for line in github_output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        ),
    )

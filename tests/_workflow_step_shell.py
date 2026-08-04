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
import re
import shlex
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
class Stub:
    """What a shadowed executable should do when the step calls it.

    ``exit_code`` alone covers steps that only branch on success. ``stdout``
    matters for steps that branch on what a command *says* -- ``git status
    --porcelain`` reporting a dirty tree, a manifest reader printing ``True``.
    ``passthrough`` runs the real interpreter instead, for blocks whose decision
    is a genuine computation worth exercising rather than faking.
    """

    exit_code: int = 0
    stdout: str = ""
    passthrough: str = ""
    script: str = ""  # raw shell, receives "$@"; for tools answering per-argument


@dataclass(frozen=True)
class StepRun:
    """What the step did, rather than what its source says it does."""

    returncode: int
    stdout: str
    stderr: str
    calls: tuple[str, ...]  # one line per stubbed-executable invocation, argv joined
    outputs: dict[str, str]  # whatever it wrote to $GITHUB_OUTPUT
    env_file: dict[str, str]  # whatever it wrote to $GITHUB_ENV, for later steps
    summary: str  # whatever it wrote to $GITHUB_STEP_SUMMARY -- the operator's surface

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


def _expand(run_block: str, expressions: dict[str, str] | None) -> str:
    """Substitute ``${{ … }}`` the way Actions does before bash ever sees it.

    A leftover expression is a hard failure, not a shrug: bash reads ``${{`` as
    a bad substitution and kills the step, which would look like a finding about
    the workflow when it is really a gap in this harness.
    """
    expanded = run_block
    for expression, value in (expressions or {}).items():
        expanded = re.sub(
            r"\$\{\{\s*" + re.escape(expression) + r"\s*\}\}", value.replace("\\", "\\\\"), expanded
        )
    leftover = re.findall(r"\$\{\{\s*(.+?)\s*\}\}", expanded)
    assert not leftover, (
        f"this step interpolates {sorted(set(leftover))}, which Actions resolves "
        "before the shell runs. Pass them via `expressions=` — running the block "
        "with them unresolved measures a syntax error, not the step."
    )
    return expanded


def run_step(
    workflow: str,
    step_name: str,
    tmp_path: Path,
    *,
    env: dict[str, str],
    stubs: dict[str, int | Stub] | None = None,
    expressions: dict[str, str] | None = None,
) -> StepRun:
    """Run the step's shell with ``stubs`` shadowing real executables.

    ``stubs`` maps an executable name to an exit code or to a :class:`Stub`.
    Every invocation is appended to a log with its full argv, so a test can
    assert on *what the step actually asked for* -- e.g. that a real publish
    ran, not just that the word "publish" appears in the source.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")

    for name, spec in (stubs or {}).items():
        stub_spec = spec if isinstance(spec, Stub) else Stub(exit_code=spec)
        stub = bin_dir / name
        # `printf '%s '` over "$@" rather than `echo "$*"`: an argument
        # beginning with `-e` would otherwise be eaten by echo instead of
        # recorded, and this harness's whole job is to have no blind spots.
        body = "#!/bin/sh\n" f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{call_log}"\n'
        if stub_spec.script:
            body += stub_spec.script.rstrip() + "\n"
        elif stub_spec.passthrough:
            body += f'exec {shlex.quote(stub_spec.passthrough)} "$@"\n'
        else:
            if stub_spec.stdout:
                body += f"printf '%s\\n' {shlex.quote(stub_spec.stdout)}\n"
            body += f"exit {stub_spec.exit_code}\n"
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")
    # Steps that stamp a value for LATER steps write to $GITHUB_ENV, not
    # $GITHUB_OUTPUT. Without it they die on an unset variable under `-u`, and
    # the decision they also publish would never be measured.
    github_env = tmp_path / "github_env"
    github_env.write_text("", encoding="utf-8")
    # The run UI. A step that blocks something and says so only here is still
    # saying it: asserting on the source text of that block cannot tell an
    # emitted explanation from a never-reached one.
    step_summary = tmp_path / "step_summary"
    step_summary.write_text("", encoding="utf-8")

    result = subprocess.run(
        [*BASH, "-c", _expand(str(step_by_name(workflow, step_name)["run"]), expressions)],
        # Deliberately not `{**os.environ, ...}`: `bash -c` sources BASH_ENV
        # even under --noprofile --norc, so a developer's shell could change
        # what this measures. PATH is kept, stub dir first, because the step
        # legitimately needs to find the tools it shadows.
        env={
            **env,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_ENV": str(github_env),
            "GITHUB_STEP_SUMMARY": str(step_summary),
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
        summary=step_summary.read_text(encoding="utf-8"),
        env_file=dict(
            line.split("=", 1)
            for line in github_env.read_text(encoding="utf-8").splitlines()
            if "=" in line
        ),
    )

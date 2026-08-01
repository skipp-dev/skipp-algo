"""A workflow that uses ``$SMC_PYTHON_BIN`` must also set it.

``.github/actions/setup-python-pinned`` puts the canonical interpreter on PATH
but does NOT export ``SMC_PYTHON_BIN``; each workflow resolves it in a step of
its own (``echo "SMC_PYTHON_BIN=python" >> "$GITHUB_ENV"``).

``smc-r4-context-readback.yml`` referenced ``"$SMC_PYTHON_BIN"`` in four steps
and never set it. The shell expanded it to the empty string, so
``"" - <<'PY'`` exited 127 ("command not found") and the workflow could not
complete a single run — the failure only surfaced on the first real dispatch
(run 30683763421, 2026-08-01), because nothing in CI executes a
workflow_dispatch-only workflow.

That is the same class as the guards already on the required path: a workflow
which is structurally broken but never exercised looks healthy until the day
someone needs it. This check reads the YAML instead of running it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Uses the variable: "$SMC_PYTHON_BIN" / ${SMC_PYTHON_BIN} / $SMC_PYTHON_BIN.
_USES = re.compile(r"\$\{?SMC_PYTHON_BIN\}?")
# Sets it: shell export into $GITHUB_ENV, a job-level env: mapping, or an
# action input receiving it.
_SETS = re.compile(r"SMC_PYTHON_BIN\s*[:=]")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def test_the_workflow_corpus_is_not_empty() -> None:
    """A glob that matched nothing would make every assertion below vacuous."""
    files = _workflow_files()
    assert len(files) > 20, f"only {len(files)} workflow files found — glob broken?"


def test_every_workflow_that_uses_the_interpreter_var_also_resolves_it() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if not _USES.search(text):
            continue
        # Strip the uses so a bare reference cannot satisfy the setter regex.
        without_uses = _USES.sub("", text)
        if not _SETS.search(without_uses):
            offenders.append(path.name)

    assert not offenders, (
        "Workflow(s) reference $SMC_PYTHON_BIN without ever setting it. The "
        "shell expands it to the empty string, so a heredoc step exits 127 and "
        "the workflow cannot complete a run:\n\n"
        + "\n".join(f"  - {name}" for name in offenders)
        + "\n\nAdd a resolve step after ./.github/actions/setup-python-pinned:\n"
        '    echo "SMC_PYTHON_BIN=python" >> "$GITHUB_ENV"'
    )


def test_the_readback_workflow_resolves_it_after_the_python_setup() -> None:
    """Order matters: resolving before setup-python-pinned would pin the wrong one."""
    text = (WORKFLOWS / "smc-r4-context-readback.yml").read_text(encoding="utf-8")
    setup = text.index("./.github/actions/setup-python-pinned")
    resolve = text.index('echo "SMC_PYTHON_BIN=python" >> "$GITHUB_ENV"')
    first_use = _USES.search(text, resolve)
    assert setup < resolve, "SMC_PYTHON_BIN is resolved before the interpreter is set up"
    assert first_use is not None, "the workflow no longer uses SMC_PYTHON_BIN"
    assert resolve < first_use.start(), "SMC_PYTHON_BIN is used before it is resolved"

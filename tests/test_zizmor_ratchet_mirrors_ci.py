"""The local zizmor ratchet must measure what CI measures.

``scripts/run_zizmor_ratchet.sh`` calls itself a "local mirror of the
authoritative fast-gates step". Nothing checked that it still was one.

Measured 2026-08-04, while widening the CI scan from ``.github/workflows/`` to
all three action-pin surfaces: the script had ``WORKFLOW_DIR`` hardcoded, so it
would have kept counting 91 High findings against a budget of 93 — passing
locally, on a smaller corpus than CI, with no signal that the two had diverged.
A mirror that stops mirroring reports success either way, which is the whole
reason this repo treats "green without observing anything" as a bug class.

The script already derived the budgets and the pinned zizmor version from the
step rather than duplicating them, and its header says why ("single source of
truth ... never hardcode them here"). The scan paths were the one thing it did
duplicate. Now it derives those too, and this pins the property rather than the
implementation: whatever the step scans, the script must scan.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_SCRIPT_REL = "scripts/run_zizmor_ratchet.sh"
_WORKFLOW_REL = ".github/workflows/smc-fast-pr-gates.yml"
_STEP_NAME = "zizmor (workflow security ratchet)"

# `.github/<something>/`, the shape every scan argument has.
_GITHUB_DIR = re.compile(r"\.github/[A-Za-z0-9_./-]+/")


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _step_body() -> str:
    """The zizmor step's lines, sliced the same way the script slices them.

    Deliberately the same stateful range the shell uses (start after the step
    name, stop at the next step-level ``- name:``): a test that located the step
    differently could agree with a script that no longer finds it at all.
    """
    lines = (_repo_root() / _WORKFLOW_REL).read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if f"- name: {_STEP_NAME}" in line:
            capturing = True
            continue
        if capturing and re.match(r"^      - name:", line):
            break
        if capturing:
            out.append(line)
    return "\n".join(out)


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"\s*#.*$", "", line) for line in text.splitlines())


def _scanned_by_ci() -> set[str]:
    return set(_GITHUB_DIR.findall(_strip_comments(_step_body())))


_ARRAY_MARKER = "SCAN_PATH_ARRAY=($SCAN_PATHS)"


def _scanned_by_script() -> set[str]:
    """What the script would scan — by EXECUTING the script's own code.

    The first version of this helper re-implemented the extraction pipeline
    (``sed | grep -oE | sort -u``) and fed it the step body. That measured the
    CI step against itself: hardcoding ``SCAN_PATHS=".github/workflows/"`` in
    the script left this test green, verified 2026-08-04 by doing exactly that.
    A re-implementation always agrees with a script it never runs.

    So run the real thing: take the script verbatim up to and including the
    array assignment, append an echo, and execute it. Whatever the script would
    hand zizmor is what comes back — derived, hardcoded, or empty.
    """
    root = _repo_root()
    script = (root / _SCRIPT_REL).read_text(encoding="utf-8")
    assert _ARRAY_MARKER in script, (
        f"{_SCRIPT_REL} no longer builds {_ARRAY_MARKER!r}. This guard executes "
        "the script's own prefix to learn what it scans; without that anchor it "
        "cannot observe anything, so the parity claim would be unfounded."
    )
    prefix = script[: script.index(_ARRAY_MARKER) + len(_ARRAY_MARKER)]
    proc = subprocess.run(
        ["bash", "-c", prefix + '\nprintf "%s\\n" "${SCAN_PATH_ARRAY[@]}"'],
        capture_output=True,
        text=True,
        cwd=root,
    )
    assert proc.returncode == 0, (
        f"the script's own path extraction failed (rc={proc.returncode}). It would "
        f"abort in the pre-commit hook too.\n{proc.stderr}"
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def test_the_step_is_still_findable() -> None:
    """The premise. An unfindable step makes every set below empty and equal."""
    body = _step_body()
    assert body.strip(), (
        f"no step named {_STEP_NAME!r} found in {_WORKFLOW_REL}. Both this guard "
        "and the script locate it by that exact name; renamed, they would agree "
        "on nothing and pass."
    )
    assert "zizmor" in body, "the located block does not look like the zizmor step"


def test_ci_scans_at_least_the_three_action_pin_surfaces() -> None:
    """A floor, so shrinking the CI scan is a decision and not an accident.

    Composite actions and workflow templates carry `uses:` pins that the Python
    guards read but zizmor's `unpinned-uses` audit — a High finding — is what
    actually catches a mutable tag there.
    """
    scanned = _scanned_by_ci()
    for required in (".github/workflows/", ".github/actions/", ".github/workflow-templates/"):
        assert required in scanned, (
            f"the zizmor step no longer scans {required}; findings there stop "
            f"counting against the ratchet without any budget change. Scans: {sorted(scanned)}"
        )


def test_the_local_mirror_scans_exactly_what_ci_scans() -> None:
    """The property, not the implementation: same corpus, either direction."""
    ci = _scanned_by_ci()
    script = _scanned_by_script()
    assert ci, "extracted no scan path from the CI step — nothing was compared"
    assert script == ci, (
        "the local ratchet and the CI step scan different corpora, so a clean "
        "local run says nothing about CI (and vice versa).\n"
        f"  CI only:     {sorted(ci - script)}\n"
        f"  script only: {sorted(script - ci)}"
    )

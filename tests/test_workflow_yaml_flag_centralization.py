"""YAML workflow feature-flag centralization guard (audit F-003-YAML).

Companion to ``test_feature_flag_centralization.py`` which covers Python source.
This module covers GitHub Actions workflow YAML files.

Enforces that ENABLE_* flags in workflow ``env:`` blocks are always sourced
from GHA expressions (``${{ vars.ENABLE_* }}``, ``${{ secrets.ENABLE_* }}``,
or ``${{ inputs.ENABLE_* }}``) and never hard-coded to literal boolean or
integer values.

Hard-coded literals have three failure modes:
  1. Flag state is invisible in the GitHub Variables UI — operators cannot see
     or toggle the flag without a code change + PR + CI cycle.
  2. They bypass ``open_prep/feature_flags.py`` (the Python SSOT), making it
     possible for the workflow to run with a flag state that differs from what
     the Python runtime sees at execution time.
  3. They recreate the four-callsite drift risk that audit-L-1 R4 (2026-05-12)
     identified and fixed — a "local patch" that diverges from the canonical
     value over time.

Allowed patterns
----------------
    ENABLE_FOO: ${{ vars.ENABLE_FOO }}        # GitHub Variables (preferred)
    ENABLE_FOO: ${{ secrets.ENABLE_FOO }}     # GitHub Secrets (if sensitive)
    ENABLE_FOO: ${{ inputs.enable_foo }}      # workflow_dispatch input

Disallowed patterns
-------------------
    ENABLE_FOO: "true"
    ENABLE_FOO: 'false'
    ENABLE_FOO: 1
    ENABLE_FOO: "0"
    ENABLE_FOO: yes   # YAML boolean alias
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO / ".github" / "workflows"

# Matches ENABLE_* env keys with any of the common literal boolean/integer
# representations.  Anchored to a full line (stripped) so partial-key hits
# like "ENABLE_FOO_DESCRIPTION: some_literal" do not match.
_HARDCODED_ENABLE_RE = re.compile(
    r"""^\s*ENABLE_[A-Z0-9_]+\s*:\s*(?:[\"']?(?:true|false|yes|no|1|0)[\"']?)\s*$""",
    re.IGNORECASE | re.MULTILINE,
)


def _collect_violations() -> list[str]:
    """Return 'workflow.yml:NN: ENABLE_FOO: "true"' for each violation."""
    violations: list[str] = []
    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            text = wf_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _HARDCODED_ENABLE_RE.search(line):
                violations.append(f"  {wf_path.name}:{lineno}: {line.strip()}")
    return violations


# ---------------------------------------------------------------------------
# Guard tests
# ---------------------------------------------------------------------------


def test_no_hardcoded_enable_flags_in_yaml_workflows() -> None:
    """No workflow env: block may set ENABLE_* to a hardcoded literal.

    Replace with ``${{ vars.ENABLE_<FLAG> }}`` (GitHub Variables) so the value
    is visible in the GH UI and consistent with the Python SSOT.

    See module docstring for rationale and allowed/disallowed patterns.
    """
    violations = _collect_violations()
    assert not violations, (
        "Hard-coded ENABLE_* literal found in a GitHub Actions workflow env: block.\n"
        "Replace with ${{ vars.ENABLE_<FLAG> }} (GitHub Variables) so the flag\n"
        "state is visible in the UI and consistent with open_prep/feature_flags.py:\n"
        + "\n".join(violations)
    )


def test_workflow_yaml_files_are_valid_utf8() -> None:
    """All workflow files must be valid UTF-8.

    PyYAML with errors='replace' silently masks encoding issues; GHA itself
    requires UTF-8 and will reject files with invalid byte sequences.
    """
    bad: list[str] = []
    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            wf_path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError) as exc:
            bad.append(f"  {wf_path.name}: {exc}")
    assert not bad, (
        "Workflow files with non-UTF-8 content found:\n" + "\n".join(bad)
    )


# ---------------------------------------------------------------------------
# Regex self-tests — document exact match semantics and prevent false positives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        '      ENABLE_OPRA_UOA: "true"',
        "      ENABLE_OPRA_UOA: 'false'",
        "      ENABLE_OPRA_UOA: 1",
        "      ENABLE_OPRA_UOA: 0",
        "      ENABLE_OPRA_UOA: yes",
        "      ENABLE_OPRA_UOA: no",
        "      ENABLE_OPRA_UOA: True",
        "      ENABLE_OPRA_UOA: FALSE",
        '      ENABLE_MY_FLAG: "1"',
    ],
)
def test_hardcoded_enable_regex_catches_violations(line: str) -> None:
    """_HARDCODED_ENABLE_RE must match known-bad patterns."""
    assert _HARDCODED_ENABLE_RE.search(line), (
        f"Regex did not catch violation: {line!r}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "      ENABLE_OPRA_UOA: ${{ vars.ENABLE_OPRA_UOA }}",
        "      ENABLE_OPRA_UOA: ${{ secrets.ENABLE_OPRA_UOA }}",
        "      ENABLE_OPRA_UOA: ${{ inputs.enable_opra_uoa }}",
        # A description field that happens to contain a word starting ENABLE_ but
        # is not a key:
        "      # ENABLE_FOO would normally be 'true' here",
        # Different prefix — not ENABLE_*:
        "      FEATURE_FOO: 'true'",
        "      ALLOW_FOO: 1",
    ],
)
def test_hardcoded_enable_regex_does_not_catch_allowlist(line: str) -> None:
    """_HARDCODED_ENABLE_RE must NOT match allowed/unrelated patterns."""
    assert not _HARDCODED_ENABLE_RE.search(line), (
        f"Regex false-positive on: {line!r}"
    )

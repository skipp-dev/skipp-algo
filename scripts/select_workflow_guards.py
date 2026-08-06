#!/usr/bin/env python3
"""Select the guards that read a workflow a pull request changed.

2026-08-01, three times in one day, a green PR changed a workflow and broke a
guard that reads it but is not on the fast-gates list:

* #4285/#4288 -- ``smc-r4-context-readback.yml`` used ``$SMC_PYTHON_BIN``
  without setting it; the workflow could not complete a single run.
* #4291 -- the same workflow declared ``manual-dispatch-only``, outside the
  closed live-window vocabulary.
* #4302 -- ``smc-library-refresh.yml`` joined the shared TradingView session
  group while a second pin still demanded the per-ref one.

Each was repaired by adding one more file to the roster, which closes the
instance and not the class.

A roster rule cannot close the class, and this was measured before it was
believed: 571 test files read a workflow and 484 are unlisted, so "every
workflow guard must be gated" is a gate rebuild; and "no workflow may have
mixed registration" flags 17 workflows whose gated side is merely a repo-wide
sweep, so it fires on the normal state rather than the defect.

Scope it to the diff instead. A PR that touches no workflow selects nothing; a
PR that touches one runs every guard that reads it, whether or not anyone
remembered to list that guard.

Two ways a guard reads a workflow, and BOTH are needed -- checked against the
three cases above, where matching only the first would have caught one of them:

1. by name -- ``smc-library-refresh.yml``, or the bare stem, because
   ``test_workflow_databento_handoff_concurrency.py`` stores
   ``"smc-library-refresh"`` and appends the extension itself;
2. by enumeration -- ``WORKFLOWS.glob("*.yml")``, as
   ``test_workflow_live_window_posture.py`` does. Such a guard names no
   workflow at all, so any workflow change has to select it.

Over-selection is deliberate on the cheap side: a stem like ``ci`` will match
files that merely quote the word. That costs seconds of runtime. Under-selection
costs a red main after the merge.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
WORKFLOW_DIR = "workflows"

# `.github` plus `workflows` in one file is what "reads a workflow" looks like;
# every guard in the repo builds the path that way.
_READS_WORKFLOWS = (".github", WORKFLOW_DIR)
_ENUMERATES = re.compile(r"\b(?:r?glob|iterdir)\s*\(")

# CI surfaces that are not workflows but that guards read the same way.
#
# Measured 2026-08-06, after a PR editing `.github/dependabot.yml` selected
# nothing: the mechanism above handles any `.yml`, but `_reads_workflows`
# demands the literal token `workflows`, which a dependabot guard has no reason
# to contain. So the gap was two-sided — the step fed only
# `.github/workflows/`, AND the readability test was wired to workflows.
#
# A surface list, NOT a guard roster. The module docstring's objection stands:
# a roster of guards cannot close the class, because it goes stale silently
# every time someone adds one. A roster of SURFACES is bounded by what CI reads
# and changes maybe twice a year. And it has to be a list rather than "any
# changed file", because matching by bare filename makes `README.md` select 17
# tests (measured) and destroys the cost model that a PR touching no CI surface
# pays nothing.
#
# Deliberately absent, both measured the same day:
#   * `pin_registry.toml` — 14 readers, all already pinned on the required
#     path, so selecting them again buys runtime and no signal.
#   * `.pre-commit-config.yaml` — zero tests read it. An entry here would
#     select nothing and merely look like coverage.
_CONFIG_SURFACES = (
    ".github/dependabot.yml",
    ".github/actions/*/action.yml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
)


def _reads_workflows(text: str) -> bool:
    return all(token in text for token in _READS_WORKFLOWS)


def _enumerates_workflows(text: str) -> bool:
    """A guard that walks the directory names no workflow, so nothing else selects it."""
    return _reads_workflows(text) and bool(_ENUMERATES.search(text))


def _names(text: str, stem: str) -> bool:
    """The stem delimited by a quote or a slash, with the extension optional.

    Delimiters keep ``smc-library-refresh`` from matching
    ``smc-library-refresh-producer``; the optional extension is what catches the
    guards that store a bare name and append ``.yml`` themselves.
    """
    pattern = rf"""["'/]{re.escape(stem)}(?:\.ya?ml)?["'/]"""
    return bool(re.search(pattern, text))


def _is_config_surface(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in _CONFIG_SURFACES)


def _names_file(text: str, path: str) -> bool:
    """A guard reads a config surface by spelling its name or its whole path.

    Deliberately plainer than :func:`_names`: there is no bare-stem form to
    catch here (nobody stores ``"dependabot"`` and appends ``.yml``), and a
    stem match would be far looser — ``package`` occurs in most files that
    mention packaging at all.
    """
    return Path(path).name in text or path in text


def select_guards(changed: list[str], tests_dir: Path | None = None) -> list[str]:
    """Test files that read any of ``changed``, as repository-relative paths."""
    tests_dir = TESTS if tests_dir is None else tests_dir
    # Only files under .github/workflows/ produce a workflow stem. Measured
    # 2026-08-06: without that restriction `.github/dependabot.yml` is a `.yml`
    # like any other, so it yielded the stem `dependabot` and dragged in all 38
    # guards that merely ENUMERATE the workflow directory — none of which read
    # it. The early return used to hide this, because the step fed nothing but
    # workflows.
    stems = [
        Path(path).stem
        for path in changed
        if path.startswith(".github/workflows/") and Path(path).suffix in {".yml", ".yaml"}
    ]
    configs = [path for path in changed if _is_config_surface(path)]
    if not stems and not configs:
        return []

    selected: set[Path] = set()
    for candidate in sorted(tests_dir.glob("test_*.py")):
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if any(_names_file(text, path) for path in configs):
            selected.add(candidate)
            continue
        # `stems` gates the whole workflow branch: enumeration means "any
        # workflow changed", which is false when none did.
        if not stems or not _reads_workflows(text):
            continue
        if _enumerates_workflows(text) or any(_names(text, stem) for stem in stems):
            selected.add(candidate)

    root = tests_dir.resolve().parent
    # as_posix(), not str(): the result is compared against forward-slash
    # literals in tests and handed to pytest, and str(Path) yields backslashes
    # on Windows. tests/test_scripts_path_as_posix_guard.py enforces it.
    return sorted(path.resolve().relative_to(root).as_posix() for path in selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("changed", nargs="*", help="paths changed by the pull request")
    args = parser.parse_args()

    guards = select_guards(args.changed)
    if not guards:
        print("no workflow guards selected", file=sys.stderr)
        return 0
    print("\n".join(guards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

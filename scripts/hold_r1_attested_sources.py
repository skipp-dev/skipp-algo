#!/usr/bin/env python3
"""Hold R1-attested sources at their attested content during an automated refresh.

The library refresh bumps ``import preuss_steffen/smc_micro_profiles_generated/<N>``
across every consumer ``.pine`` file. Two of those consumers are R1-attested
companions, so every refresh rewrote a source whose registered evidence still
described the previous content -- and since 2026-08-04 the
``check_r1_attested_sources`` guard fails exactly that, on the refresh's own PR.

That produced a treadmill rather than a stop. Measured 2026-08-04: the
Databento export fires 9x per weekday, each success chains a refresh, each
refresh opens ``bot/library-refresh-<run>-<attempt>`` with auto-merge enabled --
and auto-merge can never fire while the guard is red. #4405 (pin /184) and
#4429 (/185) sat open simultaneously with a third run generating /186. Before
the guard existed the same PRs merged in ~35 seconds and nothing accumulated.

An attested companion may only move together with new evidence, and evidence
costs a mutating TradingView session. A cadence of 9 per day cannot carry that,
so the automated path must not move it at all: hold the attested sources, let
every other consumer advance, and leave the companion bump to a deliberate
re-attestation PR.

Holding is safe for the published library. Pine imports are pinned per script
and TradingView keeps every published version, so a companion importing ``/183``
keeps resolving after ``/186`` ships.

CORRECTION 2026-08-05. This docstring claimed "nothing in the repo requires
consumers to share one pin -- verified 2026-08-04". That verification read the
*scripts* (``check_library_release_manifest_drift.py`` checks that the
manifest's ``consumers[]`` paths exist, not what they import) and generalised
from them to the whole repo without reading the pytest suite. Three tests did
require it, and `main` went red the moment the hold first lagged a companion by
a real version -- ``SMC_Event_Overlay.pine`` on ``/183`` against fourteen
consumers on ``/190``:

* ``tests/test_pine_library_version_consistency.py``
* ``tests/test_pine_function_definition_order.py``
* ``tests/test_smc_event_overlay.py``

Two of them -- ``test_pine_library_version_consistency.py`` and
``test_pine_function_definition_order.py`` -- exempt the attested sources by
reading :func:`attested_paths`. ``test_smc_event_overlay.py`` needs no list: it
asserts the companion pins at or behind the published version, never ahead --
anything in front is an escaped bump rather than a hold. (Until 2026-08-07 this
said all three read :func:`attested_paths`; an AST sweep counts two.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    return result.stdout


def attested_paths() -> list[str]:
    """Repo-relative paths of every R1-attested source, from the live contract.

    Derived from the rollout contract rather than hard-coded here: a second
    list would be a second thing to keep true, and the guard that fails the
    build already reads the first one.
    """
    # Imported here rather than at module scope: the workflow runs this as
    # `python -m scripts.hold_r1_attested_sources` from the checkout root, so
    # the package is importable without touching sys.path -- and mutating
    # sys.path is itself ledgered (tests/test_sys_path_mutation_ledger.py).
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    return sorted({target["path"] for target in build_rollout_contract()["targets"]})


def modified_attested(paths: list[str], *, cwd: Path) -> list[str]:
    """Attested paths this working tree has modified against HEAD.

    An empty ``paths`` is refused by the caller, never passed through: ``git
    diff --name-only HEAD --`` with an empty pathspec drops the pathspec and
    answers about the whole tree, which would report every file as attested.
    """
    if not paths:
        raise ValueError("refusing to diff an empty attested roster")
    out = _git(["diff", "--name-only", "HEAD", "--", *paths], cwd=cwd)
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def hold(paths: list[str], *, cwd: Path) -> list[str]:
    """Restore each modified attested path to its committed content."""
    modified = modified_attested(paths, cwd=cwd)
    if modified:
        _git(["checkout", "HEAD", "--", *modified], cwd=cwd)
    return modified


def render_notice(held: list[str]) -> str:
    listed = "\n".join(f"- `{path}`" for path in held)
    return (
        "## R1-attested sources held at their attested content\n"
        "\n"
        "This refresh advanced the library pin for every consumer EXCEPT the\n"
        "R1-attested companion(s) below, which were restored to the content the\n"
        "registered evidence describes:\n"
        "\n"
        f"{listed}\n"
        "\n"
        "That keeps this PR mergeable: an attested source may not change while\n"
        "the registered evidence still attests to the previous content, and a\n"
        "re-attestation needs a mutating TradingView session that this automated\n"
        "cadence cannot carry.\n"
        "\n"
        "The companion is NOT stale as a result -- a Pine import is pinned per\n"
        "script and every published library version stays resolvable. Moving it\n"
        "is a deliberate act: run the R1 companion rollout, record a NEW dated\n"
        "evidence artifact, repoint `EXECUTION_EVIDENCE`, and bump the pin in\n"
        "that same PR.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=str(ROOT),
        help="repository working tree to operate on (default: this checkout)",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="write `held` / `notice` outputs here (default: $GITHUB_OUTPUT)",
    )
    args = parser.parse_args(argv)
    cwd = Path(args.repo).resolve()

    paths = attested_paths()
    if not paths:
        # Fail closed. An empty roster here would silently hold nothing while
        # printing an all-clear -- the vacuity this repo keeps removing.
        print(
            "::error::derived an empty R1-attested roster from "
            "scripts/smc_r1_rollout_contract.py; refusing to report that "
            "nothing needed holding",
            file=sys.stderr,
        )
        return 1

    held = hold(paths, cwd=cwd)
    if not held:
        print(f"No R1-attested source modified ({len(paths)} checked).")
    else:
        for path in held:
            print(f"held at attested content: {path}")

    if args.github_output:
        notice = render_notice(held) if held else ""
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"held={json.dumps(held)}\n")
            # Heredoc with a delimiter grown past any collision: the notice is
            # multi-line and its content is not under this script's control.
            delimiter = "R1HOLD_EOF"
            while delimiter in notice:
                delimiter += "_X"
            handle.write(f"notice<<{delimiter}\n{notice}\n{delimiter}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

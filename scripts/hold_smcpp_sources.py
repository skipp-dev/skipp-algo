#!/usr/bin/env python3
"""Hold SMC++ library sources at current-main content unless the change is pin-only.

Why this exists (the #5148 gap — the 2026-08-12 #4646 incident class, for
library sources): ``pine-library-publish-handlibs.yml`` checks out ``main``
when it starts, the ordered publisher
(``scripts/tv_publish_hand_authored_libraries.ts``) rewrites import-pin lines
IN the stale working-tree copies (its per-library own-dep repins and
``repinAllConsumers``), and the PR step stages ``'*.pine'`` +
``'SMC++'/*.pine`` wholesale. An SMC++ source whose pin moved this run is
therefore committed with the run-start BASE content underneath — a merge into
that source mid-run comes back reverted on the bot lane. The customer-surface
hold (``scripts/hold_customer_surfaces.py``) excludes ``SMC++/**`` by design
(library sources are not customer surfaces) and the R1 hold owns only the
attested sources (both at the repo root today), so a non-attested SMC++
source was held by NOTHING.

Same pattern and the same classifier and restore mechanics as the
customer-surface hold — imported, never re-implemented — with the same base:
the caller materialises every candidate from a FRESH fetch of main
(``git show FETCH_HEAD:<file>``), never the run-start HEAD, which would
revert the mid-run merge itself (#5141). ``identical`` / ``pin-only`` passes
(the run's own repins are pin-only against fresh main), anything else is
restored to current-main content and its pin advances with the next publish.

The roster is the candidates minus ``attested_paths()``: if an SMC++ source
is ever R1-attested, its stricter unconditional hold
(``scripts/hold_r1_attested_sources.py``) owns it, and classifying it here as
pin-only would re-open the door that hold closes. Fail-closed floor: every
source in the publisher's own ``HAND_LIBS`` table must be among the
candidates — derived from the writer itself, not restated, with a hard count
floor underneath, because a derived list without a floor cannot catch its own
drift. An empty or shrunken roster is UNKNOWN, never an all-clear.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Final

from scripts.hold_customer_surfaces import hold, write_github_outputs

ROOT: Final = Path(__file__).resolve().parents[1]

#: The writer whose population this hold mirrors. Parsed, not restated: a
#: hand-kept second list here would drift the first time a library joins or
#: leaves the table (the #5145 defect class, applied to sources).
_PUBLISHER: Final = ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts"

_SOURCE_RE: Final = re.compile(r'source:\s*"(SMC\+\+/[A-Za-z0-9_]+\.pine)"')

#: Hard floor under the derived table parse — 10 libraries measured
#: 2026-08-28. Lower it only together with a reason, in the same PR that
#: shrinks the HAND_LIBS table.
_MIN_HAND_LIB_SOURCES: Final = 10


def hand_lib_sources() -> list[str]:
    """The SMC++ sources the publisher can write, from the writer itself."""
    sources = _SOURCE_RE.findall(_PUBLISHER.read_text(encoding="utf-8"))
    if len(sources) < _MIN_HAND_LIB_SOURCES:
        raise ValueError(
            f"HAND_LIBS parse found only {len(sources)} source(s) in "
            f"{_PUBLISHER.name} — below the floor of {_MIN_HAND_LIB_SOURCES} "
            "(measured 2026-08-28); the derivation lost the population it "
            "exists to cover"
        )
    return sorted(set(sources))


def held_smcpp_sources(candidates: list[str], repo: Path = ROOT) -> list[str]:
    """The roster this run will hold: candidates minus the R1-attested set.

    Fails closed when a publisher source is missing from the candidates: an
    enumeration that silently lost a source would report a clean all-clear
    for a file it never looked at. A source this tree does not carry cannot
    be demanded of it (mid-run rename tolerance, mirroring
    ``required_customer_surfaces``).
    """
    # Imported here rather than at module scope for the same reason as in
    # scripts/hold_customer_surfaces.py: the workflow runs this file as
    # ``python -m scripts.hold_smcpp_sources`` from the checkout root, so
    # the package import works without touching sys.path.
    from scripts.hold_r1_attested_sources import attested_paths

    attested = set(attested_paths())
    roster = sorted({c for c in candidates if c not in attested})
    required = [
        source
        for source in hand_lib_sources()
        if source not in attested and (repo / source).is_file()
    ]
    missing = [source for source in required if source not in roster]
    if missing:
        raise ValueError(
            "SMC++ source roster is missing "
            + ", ".join(missing)
            + " — refusing to hold a population that lost a publisher source"
        )
    return roster


def render_notice(held: list[str]) -> str:
    listed = "\n".join(f"- `{path}`" for path in held)
    return (
        "## SMC++ library sources held at current-main content\n"
        "\n"
        "This publish run changed the library source(s) below beyond their\n"
        "import pin(s), so they were restored to the content of current\n"
        "`main` (measured at hold time) and are NOT advanced by this PR:\n"
        "\n"
        f"{listed}\n"
        "\n"
        "The ordered publisher may change exactly one thing in an SMC++\n"
        "source: pinned import versions. Anything else in its working copy\n"
        "is either another change merged to `main` mid-run (committing the\n"
        "stale copy would revert it — the 2026-08-12 #4646 class, for\n"
        "library sources) or an unexpected write by a workflow step.\n"
        "Holding keeps this PR honest and mergeable; the held source simply\n"
        "advances its pin with the next publish run.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="directory holding the current-main copies the caller wrote via "
        "`git show FETCH_HEAD:<file>` — reading stays with the caller so this "
        "script starts no process (same seam as hold_customer_surfaces.py)",
    )
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
    parser.add_argument("candidates", nargs="+")
    args = parser.parse_args(argv)

    try:
        roster = held_smcpp_sources(
            args.candidates, repo=Path(args.repo).resolve()
        )
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    held, advanced = hold(
        roster, base_dir=args.base_dir.resolve(), repo=Path(args.repo).resolve()
    )
    for path in advanced:
        print(f"pin-only change kept: {path}")
    if not held:
        print(f"No SMC++ source held ({len(roster)} checked).")
    else:
        for path in held:
            print(f"held at current-main content: {path}")

    if args.github_output:
        notice = render_notice(held) if held else ""
        write_github_outputs(Path(args.github_output), held=held, notice=notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

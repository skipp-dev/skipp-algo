"""Pin: every library a live Pine surface imports has someone who repins it.

Background
==========

A Pine import carries an explicit version — ``import preuss_steffen/smc_utils/4
as u``. TradingView has no "latest": the number is the contract, and a chart
keeps resolving the pinned version forever. So a library that ships a new
version leaves every consumer behind until something rewrites that number.

Two mechanisms do the rewriting today, and between them they cover the live
surface:

* ``smc-library-publish.yml`` — after publishing the generated micro-profiles
  library it enumerates every consumer of that ONE library and rewrites the
  pin. Its ``PIN_PATTERN`` names the library it owns; this test reads that
  line rather than restating it.
* ``scripts/tv_publish_hand_authored_libraries.ts`` — the ordered
  publish+repin helper behind ``npm run tv:publish-handlibs``. It publishes
  each hand-authored ``SMC++/`` library and calls ``repinAllConsumers`` to
  move every consumer to the freshly published version.
  ``pine-library-publish-handlibs.yml`` runs it weekly and opens a bot PR with
  the pin diff.

What is NOT covered, and why that is the interesting part
---------------------------------------------------------

Nothing checks that those two mechanisms between them cover *everything* the
live surface pins. A new ``import preuss_steffen/<something>/1`` in a customer
surface is owned by nobody: it is not an ``SMC++/`` library (so it never
reaches ``HAND_LIBS``), and it is not the generated library (so the refresh's
enumeration steps past it). It would sit frozen at its first version while its
library moves on — which is precisely the 2026-07 incident chain (#3599/#3603):
the generated library drifted ``/1`` against a live ``/152`` for about four
months and nothing alerted, producing CE10272 on every modern ``mp.*`` symbol.

The monitoring layer built afterwards
(``scripts/build_pine_library_version_snapshot.ts`` →
``pine-library-version-monitor.yml`` → the live-overlay daemon's Grafana
gauges) detects that drift, but it detects it *after* it exists, on a live
probe, and it reports rather than blocks. This test is the cheap half that
runs in the required check: it does not know what version TradingView holds,
but it can prove that *someone owns the number*.

Scope — the live SMC surface, stated as a population
====================================================

Root ``*.pine`` plus ``SMC++/*.pine``: the customer surfaces and the
hand-authored libraries that import each other. This is the same boundary the
snapshot builder and the refresh's repin enumeration already use.

Deliberately outside, each with its own owner named so the exclusion can go
stale loudly rather than silently:

* ``tests/`` — fixtures pin frozen versions on purpose.
* ``pine/legacy/`` — ADR-0003 permits older majors by design.
* ``pine/skipp_*.pine`` and ``pine/generated/`` — the shared and generated
  tiers, on the separate cadence of ``pine-library-freshness.yml``. Their
  libraries (``skipp_*``, ``smc_overlay_generated``) have no repin automation
  at all; that is a known, separate property of that tier and not something
  this test silently absorbs into a green run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO_ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts"
REFRESH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "smc-library-publish.yml"
FRESHNESS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pine-library-freshness.yml"

# ``import preuss_steffen/smc_utils/4 as u`` — and the alias-less form
# ``import preuss_steffen/smc_utils/4``, which Pine permits. The 2026-08-15
# review proved the mandatory-alias first cut let an alias-less pin escape the
# ownership check entirely, while every repin mechanism this guard audits
# (repinImport, the refresh's PIN_PATTERN) matches without the alias — the
# guard must not be narrower than the mechanisms it vouches for.
_IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<owner>[A-Za-z0-9_]+)/(?P<lib>[A-Za-z0-9_]+)/(?P<ver>\d+)"
    r"(?!\S)(?:\s+as\s+\w+)?",
    re.MULTILINE,
)

# The refresh declares the library it owns in one shell assignment:
#   PIN_PATTERN='import preuss_steffen/smc_micro_profiles_generated/[0-9]*'
_PIN_PATTERN_RE = re.compile(
    r"PIN_PATTERN='import\s+[A-Za-z0-9_]+/(?P<lib>[A-Za-z0-9_]+)/"
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reused, not restated. The orchestrator's HAND_LIBS table is already parsed by
# the inventory guard; a second parser here would be a second thing to keep
# true, and the two would drift apart exactly when it matters.
from test_pine_handlib_publisher_inventory import _hand_libs


def live_surface_files() -> list[Path]:
    """Root consumers plus the hand-authored libraries — the population."""
    files = sorted(REPO_ROOT.glob("*.pine"))
    files += sorted((REPO_ROOT / "SMC++").glob("*.pine"))
    return files


def pins_by_library() -> dict[str, list[str]]:
    """Map library name -> the live files that pin it."""
    out: dict[str, list[str]] = {}
    for path in live_surface_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            out.setdefault(match.group("lib"), []).append(rel)
    return out


def refresh_owned_library() -> str:
    """The single library the refresh's repin enumeration rewrites."""
    text = REFRESH_WORKFLOW.read_text(encoding="utf-8")
    matches = _PIN_PATTERN_RE.findall(text)
    assert matches, (
        f"no PIN_PATTERN assignment found in {REFRESH_WORKFLOW.name} — the "
        "refresh's repin ownership can no longer be read from the workflow, "
        "so this guard would credit it with owning nothing."
    )
    assert len(set(matches)) == 1, (
        f"{REFRESH_WORKFLOW.name} declares more than one PIN_PATTERN library "
        f"({sorted(set(matches))}); this guard assumes exactly one and would "
        "otherwise pick an arbitrary winner."
    )
    return matches[0]


def test_every_pinned_library_on_the_live_surface_has_a_repin_owner() -> None:
    """No live pin may be a number nobody moves."""
    pinned = pins_by_library()
    assert pinned, (
        "no imports found across the live surface — this test would pass "
        "vacuously"
    )

    hand_libs = set(_hand_libs())
    assert hand_libs, "HAND_LIBS parsed empty — ownership would look absent for all"

    owners = hand_libs | {refresh_owned_library()}
    unowned = sorted(set(pinned) - owners)

    assert not unowned, (
        "library pinned by a live Pine surface with no repin owner:\n  - "
        + "\n  - ".join(f"{lib} — pinned by {', '.join(sorted(pinned[lib]))}" for lib in unowned)
        + "\n\nNothing rewrites these version numbers when the library ships a "
        "new version, so the consumer stays on the version it was born with "
        "and only the live TradingView probe would ever notice. Either add the "
        "library to HAND_LIBS in scripts/tv_publish_hand_authored_libraries.ts "
        "(giving it the ordered publish+repin path), or extend the refresh's "
        "repin enumeration in smc-library-publish.yml."
    )


def test_the_hand_lib_repin_mechanism_is_actually_invoked() -> None:
    """HAND_LIBS only confers ownership if the helper repins from it.

    Membership in a table is not a mechanism. If ``repinAllConsumers`` were
    defined but never called, every hand-authored library would still look
    owned here while no pin ever moved — the guard would be green over an
    inert mechanism, which is worse than no guard.
    """
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "export function repinAllConsumers(" in text, (
        "repinAllConsumers is gone from the orchestrator; hand-lib pins have "
        "no repin mechanism and the ownership asserted above is empty."
    )
    invocations = re.findall(r"(?<!function )\brepinAllConsumers\s*\(", text)
    assert invocations, (
        "repinAllConsumers is defined but never called — HAND_LIBS membership "
        "would confer ownership over a mechanism that never runs."
    )
    # The CALL SITE must pass write=true. The first cut asserted
    # `"write: boolean" in text or ", true)" in text` — the first disjunct is
    # permanently satisfied by the function's own signature, so the 2026-08-15
    # review flipped the sole call site to write=false and all three ownership
    # tests stayed green. The signature can never witness what the caller does.
    assert re.search(r"\brepinAllConsumers\([^)]*,\s*true\s*\)", text), (
        "no call site passes repinAllConsumers write=true — a dry-run-only "
        "repin moves no pins while every hand-authored library still looks "
        "owned here."
    )


def test_the_excluded_tier_still_has_the_owner_this_test_credits_it_with() -> None:
    """The scope exclusion is a claim, and claims expire.

    ``pine/skipp_*.pine`` and ``pine/generated/`` are left out of the
    population above because they belong to a different cadence. If that
    workflow disappears, the exclusion silently becomes a hole in coverage
    rather than a boundary — so the claim is checked, not asserted in prose.
    """
    assert FRESHNESS_WORKFLOW.is_file(), (
        f"{FRESHNESS_WORKFLOW.name} is gone, but this test's scope docstring "
        "still names it as the owner of the pine/ tier. Either restore it or "
        "widen this test's population to cover pine/skipp_*.pine."
    )
    shared = sorted((REPO_ROOT / "pine").glob("skipp_*.pine"))
    assert shared, (
        "no pine/skipp_*.pine libraries found, but the scope docstring excludes "
        "them by name — the exclusion now describes nothing."
    )

"""Issue #4756's piggyback promise, mechanised: a bump takes its getters along.

2026-08-16, Pine release-notes reconciliation: libraries can ``export const``
since June 2025, and three libraries carry eight exported constant getters
that only exist because they once could not. Migrating is an API break
(``lib.PROB_EPS()`` -> ``lib.PROB_EPS``) and costs a repin round over every
consumer, so #4756 decided: migrate PIGGYBACK on each library's next content
version bump, in the same PR.

That promise had no mechanism -- nothing in the bump flow reads the issue
tracker, and this repo's history says prose promises with a future trigger
rot silently (the vacuity sweeps dug out a row of them). This file is the
mechanism, built on the forward-probe doctrine: it SLEEPS while each
library's consumer pin sits at the version frozen below, and the only green
state is that sleeping one. Every change forces explicit bookkeeping:

* pin moved, getters still there  -> red: the bump broke the piggyback
  promise; migrate in this PR, or defer DELIBERATELY by updating the frozen
  version here with a dated comment.
* getters gone, pin unmoved       -> red: early migration or rename drift;
  retire the entry here and strike the getters off #4756.
* pin moved, getters gone         -> red: promise fulfilled; retire the
  entry here and strike it off #4756 (the ledger empties like the skip
  ledger: an entry at zero demands removal, not silence).

The two ``smc_lifecycle_private`` entries carry #4756's caveat: their
results must be CHECKED for constancy at bump time -- the message demands
the check and a decision, not blindly ``export const``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._guard_corpus import iter_tracked_files

ROOT = Path(__file__).resolve().parents[1]
_ISSUE = "#4756"

# (library, source path, frozen consumer-pin version, getters, demand)
# frozen versions measured 2026-08-16 across every *.pine consumer import.
_ENTRIES = (
    (
        "skipp_math",
        "pine/skipp_math.pine",
        1,
        ("PROB_EPS", "LOGIT_CLAMP", "PRICE_EPS", "Z_95"),
        "migrate to `export const` in this same PR",
    ),
    (
        "skipp_scoring",
        "pine/skipp_scoring.pine",
        1,
        ("SIDEWAYS_EMA_THRESH", "SIDEWAYS_ATR_THRESH"),
        "migrate to `export const` in this same PR",
    ),
    (
        "smc_lifecycle_private",
        "SMC++/smc_lifecycle_private.pine",
        3,
        ("compose_passed_status_text", "compose_eligible_status_text"),
        "check whether the composed result is truly constant, then migrate "
        "or defer with the finding recorded in the issue",
    ),
)


def _max_consumer_pin(library: str) -> int:
    """The highest version any *.pine consumer imports, and there MUST be one.

    A library nobody imports has no repin cost and no bump for this tripwire
    to see -- that is a population collapse, not a pass."""
    pattern = re.compile(rf"import\s+preuss_steffen/{re.escape(library)}/(\d+)\b")
    # git-derived corpus, not a tree walk: sibling worktrees and scratch dirs
    # must not feed phantom consumers into the pin measurement (the walking-
    # guard budget test rejected the rglob draft of this).
    versions = [
        int(match.group(1))
        for path in iter_tracked_files("*.pine", (), root=ROOT)
        for match in pattern.finditer(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert versions, (
        f"no consumer imports preuss_steffen/{library}/ anywhere -- the "
        f"tripwire for {_ISSUE} cannot see bumps and must be re-anchored"
    )
    return max(versions)


def _present_getters(source_path: str, getters: tuple[str, ...]) -> list[str]:
    text = (ROOT / source_path).read_text(encoding="utf-8")
    return [
        getter
        for getter in getters
        if re.search(rf"export\s+{re.escape(getter)}\s*\(\)", text)
    ]


@pytest.mark.parametrize(
    "library,source,frozen,getters,demand",
    _ENTRIES,
    ids=[entry[0] for entry in _ENTRIES],
)
def test_a_version_bump_takes_its_const_getters_along(
    library: str,
    source: str,
    frozen: int,
    getters: tuple[str, ...],
    demand: str,
) -> None:
    current = _max_consumer_pin(library)
    present = _present_getters(source, getters)

    if current == frozen:
        assert len(present) == len(getters), (
            f"{library}: {sorted(set(getters) - set(present))} no longer "
            f"exported at the frozen version /{frozen} -- early migration or "
            f"rename drift. Retire this entry, strike the getters off "
            f"{_ISSUE}, and keep the remaining table honest."
        )
        return  # sleeping: the bump this tripwire waits for has not happened

    assert not present, (
        f"{library}: consumer pin moved /{frozen} -> /{current} but "
        f"{present} still exported as getters. {_ISSUE}'s decision: {demand}. "
        f"Deferring is allowed but must be deliberate -- update the frozen "
        f"version in this test with a dated comment saying why."
    )
    pytest.fail(
        f"{library}: pin moved /{frozen} -> /{current} and the getters are "
        f"gone -- the {_ISSUE} promise is FULFILLED for this library. Retire "
        f"this entry and strike it off {_ISSUE}; a fulfilled tripwire left "
        f"in place guards a phantom (skip-ledger rule: an entry at zero "
        f"demands removal)."
    )

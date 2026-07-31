"""Doc-truth pin: the Context BUS channel budget, wherever it is restated.

``scripts/smc_context_bus_manifest.py`` owns the budget (``MAX_CHANNELS``,
``MIN_RESERVED_CHANNELS``). Seven other places restate it in prose, and on
2026-07-31 the budget moved 60/4 -> 62/2 (#4263 spent two reserved slots on the
session-MSS channels) while every one of those restatements stayed at 60/4. The
registry note was fixed by DERIVING it (#4264); prose cannot be derived, so it
is pinned here instead: change the constants without updating the docs and this
test names each file that still lies.

Deliberately NOT pinned: dated evidence artifacts such as
``smc_context_bus_r4_shadow_tradingview_2026-07-31.json``, which record what was
observed at a point in time (60 channels, measured 05:23Z, before #4263 landed
at 19:03Z). Rewriting a measurement to match today's contract would falsify
evidence, not fix a doc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.smc_context_bus_manifest import (
    MAX_CHANNELS,
    MIN_RESERVED_CHANNELS,
    TRADINGVIEW_PLOT_LIMIT,
)

_ROOT = Path(__file__).resolve().parent.parent

_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
}


def _word(value: int) -> str:
    return _NUMBER_WORDS.get(value, str(value))


_ARCHITECTURE = "docs/SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md"
_ROADMAP = "docs/smc-bus-roadmap.md"
_TRACEABILITY = "artifacts/governance/pine_extended_migration_traceability.json"

# (relative path, phrase that must appear on a line of its own file). Each
# phrase is built from the constants, so a budget change breaks every stale
# restatement at once.
#
# Phrases are matched per LINE and must be mutually non-overlapping: with a
# whole-file substring search, "no more than 62 channels" is also satisfied by
# the "allocate no more than 62 channels" line elsewhere in the same document,
# so reverting the first line alone would slip through. Hence the bullet
# punctuation is part of the pin.
_RESTATEMENTS: tuple[tuple[str, str], ...] = (
    (_ARCHITECTURE, f"manifest with {MAX_CHANNELS} channels and {_word(MIN_RESERVED_CHANNELS)} reserves;"),
    (_ARCHITECTURE, f"- no more than {MAX_CHANNELS} channels;"),
    (_ARCHITECTURE, f"- at least {_word(MIN_RESERVED_CHANNELS)} unused reserve plots;"),
    (_ARCHITECTURE, f"{MAX_CHANNELS} direct channels,"),
    (_ARCHITECTURE, f"{_word(MIN_RESERVED_CHANNELS)} reserved slots, and no packed UI-row transport"),
    (_ARCHITECTURE, f"- allocate no more than {MAX_CHANNELS} channels;"),
    (_ARCHITECTURE, f"- reserve at least {_word(MIN_RESERVED_CHANNELS)} channels;"),
    (
        _ARCHITECTURE,
        f"maximum {MAX_CHANNELS} channels, {_word(MIN_RESERVED_CHANNELS)}-channel reserve",
    ),
    (
        _ROADMAP,
        f"≤ {MAX_CHANNELS} direct channels, ≥ {MIN_RESERVED_CHANNELS} reserve slots "
        f"(of the {TRADINGVIEW_PLOT_LIMIT} cap)",
    ),
    (
        _TRACEABILITY,
        f"at most {MAX_CHANNELS} channels and at least {_word(MIN_RESERVED_CHANNELS)} reserves",
    ),
    (_TRACEABILITY, f"all {MAX_CHANNELS} CTX channels are display.none"),
)


def test_restatement_inventory_is_not_empty() -> None:
    """Guard the guard: an empty inventory would pass every check below."""
    assert len(_RESTATEMENTS) >= 11
    assert {rel for rel, _ in _RESTATEMENTS} == {_ARCHITECTURE, _ROADMAP, _TRACEABILITY}


def test_restatement_phrases_do_not_shadow_each_other() -> None:
    """Within one file, no phrase may be a substring of another.

    Otherwise a single line satisfies two pins and reverting one restatement
    slips through — the exact hole the first version of this test had. Overlaps
    ACROSS files are harmless, since each pin is only searched in its own file.
    """
    shadowed = [
        f"{rel_a}: {a!r} is contained in {b!r}"
        for rel_a, a in _RESTATEMENTS
        for rel_b, b in _RESTATEMENTS
        if rel_a == rel_b and a != b and a in b
    ]
    assert not shadowed, "Overlapping pins:\n  - " + "\n  - ".join(shadowed)


@pytest.mark.parametrize(("rel", "phrase"), _RESTATEMENTS)
def test_channel_budget_restatement_matches_the_constants(rel: str, phrase: str) -> None:
    text = (_ROOT / rel).read_text(encoding="utf-8")
    assert phrase in text, (
        f"{rel} no longer states the Context BUS budget as "
        f"{MAX_CHANNELS} channels / {MIN_RESERVED_CHANNELS} reserves. "
        f"Expected to find: {phrase!r}. Update the prose to match "
        f"scripts/smc_context_bus_manifest.py, or update this pin if the "
        f"wording changed."
    )


def test_superseded_budget_numbers_are_gone_from_the_restating_files() -> None:
    """The 60/4 budget must not survive anywhere that states the CURRENT rule."""
    stale = (
        "60 channels",
        "60 direct channels",
        "no more than 60",
        "at most 60 channels",
        "maximum 60 channels",
        "four reserves",
        "four reserved slots",
        "four unused reserve plots",
        "reserve at least four",
        "≥ 4 reserve slots",
    )
    offenders: list[str] = []
    for rel in (_ARCHITECTURE, _ROADMAP, _TRACEABILITY):
        text = (_ROOT / rel).read_text(encoding="utf-8")
        offenders.extend(f"{rel}: {phrase!r}" for phrase in stale if phrase in text)
    assert not offenders, "Superseded 60/4 channel budget still stated in:\n  - " + "\n  - ".join(
        offenders
    )

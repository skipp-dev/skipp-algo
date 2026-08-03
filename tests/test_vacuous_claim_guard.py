"""Merge gate for the "green without having looked" class.

A check whose loop runs zero times reports success without evidence. The
repo has said so in prose 34 times (``"…would pass vacuously"``) and has
healed individual instances by hand; what it lacked was enforcement. This
guard closes the class: every vacuum-prone claim is either fixed with the
lived idiom or carries a dated justification in ``pin_registry.toml``.

This guard is subject to its own rule. ``assert undeclared == []`` over an
empty list is exactly the shape it forbids, so it carries a witness that
the analyzer actually looked at something — the same idiom the fast-gates
meta-guards already use (``assert len(ledgers) >= 15`` and its two
siblings in ``tests/test_fast_gates_silent_skip_coverage.py``).

Scope: ``tests/`` only, and that is a measured decision rather than an
omission. On 2026-08-03 ``python -m scripts.detect_vacuous_claims scripts/
services/`` reported **0 vacuum-prone claims over 805 files** — production
``assert`` is already budget-gated by
``tests/test_assert_in_production_budget.py``, so the surface is empty.
Pointing the guard at an empty population would be precisely the failure
this module exists to forbid: it would report green having observed
nothing. Re-measure before widening the scope.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

from scripts.detect_vacuous_claims import ROOT, ScanResult, scan_paths
from tests._pin_registry import vacuous_claim_exemptions

TESTS_DIR = ROOT / "tests"

#: An exemption is a decision, and a decision has a date and a reason.
_DATED_REASON = re.compile(r"^\d{4}-\d{2}-\d{2}: \S")


@lru_cache(maxsize=1)
def _scan() -> ScanResult:
    return scan_paths([TESTS_DIR])


def test_the_analyzer_observed_the_test_suite() -> None:
    """Witness for the gate below — without it, this file is its own bug.

    If discovery breaks (a moved tests/ layout, a swallowed parse error),
    the claim set goes empty and every assertion here passes while proving
    nothing. Pinning the scanned population makes that failure loud.
    """
    scanned = _scan().files
    assert len(scanned) > 1_000, (
        f"the analyzer scanned only {len(scanned)} files — discovery or the "
        "tests/ layout changed and this guard would pass vacuously"
    )


def test_no_unexempted_vacuous_claims() -> None:
    """Every vacuum-prone assertion is fixed or explicitly declared."""
    exemptions = vacuous_claim_exemptions()
    undeclared = sorted(
        f"{claim.key}  [{claim.kind}]  {claim.path}:{claim.lineno}"
        for claim in _scan().claims
        if claim.key not in exemptions
    )
    assert undeclared == [], (
        "assertion(s) can pass without observing anything: the iterable can "
        "be empty at runtime and nothing in the same scope proves it is not.\n\n"
        + "\n".join(undeclared)
        + "\n\nFix with the idiom this repo already uses — assert the set "
        "non-empty next to the loop (`assert bool_lines, \"…would pass "
        "vacuously\"`), or raise when the loop finds nothing. If the "
        "emptiness is intended and proven elsewhere, add the key to "
        "[vacuous_claim_guard.exemptions] in pin_registry.toml with a dated "
        "reason naming the test that does the proving."
    )


def test_claim_keys_are_unique() -> None:
    """One registry key must mean exactly one claim.

    :attr:`VacuousClaim.key` is ``path::test::iterable`` and deliberately
    omits ``kind``: an exemption records what a reviewer decided about a
    *site*, not about a detector category. But one test can carry both a
    loop claim and a ``parametrize`` claim over identically rendered text.
    Those two collide on one key, and a single exemption would then waive
    both — silently widening a decision that was made about one of them.
    A collision must be loud rather than convenient.
    """
    duplicates = sorted(
        key for key, count in Counter(c.key for c in _scan().claims).items() if count > 1
    )
    assert duplicates == [], (
        "distinct claims share one registry key, so one exemption would "
        f"waive several sites at once: {duplicates}. Disambiguate the sites "
        "(they are two different assertions in the same test) rather than "
        "exempting the shared key."
    )


def test_every_exemption_still_matches_a_claim() -> None:
    """A stale exemption silently shrinks the guarded set.

    Same contract as the ``frozen site still present`` tests: if the code an
    exemption refers to was fixed or deleted, the exemption must go with it,
    otherwise the registry drifts into a list of things nobody checks.
    """
    keys = {claim.key for claim in _scan().claims}
    stale = sorted(set(vacuous_claim_exemptions()) - keys)
    assert stale == [], (
        "exemption(s) no longer match any detected claim (fixed, renamed or "
        f"deleted): {stale}. Remove them so the registry stays a true mirror "
        "of what is actually being waived."
    )


def test_every_exemption_carries_a_dated_reason() -> None:
    """An undated waiver is indistinguishable from an accident."""
    undated = sorted(
        key
        for key, reason in vacuous_claim_exemptions().items()
        if not _DATED_REASON.match(reason)
    )
    assert undated == [], (
        f"exemption(s) without a ``YYYY-MM-DD: reason`` justification: {undated}"
    )

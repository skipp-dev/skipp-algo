"""Relationship-invariant pin between ``HERO_TRUST_VOCAB`` and the
``TrustState`` enum.

These two controlled vocabularies live in different layers
(``scripts/smc_hero_state.py`` for hero/dashboard rendering,
``smc_integration/trust_state.py`` for the product trust state machine)
but they intentionally overlap on the four "shared" trust states:
``healthy``, ``degraded``, ``stale``, ``unavailable``.

Beyond the shared core each vocab has its own surface:

* ``HERO_TRUST_VOCAB`` adds ``"warmup"`` (hero-only — initial bootstrap
  state before the first measurement window completes).
* ``TrustState`` adds ``WATCH_ONLY = "watch_only"`` (product-only —
  dashboard remains visible but trades are advisory-only).

The two vocabs are NOT the same set; this pin freezes the *relationship*
so that a future refactor cannot:

* drift the shared core (e.g. rename ``"stale"`` to ``"outdated"`` in
  one vocab without the other → dashboard renders the old token while
  the trust machine emits the new one);
* silently widen the overlap (e.g. add ``"watch_only"`` to
  ``HERO_TRUST_VOCAB`` without updating the dashboard render path);
* silently shrink it (e.g. drop ``"warmup"`` from the hero vocab while
  Pine still renders it).

Companion pins:

* ``tests/test_central_vocab_fingerprint_gate.py`` — freezes the exact
  membership of each vocab via sha256.
* ``tests/test_pine_python_vocab_cross_check.py`` — freezes Pine render
  coverage of every vocab token.
* ``tests/test_hero_defaults_vocab_coverage.py`` — freezes that
  ``DEFAULTS["HERO_TRUST"]`` is a vocab member.
"""

from __future__ import annotations

from scripts.smc_hero_state import HERO_TRUST_VOCAB
from smc_integration.trust_state import TrustState

# Shared trust states that both vocabularies must contain.
_SHARED_CORE: frozenset[str] = frozenset({"healthy", "degraded", "stale", "unavailable"})

# Hero-only token: bootstrap state before first measurement window.
_HERO_ONLY: frozenset[str] = frozenset({"warmup"})

# TrustState-only token: dashboard visible, trades advisory-only.
_TRUST_STATE_ONLY: frozenset[str] = frozenset({"watch_only"})


def _trust_state_values() -> frozenset[str]:
    return frozenset(member.value for member in TrustState)


def test_shared_core_is_subset_of_both_vocabs() -> None:
    hero_missing = sorted(_SHARED_CORE - HERO_TRUST_VOCAB)
    trust_missing = sorted(_SHARED_CORE - _trust_state_values())
    assert not hero_missing, (
        f"HERO_TRUST_VOCAB is missing shared-core trust state(s): {hero_missing}. "
        f"The set {sorted(_SHARED_CORE)} must be a subset of both vocabs."
    )
    assert not trust_missing, (
        f"TrustState enum is missing shared-core trust state(s): {trust_missing}. "
        f"The set {sorted(_SHARED_CORE)} must be a subset of both vocabs."
    )


def test_hero_only_token_is_not_in_trust_state() -> None:
    leaked = sorted(_HERO_ONLY & _trust_state_values())
    assert not leaked, (
        f"Hero-only trust token(s) {leaked} leaked into the TrustState enum. "
        f"If this is intentional, update _HERO_ONLY in this pin and the "
        f"surrounding documentation; otherwise remove the token from "
        f"smc_integration/trust_state.py."
    )


def test_trust_state_only_token_is_not_in_hero_vocab() -> None:
    leaked = sorted(_TRUST_STATE_ONLY & HERO_TRUST_VOCAB)
    assert not leaked, (
        f"TrustState-only trust token(s) {leaked} leaked into HERO_TRUST_VOCAB. "
        f"If this is intentional, update _TRUST_STATE_ONLY in this pin and the "
        f"surrounding documentation; otherwise remove the token from "
        f"scripts/smc_hero_state.py::HERO_TRUST_VOCAB."
    )


def test_no_unaccounted_tokens_outside_documented_partition() -> None:
    """Every token in either vocab must belong to exactly one of the
    three documented sets: shared core, hero-only, trust-state-only."""
    documented = _SHARED_CORE | _HERO_ONLY | _TRUST_STATE_ONLY
    hero_extras = sorted(HERO_TRUST_VOCAB - documented)
    trust_extras = sorted(_trust_state_values() - documented)
    assert not hero_extras, (
        f"HERO_TRUST_VOCAB contains undocumented token(s): {hero_extras}. "
        f"Add each to _SHARED_CORE (with TrustState), _HERO_ONLY, or "
        f"explicitly document the new partition in this pin."
    )
    assert not trust_extras, (
        f"TrustState enum contains undocumented token(s): {trust_extras}. "
        f"Add each to _SHARED_CORE (with HERO_TRUST_VOCAB), _TRUST_STATE_ONLY, "
        f"or explicitly document the new partition in this pin."
    )

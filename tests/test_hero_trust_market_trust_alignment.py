"""Pin: HERO_MARKET_TRUST vocab is HERO_TRUST minus the warmup state (#58).

Producer A (``scripts/smc_hero_state.py``) emits ``HERO_TRUST`` from the
canonical 5-state ``TrustState`` enum plus a Hero-local ``"warmup"``
freshness signal. Producer B (``scripts/smc_hero_market_mode.py``)
emits ``HERO_MARKET_TRUST`` via :func:`project_trust_state_to_hero`,
which has no ``"warmup"`` counterpart (TrustState has no warmup state).

Convergence contract (#58):

    HERO_MARKET_TRUST_VOCAB == HERO_TRUST_VOCAB - {"warmup"}

and for every ``TrustState`` value, the label emitted by Producer B
equals ``project_trust_state_to_hero(state)`` — the canonical mapper
already collapses ``WATCH_ONLY`` → ``"degraded"`` (info-loss documented
in ``smc_hero_state.HERO_TRUST_VOCAB`` block). This pin is a tripwire
against future label drift between A and B.
"""
from __future__ import annotations

import pytest

from scripts.smc_hero_market_mode import HERO_MARKET_TRUST_VOCAB, _trust_label
from scripts.smc_hero_state import (
    HERO_TRUST_DEGRADED,
    HERO_TRUST_HEALTHY,
    HERO_TRUST_STALE,
    HERO_TRUST_UNAVAILABLE,
    HERO_TRUST_VOCAB,
    HERO_TRUST_WARMUP,
    project_trust_state_to_hero,
)
from smc_integration.trust_state import TrustState


def test_market_trust_vocab_is_hero_trust_minus_warmup() -> None:
    assert HERO_MARKET_TRUST_VOCAB == HERO_TRUST_VOCAB - {HERO_TRUST_WARMUP}


def test_market_trust_vocab_contains_no_warmup() -> None:
    assert HERO_TRUST_WARMUP not in HERO_MARKET_TRUST_VOCAB


def test_market_trust_vocab_size_is_four() -> None:
    assert len(HERO_MARKET_TRUST_VOCAB) == 4


@pytest.mark.parametrize(
    "state,expected",
    [
        (TrustState.HEALTHY, HERO_TRUST_HEALTHY),
        (TrustState.DEGRADED, HERO_TRUST_DEGRADED),
        (TrustState.STALE, HERO_TRUST_STALE),
        (TrustState.WATCH_ONLY, HERO_TRUST_DEGRADED),
        (TrustState.UNAVAILABLE, HERO_TRUST_UNAVAILABLE),
    ],
)
def test_producer_b_label_matches_canonical_projection(
    state: TrustState, expected: str
) -> None:
    assert _trust_label(state) == expected
    assert project_trust_state_to_hero(state) == expected


def test_producer_b_emits_only_market_trust_vocab() -> None:
    for state in TrustState:
        assert _trust_label(state) in HERO_MARKET_TRUST_VOCAB

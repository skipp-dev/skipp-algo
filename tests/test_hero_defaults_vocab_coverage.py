"""Semantic-coverage pin: every value in ``DEFAULTS`` (from
``scripts/smc_hero_state.py``) that corresponds to a controlled vocab
must actually be a member of that vocab.

This is the "no typo in the default" guard. The fingerprint pin
(``test_central_vocab_fingerprint_gate.py``) freezes vocab membership;
the Pine cross-check pin
(``test_pine_python_vocab_cross_check.py``) verifies render coverage;
this pin closes the third leg of the triangle by enforcing that the
*defaults dict itself* uses only vocab members.

Without this pin a typo like
``DEFAULTS["HERO_TRUST"] = "Healthy"`` (capital H) would slip through
because the fingerprint test doesn't inspect default *values* and the
Pine test only sees lowercase ``"healthy"``.
"""

from __future__ import annotations

import pytest

from scripts.smc_hero_state import (
    DEFAULTS,
    HERO_ACTION_VOCAB,
    HERO_SETUP_QUALITY_VOCAB,
    HERO_TRUST_VOCAB,
)

# Hero-state default keys whose value MUST be a vocab member.
# (Free-form text fields like HERO_WHY_NOW / HERO_RISK / HERO_BIAS /
# HERO_MARKET_MODE are intentionally excluded — they have no closed
# Python-side vocab today; HERO_BIAS / HERO_MARKET_MODE only exist as
# Pine-side anchors.)
_VOCAB_MAP: dict[str, frozenset[str]] = {
    "HERO_TRUST": HERO_TRUST_VOCAB,
    "HERO_SETUP_QUALITY": HERO_SETUP_QUALITY_VOCAB,
    "HERO_ACTION": HERO_ACTION_VOCAB,
}


@pytest.mark.parametrize("key,vocab", sorted(_VOCAB_MAP.items()))
def test_default_value_is_vocab_member(key: str, vocab: frozenset[str]) -> None:
    assert key in DEFAULTS, (
        f"DEFAULTS is missing required hero-state key {key!r}. "
        f"If the key was renamed, update scripts/smc_hero_state.py and the "
        f"_VOCAB_MAP table in this test together."
    )
    value = DEFAULTS[key]
    assert value in vocab, (
        f"DEFAULTS[{key!r}] = {value!r} is not a member of the controlled "
        f"vocab for {key} (allowed: {sorted(vocab)}). "
        f"Either fix the typo in DEFAULTS or extend the vocab — but if you "
        f"extend the vocab, the fingerprint pin "
        f"(test_central_vocab_fingerprint_gate.py) and the Pine cross-check "
        f"(test_pine_python_vocab_cross_check.py) will both fail and force "
        f"a deliberate update."
    )

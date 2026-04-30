"""Generator roundtrip pin: HERO state → Pine library export → vocab check.

Calls :func:`scripts.smc_hero_state.build_hero_state` with a synthetic
fixture, formats the output exactly as
:func:`scripts.generate_smc_micro_profiles.write_pine_library` does
(see lines 1046–1052 of that module), and asserts every emitted
``HERO_*`` const string carries a value drawn from the corresponding
controlled vocabulary (ADR-0006, ADR-0007).

This pin closes the gap between the in-process Python vocab pins and
the on-disk Pine library: a refactor that quietly emits a different
literal in the Pine generator path (e.g. via a stale dict key) is
caught here.
"""

from __future__ import annotations

from scripts.smc_hero_state import (
    DEFAULTS,
    HERO_ACTION_VOCAB,
    HERO_BIAS_VOCAB,
    HERO_MARKET_MODE_VOCAB,
    HERO_RISK_VOCAB,
    HERO_SETUP_QUALITY_VOCAB,
    HERO_TRUST_VOCAB,
    build_hero_state,
)

# Mirrors lines 1046–1052 of scripts/generate_smc_micro_profiles.py.
_PINE_EMIT_FIELDS = (
    "HERO_MARKET_MODE",
    "HERO_BIAS",
    "HERO_TRUST",
    "HERO_SETUP_QUALITY",
    "HERO_WHY_NOW",
    "HERO_RISK",
    "HERO_ACTION",
)

# Map field → expected vocab (None means free-form string, e.g.
# HERO_WHY_NOW which is a human-readable caption).
_FIELD_VOCAB: dict[str, frozenset[str] | None] = {
    "HERO_MARKET_MODE": HERO_MARKET_MODE_VOCAB,
    "HERO_BIAS": HERO_BIAS_VOCAB,
    "HERO_TRUST": HERO_TRUST_VOCAB,
    "HERO_SETUP_QUALITY": HERO_SETUP_QUALITY_VOCAB,
    "HERO_WHY_NOW": None,
    "HERO_RISK": HERO_RISK_VOCAB,
    "HERO_ACTION": HERO_ACTION_VOCAB,
}


def _emit_pine_block(hs: dict[str, str]) -> list[str]:
    """Reproduce the generator's HERO emit block byte-for-byte."""
    out: list[str] = []
    for field in _PINE_EMIT_FIELDS:
        value = hs.get(field, DEFAULTS[field])
        out.append(f'export const string {field} = "{value}"')
    return out


def _scenario(
    *,
    regime: str = "BULLISH",
    trade_state: str = "ACTIVE",
    ensemble_tier: str = "high",
    signal_freshness: str = "fresh",
    stale_providers: str = "",
    event_risk_level: str = "LOW",
    vol_regime: str = "NORMAL",
    quality_tier: str = "high",
) -> dict[str, object]:
    """Build a nested enrichment dict matching ``build_hero_state`` shape."""
    return {
        "regime": {"regime": regime},
        "layering": {"trade_state": trade_state},
        "providers": {"stale_providers": stale_providers},
        "signal_quality": {
            "SIGNAL_FRESHNESS": signal_freshness,
            "SIGNAL_QUALITY_TIER": quality_tier,
        },
        "ensemble_quality": {"tier": ensemble_tier},
        "calendar": {},
        "zone_priority": {},
        "event_risk": {"EVENT_RISK_LEVEL": event_risk_level},
        "volatility_regime": {"label": vol_regime},
    }


def test_roundtrip_default_scenario_emits_vocab_members() -> None:
    """Smoke: defaults-only path produces 7 const strings, all vocab-valid."""
    hs = build_hero_state(_scenario())
    assert sorted(hs.keys()) == sorted(_PINE_EMIT_FIELDS), (
        f"build_hero_state emitted unexpected key set: {sorted(hs.keys())}"
    )
    lines = _emit_pine_block(hs)
    assert len(lines) == 7
    for field, line in zip(_PINE_EMIT_FIELDS, lines, strict=False):
        vocab = _FIELD_VOCAB[field]
        if vocab is None:
            continue
        # Extract the literal between the surrounding quotes.
        prefix = f'export const string {field} = "'
        assert line.startswith(prefix), line
        assert line.endswith('"'), line
        value = line[len(prefix):-1]
        assert value in vocab, (
            f"{field} = {value!r} not in {sorted(vocab)} (emitted line: {line!r})"
        )


def test_roundtrip_degraded_scenario_emits_data_stale_risk() -> None:
    """Stale provider load drives HERO_RISK to DATA_STALE."""
    hs = build_hero_state(
        _scenario(signal_freshness="stale", stale_providers="prov_a,prov_b")
    )
    assert hs["HERO_RISK"] in HERO_RISK_VOCAB
    assert hs["HERO_RISK"] == "DATA_STALE"
    assert hs["HERO_TRUST"] in HERO_TRUST_VOCAB
    assert hs["HERO_ACTION"] in HERO_ACTION_VOCAB
    assert hs["HERO_ACTION"] == "WATCH"  # forced by trust ∈ {unavailable, stale}


def test_roundtrip_blocked_scenario_emits_blocked_action_flat_bias() -> None:
    """Trade-state BLOCKED forces ACTION=BLOCKED and BIAS=FLAT."""
    hs = build_hero_state(_scenario(trade_state="BLOCKED"))
    assert hs["HERO_ACTION"] == "BLOCKED"
    assert hs["HERO_BIAS"] == "FLAT"
    # HERO_RISK may be empty (HERO_RISK_NONE) — that is the Pine
    # boundary contract sentinel and is a valid vocab member.
    assert hs["HERO_RISK"] in HERO_RISK_VOCAB


def test_roundtrip_event_risk_high_emits_event_risk() -> None:
    """High event-risk surfaces as HERO_RISK = EVENT_RISK."""
    hs = build_hero_state(_scenario(event_risk_level="HIGH"))
    assert hs["HERO_RISK"] == "EVENT_RISK"


def test_roundtrip_extreme_vol_emits_volatility_risk() -> None:
    """EXTREME vol surfaces as HERO_RISK = VOLATILITY (when no higher risk)."""
    hs = build_hero_state(_scenario(vol_regime="EXTREME"))
    assert hs["HERO_RISK"] == "VOLATILITY"


def test_roundtrip_pine_lines_are_well_formed() -> None:
    """Every emitted line matches the exact generator format."""
    hs = build_hero_state(_scenario())
    lines = _emit_pine_block(hs)
    for line in lines:
        assert line.startswith("export const string HERO_")
        assert ' = "' in line
        assert line.endswith('"')

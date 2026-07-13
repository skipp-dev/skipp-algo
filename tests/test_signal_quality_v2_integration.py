"""Component integration for the SMC v2 signal-quality surface, using SYNTHETIC
enrichment.

Scope (be honest about what this proves): every test here calls
``build_signal_quality()`` directly with a hand-built enrichment dict. It exercises
the v2 router + detector wiring as a unit — it does NOT start at a production
producer/service, so it does not prove which enrichment fields actually arrive
live. In particular ``correlated_context`` (the SMT-divergence input) is supplied
only by these fixtures: no production producer builds it (see
``smc_core.smt_divergence`` — "NO production producer builds the required
correlated_context"), so ``SMT_DIVERGENCE_*`` here is a component contract, not an
end-to-end signal. A true integration test would begin at the producer and assert
which fields are populated in the real pipeline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from scripts.smc_signal_quality import build_signal_quality


@pytest.fixture(autouse=True)
def _reset_env() -> Iterator[None]:
    """Reset all v2 feature flags after each test."""
    keys = {
        "SIGNAL_QUALITY_MODEL",
        "ENABLE_FRESHNESS_V2_SCORE",
        "ENABLE_CONFLUENCE_SCORE",
        "ENABLE_SWEEP_TRAP",
        "ENABLE_REACTION_CONTEXT",
        "ENABLE_SMT_DIVERGENCE",
        "PROMOTE_SWEEP_TRAP",
        "PROMOTE_SMT_DIVERGENCE",
    }
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def _enable_all_v2_flags() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_FRESHNESS_V2_SCORE"] = "1"
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    os.environ["ENABLE_SMT_DIVERGENCE"] = "1"


def _make_full_enrichment() -> dict:
    return {
        "structure_state_light": {
            "STRUCTURE_FRESH": True,
            "STRUCTURE_EVENT_AGE_BARS": 2,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
        },
        "session_context_light": {
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
            "IN_KILLZONE": True,
        },
        "ob_context_light": {
            "PRIMARY_OB_SIDE": "BULL",
            "OB_FRESH": True,
            "PRIMARY_OB_DISTANCE": 1.5,
            "OB_SUPPORT_SCORE": 15.0,
        },
        "fvg_lifecycle_light": {
            "PRIMARY_FVG_SIDE": "BULL",
            "FVG_FRESH": True,
            "FVG_FILL_PCT": 0.1,
            "FVG_INVALIDATED": False,
            "FVG_GAP_SCORE": 15.0,
        },
        "liquidity_sweeps": {
            "RECENT_BULL_SWEEP": True,
            "RECENT_BEAR_SWEEP": False,
            "SWEEP_DIRECTION": "BULL",
            "SWEEP_QUALITY_SCORE": 1,
            "SWEEP_TRAP_QUALITY_SCORE": 1.0,
        },
        "compression_regime": {"ATR_REGIME": "NORMAL"},
        "correlated_context": {
            "CORRELATED_BIAS": "BEARISH",
            "CORRELATED_LAST_EVENT": "BOS_BEAR",
        },
    }


def test_all_v2_features_enabled_produces_expected_keys() -> None:
    """When every v2 feature is on, build_signal_quality returns every v2 field."""
    _enable_all_v2_flags()
    result = build_signal_quality(enrichment=_make_full_enrichment())

    # Core v1 fields are still present.
    assert "SIGNAL_QUALITY_SCORE" in result
    assert "SIGNAL_QUALITY_TIER" in result
    assert "SIGNAL_WARNINGS" in result
    assert "SIGNAL_BIAS_ALIGNMENT" in result
    assert "SIGNAL_FRESHNESS" in result

    # Phase A: Freshness v2 stays very_fresh. The high-confidence sweep trap /
    # SMT divergence are observe-only (no PROMOTE_* flag set), so they do NOT
    # downgrade the live freshness label.
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"

    # Phase D: Confluence score
    assert result["CONFLUENCE_SCORE"] == 12
    assert result["CONFLUENCE_DIRECTION"] == "bull"

    # Phase B: Sweep trap
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_HEURISTIC_SCORE"] == 100

    # Phase C: Reaction zone
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 60

    # Phase E: SMT divergence
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SMT_DIVERGENCE_SIDE"] == "bear"
    assert result["SMT_DIVERGENCE_HEURISTIC_SCORE"] == 70


# Each key-adding detector flag → the signature key that (and only that) flag adds
# to a v2 result. Freshness-v2 is intentionally excluded: it mutates SIGNAL_FRESHNESS
# in place rather than adding a presence key (covered by the freshness tests below).
# NOTE: the model is pinned to "v2" for every case — the observe-only detector flags
# deliberately do NOT flip the router from v1 to v2 (audit 2026-07-12), so a detector
# flag alone would run the v1 path and emit none of these keys.
_DETECTOR_SIGNATURE_KEYS = {
    "ENABLE_CONFLUENCE_SCORE": "CONFLUENCE_SCORE",
    "ENABLE_SWEEP_TRAP": "SWEEP_TRAP_DETECTED",
    "ENABLE_REACTION_CONTEXT": "REACTION_CONTEXT_DETECTED",
    "ENABLE_SMT_DIVERGENCE": "SMT_DIVERGENCE_DETECTED",
}


@pytest.mark.parametrize("enabled_flag", sorted(_DETECTOR_SIGNATURE_KEYS))
def test_each_detector_flag_emits_only_its_own_keys(enabled_flag: str) -> None:
    """Enabling exactly one detector flag emits that detector's signature key and
    NONE of the others — checked for every detector (positive AND negative), not
    just confluence."""
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ[enabled_flag] = "1"

    result = build_signal_quality(enrichment=_make_full_enrichment())

    for flag, key in _DETECTOR_SIGNATURE_KEYS.items():
        if flag == enabled_flag:
            assert key in result, f"{enabled_flag} must emit {key}"
        else:
            assert key not in result, f"{enabled_flag} must NOT emit {key} (leak)"


def test_v2_1_is_currently_an_alias_of_v2() -> None:
    """``v2.1`` is documented as a byte-identical alias of ``v2`` (no distinct
    branch/weights/provenance yet). Pin that reality behaviourally: identical
    enrichment must produce identical output under both model tokens. If v2.1
    ever diverges, this test forces the divergence to be made explicit."""
    _enable_all_v2_flags()
    enrichment = _make_full_enrichment()

    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    out_v2 = build_signal_quality(enrichment=enrichment)
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2.1"
    out_v21 = build_signal_quality(enrichment=enrichment)

    assert out_v2 == out_v21


def test_v2_overrides_win_across_all_features() -> None:
    """Manual overrides take precedence over every v2-derived field."""
    _enable_all_v2_flags()
    overrides = {
        "SIGNAL_FRESHNESS": "manual_fresh",
        "CONFLUENCE_SCORE": 42,
        "CONFLUENCE_DIRECTION": "neutral",
        "SWEEP_TRAP_DETECTED": False,
        "SWEEP_TRAP_HEURISTIC_SCORE": 0,
        "REACTION_CONTEXT_DETECTED": False,
        "REACTION_CONTEXT_DIRECTION": "neutral",
        "REACTION_CONTEXT_CONFIDENCE": 0,
        "SMT_DIVERGENCE_DETECTED": False,
        "SMT_DIVERGENCE_SIDE": "none",
        "SMT_DIVERGENCE_HEURISTIC_SCORE": 0,
    }
    result = build_signal_quality(enrichment=_make_full_enrichment(), overrides=overrides)
    for key, value in overrides.items():
        assert result[key] == value

def test_freshness_not_downgraded_by_trap_when_observe_only() -> None:
    """Default (no PROMOTE_* flag): a high-confidence trap/divergence must NOT
    downgrade the live freshness label — the detectors are observe-only."""
    _enable_all_v2_flags()
    enrichment = _make_full_enrichment()
    enrichment["structure_state_light"]["STRUCTURE_FRESH"] = True
    enrichment["session_context_light"]["IN_KILLZONE"] = True
    result = build_signal_quality(enrichment=enrichment)
    # Sanity: the detectors DID fire (high confidence) — they just carry no weight.
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"


def test_freshness_downgraded_only_when_detector_promoted() -> None:
    """A very_fresh base label is downgraded once the detector is promoted."""
    _enable_all_v2_flags()
    os.environ["PROMOTE_SWEEP_TRAP"] = "1"
    os.environ["PROMOTE_SMT_DIVERGENCE"] = "1"
    enrichment = _make_full_enrichment()
    enrichment["structure_state_light"]["STRUCTURE_FRESH"] = True
    enrichment["session_context_light"]["IN_KILLZONE"] = True
    result = build_signal_quality(enrichment=enrichment)
    assert result["SIGNAL_FRESHNESS"] == "fresh"


def test_freshness_not_downgraded_without_contra_signals() -> None:
    """Freshness stays very_fresh when no high-confidence contra signals fire."""
    _enable_all_v2_flags()
    enrichment = _make_full_enrichment()
    # High quality sweep -> no trap detected.
    enrichment["liquidity_sweeps"]["SWEEP_QUALITY_SCORE"] = 4
    # Correlated market aligns with primary -> no SMT divergence.
    enrichment["correlated_context"] = {"CORRELATED_BIAS": "BULLISH"}
    result = build_signal_quality(enrichment=enrichment)
    assert result["SWEEP_TRAP_DETECTED"] is False
    assert result["SMT_DIVERGENCE_DETECTED"] is False
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"


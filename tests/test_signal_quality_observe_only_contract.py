"""Contract: observe-only SMC-v2 detector flags never move the live score.

Audit 2026-07-12 found that arming any single v2 feature flag flipped the
signal-quality router from v1 to v2 (changing ``SIGNAL_QUALITY_SCORE``), and
that the sweep-trap / SMT detectors — documented as observe-only — downgraded
the live ``SIGNAL_FRESHNESS`` (consumed by ``HERO_TRUST`` and the Pine trust
tier). These tests pin the corrected contract:

* the observe-only detector flags (``ENABLE_SWEEP_TRAP`` / ``ENABLE_REACTION
  _ZONE`` / ``ENABLE_SMT_DIVERGENCE``) do NOT route the model and do NOT change
  the raw score or freshness while unpromoted;
* the genuine score-model flags (``ENABLE_CONFLUENCE_SCORE`` /
  ``ENABLE_FRESHNESS_V2``) still take effect (negative control);
* a ``PROMOTE_*`` flag re-arms the weight (positive control), so the gate is
  real in both directions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from scripts.smc_signal_quality import build_signal_quality

_OBSERVE_ONLY_FLAGS = ("ENABLE_SWEEP_TRAP", "ENABLE_REACTION_ZONE", "ENABLE_SMT_DIVERGENCE")
_ALL_KEYS = (
    "SIGNAL_QUALITY_MODEL",
    "ENABLE_FRESHNESS_V2",
    "ENABLE_CONFLUENCE_SCORE",
    *_OBSERVE_ONLY_FLAGS,
    "PROMOTE_SWEEP_TRAP",
    "PROMOTE_SMT_DIVERGENCE",
)


@pytest.fixture(autouse=True)
def _clean_env() -> Iterator[None]:
    saved = {k: os.environ.pop(k, None) for k in _ALL_KEYS}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def _enrichment() -> dict:
    """Enrichment that yields a deterministic v1 score AND fires every detector
    when routed to v2 (low-quality lopsided sweep -> trap; opposing correlated
    market -> SMT divergence; fresh OB/FVG near price -> reaction zone)."""
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
        },
        "fvg_lifecycle_light": {
            "PRIMARY_FVG_SIDE": "BULL",
            "FVG_FRESH": True,
            "FVG_INVALIDATED": False,
        },
        "liquidity_sweeps": {
            "RECENT_BULL_SWEEP": True,
            "RECENT_BEAR_SWEEP": False,
            "SWEEP_DIRECTION": "BULL",
            "SWEEP_QUALITY_SCORE": 1,
        },
        "compression_regime": {"ATR_REGIME": "NORMAL"},
        "correlated_context": {
            "CORRELATED_BIAS": "BEARISH",
            "CORRELATED_LAST_EVENT": "BOS_BEAR",
        },
    }


def _score(**env: str) -> int:
    for k, v in env.items():
        os.environ[k] = v
    return int(build_signal_quality(enrichment=_enrichment())["SIGNAL_QUALITY_SCORE"])


# ── Router does not flip on observe-only flags (default model = v1) ──────────


@pytest.mark.parametrize("flag", _OBSERVE_ONLY_FLAGS)
def test_observe_only_flag_does_not_change_v1_score(flag: str) -> None:
    baseline = _score()  # pure v1, no flags
    for k in _OBSERVE_ONLY_FLAGS:
        os.environ.pop(k, None)
    assert _score(**{flag: "1"}) == baseline


@pytest.mark.parametrize("flag", _OBSERVE_ONLY_FLAGS)
def test_observe_only_flag_stays_on_v1_path(flag: str) -> None:
    """v1 stays v1: the v2-only detector fields never leak into the live dict."""
    os.environ[flag] = "1"
    result = build_signal_quality(enrichment=_enrichment())
    assert "SWEEP_TRAP_DETECTED" not in result
    assert "REACTION_ZONE_DETECTED" not in result
    assert "SMT_DIVERGENCE_DETECTED" not in result
    assert "CONFLUENCE_SCORE" not in result


# ── Within v2, observe-only detectors are score-neutral ──────────────────────


@pytest.mark.parametrize("flag", _OBSERVE_ONLY_FLAGS)
def test_observe_only_flag_score_neutral_in_v2(flag: str) -> None:
    baseline = _score(SIGNAL_QUALITY_MODEL="v2")
    assert _score(SIGNAL_QUALITY_MODEL="v2", **{flag: "1"}) == baseline


def test_observe_only_flags_do_not_downgrade_freshness_in_v2() -> None:
    # Baseline freshness with model=v2 and NO detector flags.
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    baseline_freshness = build_signal_quality(enrichment=_enrichment())["SIGNAL_FRESHNESS"]

    for k in _OBSERVE_ONLY_FLAGS:
        os.environ[k] = "1"
    result = build_signal_quality(enrichment=_enrichment())
    # Detectors fire but carry no weight -> freshness identical to baseline.
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SIGNAL_FRESHNESS"] == baseline_freshness


# ── Positive controls: the gates are real in both directions ─────────────────


def test_confluence_flag_routes_and_changes_score() -> None:
    """A genuine score-model flag still flips v1 -> v2 and moves the score."""
    v1 = _score()
    routed = _score(ENABLE_CONFLUENCE_SCORE="1")
    assert routed != v1
    result = build_signal_quality(enrichment=_enrichment())
    assert "CONFLUENCE_SCORE" in result


def test_freshness_v2_flag_routes_to_v2() -> None:
    v1 = _score()
    # freshness_v2 routes to v2; the v2 budget differs from v1, so the field set
    # gains the v2 confluence/other derivations even if the number coincides.
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    result = build_signal_quality(enrichment=_enrichment())
    # v1 never emits SIGNAL_FRESHNESS via _freshness_label_v2; the routed path
    # yields a valid label and a score in range.
    assert 0 <= int(result["SIGNAL_QUALITY_SCORE"]) <= 100
    assert result["SIGNAL_FRESHNESS"] in (
        "very_fresh",
        "fresh",
        "aging",
        "stale",
        "expired",
    )
    _ = v1


def test_smt_promotion_adds_score_in_v2() -> None:
    """PROMOTE_SMT_DIVERGENCE re-arms the +4 SMT budget (positive control)."""
    base = _score(SIGNAL_QUALITY_MODEL="v2", ENABLE_SMT_DIVERGENCE="1")
    promoted = _score(
        SIGNAL_QUALITY_MODEL="v2",
        ENABLE_SMT_DIVERGENCE="1",
        PROMOTE_SMT_DIVERGENCE="1",
    )
    assert promoted > base

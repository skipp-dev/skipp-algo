"""Tests for SPRT integration in run_ab_comparison + terminal_decision helper."""

from __future__ import annotations

import pytest

from scripts.run_ab_comparison import (
    SPRT_P0,
    _sprt_decision,
    compare,
    render_comparison,
)
from scripts.smc_sprt_stop_rule import SPRTConfig, terminal_decision

# ---------------------------------------------------------------------------
# terminal_decision (closed-form aggregate SPRT)
# ---------------------------------------------------------------------------


def test_terminal_decision_accepts_h1_on_strong_aggregate() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.20)
    state, decision = terminal_decision(n=500, k=320, config=cfg)
    assert decision == "accept_h1"
    assert state.n == 500 and state.k == 320


def test_terminal_decision_accepts_h0_on_low_hit_rate() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.20)
    _state, decision = terminal_decision(n=500, k=200, config=cfg)
    assert decision == "accept_h0"


def test_terminal_decision_max_n_when_inconclusive() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.20)
    # Hit-rate exactly midway — LLR will straddle bounds.
    _state, decision = terminal_decision(n=20, k=11, config=cfg)
    assert decision == "inconclusive"


def test_terminal_decision_zero_n_returns_inconclusive() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6)
    state, decision = terminal_decision(n=0, k=0, config=cfg)
    assert decision == "inconclusive"
    assert state.n == 0 and state.k == 0


def test_terminal_decision_validates_invariants() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6)
    with pytest.raises(ValueError):
        terminal_decision(n=10, k=11, config=cfg)
    with pytest.raises(ValueError):
        terminal_decision(n=-1, k=0, config=cfg)


# ---------------------------------------------------------------------------
# _sprt_decision wiring
# ---------------------------------------------------------------------------


class _Agg:
    """Stand-in for AggregateReport with only the attrs _sprt_decision reads."""

    def __init__(self, total_events: int, avg_hit_rate: float) -> None:
        self.total_events = total_events
        self.avg_hit_rate = avg_hit_rate


def test_sprt_decision_promotes_when_treatment_beats_baseline() -> None:
    # Baseline p0=0.55, target p1=0.60. Treatment hits 64% on 800 events
    # -> strongly accept_h1.
    ctrl = _Agg(total_events=800, avg_hit_rate=55.0)
    treat = _Agg(total_events=800, avg_hit_rate=64.0)
    sprt = _sprt_decision(ctrl, treat)
    assert sprt["decision"] == "accept_h1"
    assert sprt["n"] == 800
    assert sprt["k"] == round(800 * 0.64)
    assert sprt["config"]["p0"] == SPRT_P0


def test_sprt_decision_rejects_when_treatment_below_baseline() -> None:
    ctrl = _Agg(total_events=800, avg_hit_rate=55.0)
    treat = _Agg(total_events=800, avg_hit_rate=48.0)
    sprt = _sprt_decision(ctrl, treat)
    assert sprt["decision"] == "accept_h0"


def test_sprt_decision_inconclusive_for_small_sample() -> None:
    ctrl = _Agg(total_events=20, avg_hit_rate=55.0)
    treat = _Agg(total_events=20, avg_hit_rate=60.0)
    sprt = _sprt_decision(ctrl, treat)
    assert sprt["decision"] == "inconclusive"


def test_sprt_decision_honors_explicit_config_over_module_defaults() -> None:
    """The F2 gate passes the spec's pre-registered SPRT params.

    2026-06-10 audit: the spec's recalibrated p0/p1 (0.544/0.574) were
    dead config — _sprt_decision always used the hardcoded module
    constants (0.55/0.60). With n=1588, k=876 the stale params yielded
    accept_h0 (llr=-7.64) while the registered params yield a
    still-running test. The explicit config MUST take precedence and be
    reflected in the report's config block.
    """
    ctrl = _Agg(total_events=1588, avg_hit_rate=55.16)
    treat = _Agg(total_events=1588, avg_hit_rate=55.16)
    spec_cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    sprt = _sprt_decision(ctrl, treat, config=spec_cfg)
    assert sprt["config"]["p0"] == 0.544
    assert sprt["config"]["p1"] == 0.574
    # Under the registered params this corpus is NOT an H0 acceptance.
    assert sprt["decision"] != "accept_h0"
    # The stale module defaults would have accepted H0 — guard the contrast.
    stale = _sprt_decision(ctrl, treat)
    assert stale["decision"] == "accept_h0"


def test_compare_threads_sprt_config_into_digest() -> None:
    """compare(sprt_config=...) must reach the digest's sprt block."""
    pair = {
        "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
        "brier": 0.22, "hit_rate_pct": 55.0,
        "calibrated_brier": 0.21, "calibrated_ece": 0.09,
        "ensemble_score": 0.5,
    }
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    digest = compare([dict(pair)], [dict(pair)], "spec-params", sprt_config=cfg)
    assert digest["sprt"]["config"]["p0"] == 0.544
    assert digest["sprt"]["config"]["p1"] == 0.574


def test_sprt_decision_relabels_inconclusive_past_max_n() -> None:
    """Inconclusive at n >= max_n must surface as max_n_reached.

    terminal_decision() is order-independent and never emits
    max_n_reached (PR #2664 Copilot review). _sprt_decision() must
    re-label so the spec's pre-registered cap is honoured in the
    report: past-cap-without-verdict means "stop accumulating", not
    "keep accumulating".
    """
    ctrl = _Agg(total_events=1588, avg_hit_rate=55.16)
    treat = _Agg(total_events=1588, avg_hit_rate=55.16)
    capped = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20, max_n=1200)
    sprt = _sprt_decision(ctrl, treat, config=capped)
    assert sprt["decision"] == "max_n_reached"
    assert sprt["config"]["max_n"] == 1200
    # Same totals without a cap stay plain inconclusive.
    uncapped = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    assert _sprt_decision(ctrl, treat, config=uncapped)["decision"] == (
        "inconclusive"
    )
    # A bound-crossing decision past the cap is NOT masked by the cap.
    h1 = _Agg(total_events=1588, avg_hit_rate=65.0)
    assert _sprt_decision(ctrl, h1, config=capped)["decision"] == "accept_h1"


def test_sprt_decision_clamps_invalid_hit_rate() -> None:
    # Defensive: avg_hit_rate occasionally arrives as a fraction in legacy
    # fixtures or with NaN-ish overflow. Clamp keeps k in [0, n].
    ctrl = _Agg(total_events=100, avg_hit_rate=55.0)
    treat = _Agg(total_events=100, avg_hit_rate=250.0)
    sprt = _sprt_decision(ctrl, treat)
    # 250% clamped to 100% -> 100 hits
    assert sprt["k"] == 100


# ---------------------------------------------------------------------------
# End-to-end: compare() and render_comparison() include SPRT block
# ---------------------------------------------------------------------------


def _pair(n_events: int, hit_rate: float, brier: float = 0.18) -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "n_events": n_events,
        "brier": brier,
        "hit_rate_pct": hit_rate,
        "calibrated_brier": brier,
        "calibrated_ece": 0.10,
        "ensemble_score": 0.5,
    }


def test_compare_attaches_sprt_block() -> None:
    control = [_pair(800, 55.0)]
    treatment = [_pair(800, 64.0)]
    digest = compare(control, treatment, "test-exp")
    assert "sprt" in digest
    assert digest["sprt"]["decision"] == "accept_h1"


def test_render_comparison_includes_sprt_section() -> None:
    control = [_pair(800, 55.0)]
    treatment = [_pair(800, 64.0)]
    digest = compare(control, treatment, "test-exp")
    md = render_comparison(digest)
    assert "## SPRT Stop-Rule (G3/F2)" in md
    assert "ACCEPT_H1" in md
    assert "Wald bounds" in md


# ---------------------------------------------------------------------------
# Schema-pin smoke test: ``digest["sprt"]`` field set
# ---------------------------------------------------------------------------
#
# Symmetric to the schema-pin tests landed in PR #118
# (``digest["fdr_calibration"]``) and PR #119 (``digest["fdr"]``). The
# SPRT layer is the third advisory block in the A/B digest and the only
# one without a stealth-field guard. Any add/rename here must be paired
# with a major schema version bump per the
# ``schema-version-bump-must-be-major-on-field-count-change`` convention.


_SPRT_TOPLEVEL_KEYS = frozenset({
    "decision",
    "n",
    "k",
    "hit_rate",
    "llr",
    "wald_upper",
    "wald_lower",
    "config",
    "control_n",
    "control_hit_rate",
})

# 2026-06-10 (PR #2664 Copilot review): added "max_n" so the report
# discloses the spec's pre-registered observation cap.
_SPRT_CONFIG_KEYS = frozenset({"p0", "p1", "alpha", "beta", "max_n"})


def _check_sprt_block(block: dict) -> None:
    assert set(block.keys()) == _SPRT_TOPLEVEL_KEYS, (
        f"sprt top-level key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    assert set(block["config"].keys()) == _SPRT_CONFIG_KEYS, (
        f"sprt config key set drifted: {set(block['config'].keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )


def test_sprt_schema_pin_accept_h1() -> None:
    """Strong-evidence variant: decision == accept_h1, all fields populated."""
    ctrl = _Agg(total_events=800, avg_hit_rate=55.0)
    treat = _Agg(total_events=800, avg_hit_rate=64.0)
    block = _sprt_decision(ctrl, treat)
    _check_sprt_block(block)
    assert block["decision"] == "accept_h1"


def test_sprt_schema_pin_accept_h0() -> None:
    """Reject-evidence variant: decision == accept_h0."""
    ctrl = _Agg(total_events=800, avg_hit_rate=55.0)
    treat = _Agg(total_events=800, avg_hit_rate=48.0)
    block = _sprt_decision(ctrl, treat)
    _check_sprt_block(block)
    assert block["decision"] == "accept_h0"


def test_sprt_schema_pin_inconclusive() -> None:
    """Insufficient-evidence variant: decision == inconclusive (small n)."""
    ctrl = _Agg(total_events=20, avg_hit_rate=55.0)
    treat = _Agg(total_events=20, avg_hit_rate=60.0)
    block = _sprt_decision(ctrl, treat)
    _check_sprt_block(block)
    assert block["decision"] == "inconclusive"


def test_sprt_schema_pin_zero_n() -> None:
    """Empty-arms variant: still pins all fields, decision == inconclusive."""
    ctrl = _Agg(total_events=0, avg_hit_rate=0.0)
    treat = _Agg(total_events=0, avg_hit_rate=0.0)
    block = _sprt_decision(ctrl, treat)
    _check_sprt_block(block)
    assert block["decision"] == "inconclusive"
    assert block["n"] == 0 and block["k"] == 0


# ---------------------------------------------------------------------------
# W4-1 regression: SPRT uses n_hit_rate_valid, not total_events
# ---------------------------------------------------------------------------


class _AggWithNanPairs:
    """Simulates an AggregateReport where some pairs have NaN hit_rate.

    total_events=1000, but only 600 come from pairs with a valid hit_rate.
    avg_hit_rate is computed from those 600 only.  The SPRT must use
    n_hit_rate_valid=600 as denominator, not total_events=1000.
    """

    def __init__(self) -> None:
        self.total_events = 1000
        self.n_hit_rate_valid = 600
        self.avg_hit_rate = 64.0  # 64% hit rate on the 600 valid-pair events


def test_w4_1_sprt_uses_n_hit_rate_valid_not_total_events() -> None:
    """W4-1 (stat-review wave 4): n denominator must be n_hit_rate_valid.

    With total_events=1000 and avg_hit_rate=64%, k=640 (inflated).
    With n_hit_rate_valid=600 and avg_hit_rate=64%, k=384 (correct).
    The test pins that _sprt_decision reports n=600, k=384.
    """
    ctrl = _AggWithNanPairs()
    treat = _AggWithNanPairs()
    sprt = _sprt_decision(ctrl, treat)
    # Must use the valid-pair denominator, not total_events.
    assert sprt["n"] == 600, f"expected n=600 (n_hit_rate_valid), got {sprt['n']}"
    assert sprt["k"] == round(600 * 0.64), (
        f"expected k={round(600 * 0.64)}, got {sprt['k']}"
    )

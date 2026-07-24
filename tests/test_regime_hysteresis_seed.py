"""RG1: the anti-flicker VIX dead-zone in ``classify_regime`` was dead in
production. Every ``generate_open_prep_result`` call wiped the hysteresis anchor
(``reset_regime_state``), so an operator refreshing the streamlit dashboard while
VIX hovered near a threshold got RISK_OFF<->NEUTRAL flicker every refresh — and
the regime-adjusted scoring weights flipped with it.

The fix seeds the anchor from the prior run's persisted regime, but only when the
prior run was in the SAME trading session (else it resets — preserving the
original "no stale cross-session bleed" intent of reset_regime_state).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import open_prep.diff as diff
from open_prep.regime import (
    _prior_regime_if_same_session,
    classify_regime,
    reset_regime_state,
    seed_regime_hysteresis_from_prior_run,
    seed_regime_state,
)

_NOW = datetime(2026, 7, 24, 13, 0, 0, tzinfo=UTC)


def test_baseline_flicker_without_seed() -> None:
    # Documents the bug: with no seeded anchor, VIX 34.6 (just below the 35
    # EXTREME boundary) classifies NEUTRAL — i.e. a wiggle down from a prior
    # RISK_OFF flickers, because the dead-zone has no prior regime to hold.
    reset_regime_state()
    assert classify_regime(macro_bias=0.0, vix_level=34.6).regime == "NEUTRAL"


def test_seed_regime_state_holds_through_vix_dead_zone() -> None:
    # With the prior-session RISK_OFF seeded, the 1.0-pt dead-zone around VIX 35
    # holds RISK_OFF at 34.6 instead of flickering to NEUTRAL.
    reset_regime_state()
    seed_regime_state("RISK_OFF")
    assert classify_regime(macro_bias=0.0, vix_level=34.6).regime == "RISK_OFF"


def test_seed_regime_state_rejects_non_regime_values() -> None:
    reset_regime_state()
    seed_regime_state("NONSENSE")  # invalid -> treated as no anchor
    assert classify_regime(macro_bias=0.0, vix_level=34.6).regime == "NEUTRAL"


def test_prior_regime_if_same_session() -> None:
    recent = {"regime": "RISK_OFF", "ts": (_NOW - timedelta(minutes=10)).isoformat()}
    stale = {"regime": "RISK_OFF", "ts": (_NOW - timedelta(hours=25)).isoformat()}
    future = {"regime": "RISK_OFF", "ts": (_NOW + timedelta(hours=2)).isoformat()}
    assert _prior_regime_if_same_session(recent, _NOW) == "RISK_OFF"
    assert _prior_regime_if_same_session(stale, _NOW) is None          # different session
    assert _prior_regime_if_same_session(future, _NOW) is None         # clock skew -> reset
    assert _prior_regime_if_same_session({"regime": "RISK_OFF"}, _NOW) is None   # no ts
    assert _prior_regime_if_same_session({"ts": recent["ts"]}, _NOW) is None     # no regime
    assert _prior_regime_if_same_session({"regime": "RISK_OFF", "ts": "garbage"}, _NOW) is None


def test_seed_from_prior_run_holds_regime_across_intrasession_refresh(monkeypatch) -> None:
    # Simulate the streamlit refresh: the previous refresh 10 min ago persisted
    # RISK_OFF; the next refresh at VIX 34.6 must hold RISK_OFF, not flicker.
    monkeypatch.setattr(
        diff, "load_previous_snapshot",
        lambda: {"regime": "RISK_OFF", "ts": (_NOW - timedelta(minutes=10)).isoformat()},
    )
    reset_regime_state()
    assert seed_regime_hysteresis_from_prior_run(_NOW) == "RISK_OFF"
    assert classify_regime(macro_bias=0.0, vix_level=34.6).regime == "RISK_OFF"


def test_seed_from_prior_run_resets_across_session(monkeypatch) -> None:
    # A prior run from 25h ago (yesterday) is a different session: reset, so the
    # regime reflects today's VIX (legitimate day-to-day change, no stale bleed).
    monkeypatch.setattr(
        diff, "load_previous_snapshot",
        lambda: {"regime": "RISK_OFF", "ts": (_NOW - timedelta(hours=25)).isoformat()},
    )
    reset_regime_state()
    assert seed_regime_hysteresis_from_prior_run(_NOW) is None
    assert classify_regime(macro_bias=0.0, vix_level=34.6).regime == "NEUTRAL"


def test_seed_from_prior_run_is_failsafe_on_missing_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(diff, "load_previous_snapshot", lambda: None)
    reset_regime_state()
    assert seed_regime_hysteresis_from_prior_run(_NOW) is None
    # and a raising loader must not propagate — behaves like reset
    monkeypatch.setattr(diff, "load_previous_snapshot", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert seed_regime_hysteresis_from_prior_run(_NOW) is None

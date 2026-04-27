"""Tests for the F&G plumbing on ``RegimeSnapshot``/``classify_regime``."""

from __future__ import annotations

from open_prep.regime import classify_regime, reset_regime_state


def setup_function(_):
    reset_regime_state()


def test_classify_regime_without_fear_greed_omits_field_in_dict():
    snap = classify_regime(macro_bias=0.0)
    assert snap.fear_greed is None
    assert "fear_greed" not in snap.to_dict()


def test_classify_regime_attaches_fear_greed_payload():
    fng = {"value": 72.0, "label": "Greed", "source": "cnn"}
    snap = classify_regime(macro_bias=0.0, fear_greed=fng)
    assert snap.fear_greed == fng
    assert snap.to_dict()["fear_greed"] == fng
    # Must show up as a human-readable annotation reason.
    assert any("F&G=72" in r for r in snap.reasons)


def test_classify_regime_does_not_change_regime_when_fear_greed_extreme():
    # Sanity: a baseline NEUTRAL regime stays NEUTRAL even when sentiment
    # is at Extreme Greed. Sentiment is annotation-only in this PR \u2014 it
    # MUST NOT silently override the VIX/macro/breadth verdict.
    baseline = classify_regime(macro_bias=0.0)
    reset_regime_state()
    annotated = classify_regime(
        macro_bias=0.0,
        fear_greed={"value": 95.0, "label": "Extreme Greed", "source": "cnn"},
    )
    assert annotated.regime == baseline.regime
    assert annotated.weight_adjustments == baseline.weight_adjustments


def test_classify_regime_ignores_fear_greed_with_invalid_value():
    snap = classify_regime(
        macro_bias=0.0,
        fear_greed={"value": "not-a-number", "label": "?", "source": "cnn"},
    )
    assert snap.fear_greed is None
    assert all("F&G" not in r for r in snap.reasons)


def test_classify_regime_ignores_fear_greed_out_of_range():
    snap = classify_regime(
        macro_bias=0.0,
        fear_greed={"value": 150.0, "label": "?", "source": "cnn"},
    )
    assert snap.fear_greed is None


def test_classify_regime_ignores_fear_greed_bool_value():
    # bool is a subclass of int; must not be coerced to 1.0.
    snap = classify_regime(
        macro_bias=0.0,
        fear_greed={"value": True, "label": "?", "source": "cnn"},
    )
    assert snap.fear_greed is None

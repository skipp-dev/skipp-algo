"""Tests for open_prep.trade_context — the ATR display bracket."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_prep import trade_context


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RT_TRADE_STOP_ATR_MULT", raising=False)
    monkeypatch.delenv("RT_TRADE_TARGET_ATR_MULT", raising=False)


def test_bullish_bracket_defaults() -> None:
    # price 200, ATR 2.5% -> ATR abs 5.0; stop 1×ATR below, target 2×ATR above.
    ctx = trade_context.trade_context(200.0, 2.5, "LONG")
    assert ctx == {
        "trade_entry": 200.0,
        "trade_stop": 195.0,
        "trade_target": 210.0,
        "trade_r": 2.0,
    }


def test_bearish_bracket_inverts() -> None:
    ctx = trade_context.trade_context(200.0, 2.5, "B_DOWN")
    assert ctx["trade_stop"] == 205.0 and ctx["trade_target"] == 190.0


def test_unusable_inputs_yield_none() -> None:
    assert trade_context.trade_context(0.0, 2.5, "LONG") is None      # no price
    assert trade_context.trade_context(200.0, 0.0, "LONG") is None    # no ATR
    assert trade_context.trade_context(200.0, 2.5, "SIDEWAYS") is None  # unknown direction
    assert trade_context.trade_context(200.0, 2.5, "") is None


def test_env_mult_override_and_garbage_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_TRADE_STOP_ATR_MULT", "0.5")
    monkeypatch.setenv("RT_TRADE_TARGET_ATR_MULT", "1.5")
    ctx = trade_context.trade_context(100.0, 1.0, "LONG")
    assert ctx["trade_stop"] == 99.5 and ctx["trade_target"] == 101.5 and ctx["trade_r"] == 3.0
    # Garbage / non-positive env values fall back to the defaults.
    monkeypatch.setenv("RT_TRADE_STOP_ATR_MULT", "banana")
    monkeypatch.setenv("RT_TRADE_TARGET_ATR_MULT", "-2")
    ctx = trade_context.trade_context(100.0, 1.0, "LONG")
    assert ctx["trade_stop"] == 99.0 and ctx["trade_target"] == 102.0


def test_attach_sets_fields_in_place() -> None:
    sig = SimpleNamespace(price=134.37, atr_pct=3.0, direction="LONG",
                          trade_entry=None, trade_stop=None, trade_target=None, trade_r=None)
    trade_context.attach(sig)
    assert sig.trade_entry == 134.37
    assert sig.trade_stop == pytest.approx(130.34, abs=0.01)
    assert sig.trade_target == pytest.approx(142.43, abs=0.01)
    assert sig.trade_r == 2.0


def test_attach_is_noop_without_atr_and_never_raises() -> None:
    sig = SimpleNamespace(price=134.37, atr_pct=0.0, direction="LONG", trade_entry=None,
                          trade_stop=None, trade_target=None, trade_r=None)
    trade_context.attach(sig)
    assert sig.trade_entry is None  # untouched
    # Garbage attribute types must not raise either.
    trade_context.attach(SimpleNamespace(price="n/a", atr_pct=None, direction=42))


@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_price_yields_no_bracket(price: float) -> None:
    assert trade_context.trade_context(price, 2.5, "LONG") is None


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_multiplier_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, value: str,
) -> None:
    monkeypatch.setenv("RT_TRADE_STOP_ATR_MULT", value)
    monkeypatch.setenv("RT_TRADE_TARGET_ATR_MULT", value)

    assert trade_context.trade_context(100.0, 1.0, "LONG") == {
        "trade_entry": 100.0,
        "trade_stop": 99.0,
        "trade_target": 102.0,
        "trade_r": 2.0,
    }

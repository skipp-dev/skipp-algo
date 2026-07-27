"""RSI(14) producer — closes the rsi_extreme phantom-key gap.

`filter_candidate` has guarded against implausible RSI readings
(``rsi_extreme``, scorer.py) and `validate_data_quality` has accepted an
``rsi`` input since their introduction — but **no producer ever set**
``quote["rsi"]``/``quote["rsi14"]`` on the open_prep path, so the fallbacks
(NaN / 50.0) applied on every quote and the warn-only gate never fired in
production.

The producer computes Wilder-smoothed RSI(14) from the same EOD candles the
ATR full-fetch already downloads (the momentum_z pattern) and stamps it as
``quote["rsi14"]``. Missing data stays ``None`` — never a fake 50.
"""
from __future__ import annotations

from open_prep.technical_analysis import rsi14_from_closes

# The standard 14-period worked example. Hand-verified reference values:
# deltas of these 15 closes -> gains sum 3.34, losses sum 1.40;
# avg_gain = 3.34/14 = 0.238571, avg_loss = 1.40/14 = 0.10;
# RS = 2.385714 -> RSI = 100 - 100/(1+RS) = 70.4641.
_WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
]


def test_matches_the_hand_computed_reference() -> None:
    assert rsi14_from_closes(_WILDER_CLOSES) == 70.4641


def test_second_step_uses_wilder_smoothing_not_simple_average() -> None:
    # Next close 46.00 (delta -0.28), exact recursion without intermediate
    # rounding: avg_gain = (3.34/14)*13/14, avg_loss = ((1.40/14)*13+0.28)/14
    # -> RSI = 66.2496. A simple rolling mean (no Wilder smoothing) over the
    # last 14 deltas gives a visibly different number.
    value = rsi14_from_closes([*_WILDER_CLOSES, 46.00])
    avg_gain = (3.34 / 14) * 13 / 14
    avg_loss = ((1.40 / 14) * 13 + 0.28) / 14
    expected = round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 4)
    assert value == expected == 66.2496


def test_all_gains_saturates_at_100_and_all_losses_at_0() -> None:
    rising = [float(i) for i in range(1, 20)]
    falling = [float(i) for i in range(20, 1, -1)]
    assert rsi14_from_closes(rising) == 100.0
    low = rsi14_from_closes(falling)
    assert low is not None and low < 0.01


def test_insufficient_history_returns_none_not_neutral() -> None:
    assert rsi14_from_closes([1.0] * 14) is None  # needs period+1 closes
    assert rsi14_from_closes([]) is None


def test_non_finite_closes_return_none() -> None:
    closes = [*_WILDER_CLOSES]
    closes[5] = float("nan")
    assert rsi14_from_closes(closes) is None


def test_produced_value_would_trip_the_existing_gate_only_at_extremes() -> None:
    """End link of the chain: the value feeds scorer's rsi_extreme check."""
    from open_prep.scorer import filter_candidate

    quote = {
        "symbol": "RSIX", "price": 50.0, "previousClose": 48.0,
        "avgVolume": 2_000_000, "volume": 900_000,
        "rsi14": rsi14_from_closes([float(i) for i in range(1, 20)]),  # 100.0
    }
    fr = filter_candidate(quote, bias=0.0)
    assert "rsi_extreme" in fr.filter_reasons

    quote["rsi14"] = rsi14_from_closes(_WILDER_CLOSES)  # ~70.5 — plausible
    fr = filter_candidate(quote, bias=0.0)
    assert "rsi_extreme" not in fr.filter_reasons

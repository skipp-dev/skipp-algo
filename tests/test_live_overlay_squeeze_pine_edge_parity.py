"""Full Pine parity for compute_squeeze_on.

The daemon's squeeze must match the legacy USI-CHOCH Pine reference
(pine/legacy/USI-CHOCH.pine:281-291) exactly: Bollinger Bands on an SMA basis
with biased (population) stdev, Keltner Channel on an EMA basis with a
Wilder-RMA ATR, and an EDGE-containment test (bbLower > kcLower and
bbUpper < kcUpper) — not a bare width comparison.

``_pine_squeeze`` below is an independent transcription of the Pine formulas
(their documented seeds and alphas), so agreement is spec-conformance, not a
copy of the production implementation.
"""
from __future__ import annotations

import math
from typing import Any

from services.live_overlay_daemon import compute


def _bars(closes: list[float], reach: float = 1.0) -> list[dict[str, Any]]:
    """Clean OHLC bars from a close series (high/low symmetric around close)."""
    return [
        {"close": c, "high": c + reach, "low": c - reach, "open": c, "volume": 1000.0}
        for c in closes
    ]


def _pine_squeeze(bars: list[dict[str, Any]], length: int = 20) -> bool | None:
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    if len(closes) < length:
        return None
    window = closes[-length:]
    bb_basis = sum(window) / length
    pop_std = math.sqrt(sum((c - bb_basis) ** 2 for c in window) / length)  # biased ÷ n
    bb_dev = pop_std * 2.0
    bb_upper, bb_lower = bb_basis + bb_dev, bb_basis - bb_dev

    alpha_ema = 2.0 / (length + 1)  # Pine ta.ema, seed = first value
    ema = closes[0]
    for c in closes[1:]:
        ema = alpha_ema * c + (1.0 - alpha_ema) * ema

    trs: list[float] = []
    for i in range(len(bars)):
        if i > 0:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                           abs(lows[i] - closes[i - 1])))
        else:
            trs.append(highs[i] - lows[i])
    alpha_rma = 1.0 / length  # Pine ta.rma, seed = SMA of first `length`
    rma = sum(trs[:length]) / length
    for tr in trs[length:]:
        rma = alpha_rma * tr + (1.0 - alpha_rma) * rma

    kc_upper, kc_lower = ema + rma * 1.5, ema - rma * 1.5
    return bb_lower > kc_lower and bb_upper < kc_upper


def _old_width_squeeze(bars: list[dict[str, Any]], length: int = 20) -> bool | None:
    """The pre-fix width comparison (sample std, SMA-of-TR), for contrast."""
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    if len(closes) < length:
        return None
    w = closes[-length:]
    mean = sum(w) / length
    sample_std = math.sqrt(sum((c - mean) ** 2 for c in w) / (length - 1))
    trs = []
    start = len(bars) - length
    for i in range(start, len(bars)):
        if i > 0:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                           abs(lows[i] - closes[i - 1])))
        else:
            trs.append(highs[i] - lows[i])
    atr = sum(trs) / len(trs)
    return (4 * sample_std) < (3 * atr)


# name -> (closes, bar reach). The two "boundary_*" series sit right on the
# squeeze threshold, where the estimator + centre differences flip the result:
# the pre-fix width method reports False while Pine reports True.
_SERIES = {
    "uptrend": ([100.0 + i * 0.5 for i in range(40)], 1.0),
    "downtrend": ([140.0 - i * 0.5 for i in range(40)], 1.0),
    "tight_range": ([100.0 + 0.15 * ((i % 4) - 1.5) for i in range(40)], 1.0),
    "expanding": ([100.0 + (i - 20) * 0.05 * i for i in range(40)], 1.0),
    "gap": ([100.0 + i * 0.1 for i in range(20)] + [110.0 + i * 0.1 for i in range(20)], 1.0),
    "boundary_a": ([100.0 + i * 0.10 + 0.20 * ((i % 3) - 1) for i in range(40)], 0.4),
    "boundary_b": ([100.0 + i * 0.14 + 0.60 * ((i % 3) - 1) for i in range(40)], 0.4),
}


def test_squeeze_matches_pine_edge_containment() -> None:
    for name, (closes, reach) in _SERIES.items():
        bars = _bars(closes, reach=reach)
        assert compute.compute_squeeze_on(bars) == _pine_squeeze(bars), name


def test_squeeze_boundary_flips_vs_old_width_method() -> None:
    # On these boundary series the fix is a real behaviour change on the served
    # signal: Pine (edge containment) fires the squeeze, the old width method
    # did not. Guard that the fixed code now agrees with Pine, not the old path.
    for name in ("boundary_a", "boundary_b"):
        closes, reach = _SERIES[name]
        bars = _bars(closes, reach=reach)
        assert compute.compute_squeeze_on(bars) is True, name
        assert _pine_squeeze(bars) is True, name
        assert _old_width_squeeze(bars) is False, name

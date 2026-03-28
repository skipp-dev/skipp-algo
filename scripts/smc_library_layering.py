"""Compute pre-layered SMC signals for Pine library enrichment.

Thin wrapper around ``smc_core.layering`` that builds a minimal
:class:`SmcMeta`, runs ``normalize_meta`` → ``derive_base_signals``,
and returns a flat dict ready for ``write_pine_library(enrichment=…)``.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from smc_core.layering import derive_base_signals, normalize_meta, REGIME_STYLE
from smc_core.types import (
    DirectionalStrength,
    MarketRegimeContext,
    SmcMeta,
    TimedDirectionalStrength,
    TimedVolumeInfo,
    VolumeInfo,
)

_TRADE_STATE_OVERRIDES: dict[str | None, str] = {
    "RISK_OFF": "DISCOURAGED",
    "ROTATION": "DISCOURAGED",
}


def compute_library_layering(
    regime: str = "NEUTRAL",
    news: str = "NEUTRAL",
    technical_strength: float = 0.5,
    technical_bias: str = "NEUTRAL",
    volume_regime: str = "NORMAL",
) -> dict[str, Any]:
    """Return layering dict suitable for the *layering* enrichment section.

    Parameters
    ----------
    regime:
        Market regime from :func:`classify_market_regime` (RISK_ON / RISK_OFF / ROTATION / NEUTRAL).
    news:
        Aggregated news sentiment (BULLISH / BEARISH / NEUTRAL).
    technical_strength:
        Technical signal strength 0‥1.
    technical_bias:
        Technical bias direction (BULLISH / BEARISH / NEUTRAL).
    volume_regime:
        Volume regime string (NORMAL / LOW_VOLUME / HOLIDAY_SUSPECT).
    """

    now = time.time()

    # Build a minimal SmcMeta with the caller-supplied values.
    tech = TimedDirectionalStrength(
        value=DirectionalStrength(strength=technical_strength, bias=technical_bias),
        asof_ts=now,
        stale=False,
    )

    news_strength = 0.5 if news != "NEUTRAL" else 0.0
    news_td = TimedDirectionalStrength(
        value=DirectionalStrength(strength=news_strength, bias=news),
        asof_ts=now,
        stale=False,
    )

    vol_regime: Literal["NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"] = (
        volume_regime if volume_regime in ("NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT") else "NORMAL"
    )

    meta = SmcMeta(
        symbol="__LIBRARY__",
        timeframe="1D",
        asof_ts=now,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime=vol_regime, thin_fraction=0.0),
            asof_ts=now,
            stale=False,
        ),
        technical=tech,
        news=news_td,
        market_regime=MarketRegimeContext(regime=regime) if regime in ("RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL") else None,
    )

    nm = normalize_meta(meta)
    signals = derive_base_signals(nm)

    global_heat = signals["global_heat"]
    global_strength = signals["global_strength"]

    # Tone from heat
    if global_heat > 0.15:
        tone = "BULLISH"
    elif global_heat < -0.15:
        tone = "BEARISH"
    else:
        tone = "NEUTRAL"

    # Trade state: volume regime overrides first, then market-regime overrides.
    if vol_regime == "HOLIDAY_SUSPECT":
        trade_state = "BLOCKED"
    elif vol_regime == "LOW_VOLUME":
        trade_state = "DISCOURAGED"
    else:
        trade_state = _TRADE_STATE_OVERRIDES.get(regime, "ALLOWED")

    return {
        "global_heat": round(global_heat, 4),
        "global_strength": round(global_strength, 4),
        "tone": tone,
        "trade_state": trade_state,
    }

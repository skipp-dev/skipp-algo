"""Short Interest enrichment for SMC micro-profile generation."""
from __future__ import annotations

from typing import Any


def compute_short_interest_enrichment(
    symbols: list[str],
    fmp_client: Any,
) -> dict[str, Any]:
    """Compute short interest enrichment fields.

    Returns
    -------
    dict with keys:
        short_squeeze_risk_tickers  – symbols with >20% SI
        high_short_interest_tickers – symbols with >10% SI
        market_short_interest_avg   – avg SI across universe
        short_interest_extreme      – True when avg > 6%
    """
    try:
        short_data = fmp_client.get_short_interest(symbols)
    except Exception:
        short_data = {}

    squeeze_risk = [s for s, pct in short_data.items() if pct > 20.0]
    high_short = [s for s, pct in short_data.items() if pct > 10.0]
    avg_short = sum(short_data.values()) / max(len(short_data), 1)

    return {
        "short_squeeze_risk_tickers": sorted(squeeze_risk),
        "high_short_interest_tickers": sorted(high_short),
        "market_short_interest_avg": round(avg_short, 2),
        "short_interest_extreme": avg_short > 6.0,
    }

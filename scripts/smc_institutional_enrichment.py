"""Institutional accumulation / distribution enrichment."""
from __future__ import annotations

from typing import Any


def compute_institutional_enrichment(
    symbols: list[str],
    fmp_client: Any,
) -> dict[str, Any]:
    """Classify symbols as institutional accumulation or distribution.

    Compares current total shares held vs previous shares using
    quarterly 13F data.  If total increased by >5% -> accumulation;
    decreased by >5% -> distribution.
    """
    accumulation: list[str] = []
    distribution: list[str] = []

    for symbol in symbols[:30]:
        sym = str(symbol).strip().upper()
        if not sym:
            continue
        try:
            holders = fmp_client.get_institutional_holders(sym)
            if not holders or len(holders) < 2:
                continue
            current = sum(int(h.get("shares") or 0) for h in holders[:20])
            previous = sum(int(h.get("previousShares") or 0) for h in holders[:20])
            if previous > 0:
                change_pct = (current - previous) / previous
                if change_pct > 0.05:
                    accumulation.append(sym)
                elif change_pct < -0.05:
                    distribution.append(sym)
        except Exception:
            continue

    return {
        "institutional_accumulation_tickers": sorted(accumulation),
        "institutional_distribution_tickers": sorted(distribution),
        "institutional_data_available": len(accumulation) + len(distribution) > 0,
    }

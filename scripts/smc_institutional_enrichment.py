"""Institutional accumulation / distribution enrichment."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# E-2 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): warn when more than this fraction
# of per-symbol enrichment calls fail.
_FAILURE_RATE_WARN_THRESHOLD = 0.10


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
    failed: list[tuple[str, str]] = []  # E-2: per-symbol failure tracking

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
        except Exception as exc:
            failed.append((sym, type(exc).__name__))
            logger.warning("institutional enrichment failed for %s: %s", sym, exc)
            continue

    if symbols and len(failed) / len(symbols) > _FAILURE_RATE_WARN_THRESHOLD:
        logger.warning(
            "institutional enrichment failure rate %.1f%% (%d/%d) exceeds %.0f%% threshold",
            100 * len(failed) / len(symbols),
            len(failed),
            len(symbols),
            100 * _FAILURE_RATE_WARN_THRESHOLD,
        )

    return {
        "institutional_accumulation_tickers": sorted(accumulation),
        "institutional_distribution_tickers": sorted(distribution),
        "institutional_data_available": len(accumulation) + len(distribution) > 0,
    }

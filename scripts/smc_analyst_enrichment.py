"""Analyst consensus enrichment for SMC micro-profile generation."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# E-2 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): warn when more than this fraction
# of per-symbol enrichment calls fail. We log instead of raising so existing
# runs continue, but the operator gets a structured signal.
_FAILURE_RATE_WARN_THRESHOLD = 0.10


def compute_analyst_enrichment(
    symbols: list[str],
    fmp_client: Any,
) -> dict[str, Any]:
    """Classify symbols by analyst consensus.

    Uses the existing ``get_analyst_estimates()`` method to derive:
    - Strong Buy: consensus rating >= 4.0 (out of 5)
    - Underperform: consensus rating <= 2.0
    - High Upside: average target > 30% above current price
    """
    strong_buy: list[str] = []
    underperform: list[str] = []
    high_upside: list[str] = []
    failed: list[tuple[str, str]] = []  # E-2: per-symbol failure tracking

    for symbol in symbols[:50]:
        sym = str(symbol).strip().upper()
        if not sym:
            continue
        try:
            profile = fmp_client.get_company_profile(sym)
            price = float(profile.get("price") or 0) if profile else 0.0

            estimates = fmp_client.get_analyst_estimates(sym, period="annual", limit=1)
            if not estimates:
                continue
            latest = estimates[0]
            buy = int(latest.get("analyistBuy") or latest.get("analystBuy") or 0)
            strong = int(latest.get("analyistStrongBuy") or latest.get("analystStrongBuy") or 0)
            hold = int(latest.get("analyistHold") or latest.get("analystHold") or 0)
            sell = int(latest.get("analyistSell") or latest.get("analystSell") or 0)
            strong_sell = int(latest.get("analyistStrongSell") or latest.get("analystStrongSell") or 0)
            total = buy + strong + hold + sell + strong_sell
            if total == 0:
                continue

            buy_pct = (buy + strong) / total
            sell_pct = (sell + strong_sell) / total

            if buy_pct >= 0.80:
                strong_buy.append(sym)
            elif sell_pct >= 0.50:
                underperform.append(sym)

            avg_target = float(latest.get("estimatedEpsAvg") or 0)
            if price > 0 and avg_target > 0 and (avg_target / price - 1) > 0.30:
                high_upside.append(sym)
        except Exception as exc:
            failed.append((sym, type(exc).__name__))
            logger.warning("analyst enrichment failed for %s: %s", sym, exc)
            continue

    if symbols and len(failed) / len(symbols) > _FAILURE_RATE_WARN_THRESHOLD:
        logger.warning(
            "analyst enrichment failure rate %.1f%% (%d/%d) exceeds %.0f%% threshold",
            100 * len(failed) / len(symbols),
            len(failed),
            len(symbols),
            100 * _FAILURE_RATE_WARN_THRESHOLD,
        )

    return {
        "analyst_strong_buy_tickers": sorted(strong_buy),
        "analyst_underperform_tickers": sorted(underperform),
        "analyst_high_upside_tickers": sorted(high_upside),
    }

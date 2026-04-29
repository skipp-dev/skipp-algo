"""Insider transaction enrichment for SMC micro-profile generation."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# E-2 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): warn when more than this fraction
# of per-symbol enrichment calls fail.
_FAILURE_RATE_WARN_THRESHOLD = 0.10


def compute_insider_enrichment(
    symbols: list[str],
    fmp_client: Any,
) -> dict[str, Any]:
    """Identify significant insider buying / selling in last 30 days.

    Only considers transactions > $100,000 to filter noise.
    """
    buying: list[str] = []
    selling_heavy: list[str] = []
    failed: list[tuple[str, str]] = []  # E-2: per-symbol failure tracking
    cutoff = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    for symbol in symbols[:30]:
        sym = str(symbol).strip().upper()
        if not sym:
            continue
        try:
            txns = fmp_client.get_insider_trading(sym, limit=50)
            if not txns:
                continue

            buy_value = 0.0
            sell_value = 0.0
            for txn in txns:
                txn_date = str(txn.get("transactionDate") or txn.get("filingDate") or "")
                if txn_date < cutoff:
                    continue
                try:
                    value = abs(float(txn.get("securitiesTransacted") or 0) * float(txn.get("price") or 0))
                except (TypeError, ValueError):
                    continue
                if value < 100_000:
                    continue
                txn_type = str(txn.get("transactionType") or "").upper()
                if "PURCHASE" in txn_type or "BUY" in txn_type or txn_type.startswith("P"):
                    buy_value += value
                elif "SALE" in txn_type or "SELL" in txn_type or txn_type.startswith("S"):
                    sell_value += value

            if buy_value > 500_000:
                buying.append(sym)
            if sell_value > 2_000_000:
                selling_heavy.append(sym)
        except Exception as exc:
            failed.append((sym, type(exc).__name__))
            logger.warning("insider enrichment failed for %s: %s", sym, exc)
            continue

    if symbols and len(failed) / len(symbols) > _FAILURE_RATE_WARN_THRESHOLD:
        logger.warning(
            "insider enrichment failure rate %.1f%% (%d/%d) exceeds %.0f%% threshold",
            100 * len(failed) / len(symbols),
            len(failed),
            len(symbols),
            100 * _FAILURE_RATE_WARN_THRESHOLD,
        )

    return {
        "insider_buying_tickers": sorted(buying),
        "insider_selling_heavy_tickers": sorted(selling_heavy),
    }

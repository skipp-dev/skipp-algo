"""Insider transaction enrichment for SMC micro-profile generation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def compute_insider_enrichment(
    symbols: list[str],
    fmp_client: Any,
) -> dict[str, Any]:
    """Identify significant insider buying / selling in last 30 days.

    Only considers transactions > $100,000 to filter noise.
    """
    buying: list[str] = []
    selling_heavy: list[str] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

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
        except Exception:
            continue

    return {
        "insider_buying_tickers": sorted(buying),
        "insider_selling_heavy_tickers": sorted(selling_heavy),
    }

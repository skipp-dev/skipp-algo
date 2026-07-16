"""Fail-closed normalization for FMP postmarket quote and trade feeds.

The regular batch quote remains useful for ``previousClose`` and the final
regular-session cumulative volume, but its postmarket ``price`` and timestamp
are deliberately ignored.  Current price provenance comes only from a fresh
aftermarket trade or a fresh, non-crossed bid/ask pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _timestamp_epoch(row: dict[str, Any]) -> float:
    raw = _number(row.get("timestamp"))
    return raw / 1000.0 if raw >= 1_000_000_000_000 else raw


def _fresh(row: dict[str, Any], now_epoch: float, max_age_seconds: float) -> bool:
    age = now_epoch - _timestamp_epoch(row)
    return -30.0 <= age <= max_age_seconds


@dataclass(frozen=True)
class PostmarketAdapterResult:
    """Normalized price candidates plus deterministic acceptance counters."""

    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


def build_postmarket_quotes(
    *,
    reference_rows: list[dict[str, Any]],
    quote_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    close_volume_by_symbol: dict[str, float],
    baseline_session_date: str,
    current_session_date: str,
    now_epoch: float,
    max_age_seconds: float = 300.0,
) -> PostmarketAdapterResult:
    """Merge FMP postmarket feeds without trusting stale regular prices.

    A row is *price ready* when it has ``previousClose`` plus either a fresh
    last trade or a fresh valid bid/ask midpoint.  It is *signal ready* only
    when a same-session regular-close volume baseline also yields a
    non-negative postmarket volume delta.  Callers may observe price-ready
    rows, but must not pass non-signal-ready rows to volume-based detection.
    """

    def _by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol not in result:
                result[symbol] = row
        return result

    references = _by_symbol(reference_rows)
    quotes = _by_symbol(quote_rows)
    trades = _by_symbol(trade_rows)
    stats = {
        "symbols_considered": len(set(references) | set(quotes) | set(trades)),
        "price_ready_rows": 0,
        "signal_ready_rows": 0,
        "trade_price_rows": 0,
        "midpoint_price_rows": 0,
        "rejected_no_reference": 0,
        "rejected_no_fresh_price": 0,
        "rejected_crossed_quote": 0,
        "rejected_missing_baseline": 0,
        "rejected_volume_regression": 0,
    }
    normalized: dict[str, dict[str, Any]] = {}
    baseline_is_current = bool(baseline_session_date) and (
        baseline_session_date == current_session_date
    )

    for symbol in sorted(set(references) | set(quotes) | set(trades)):
        reference = references.get(symbol, {})
        previous_close = _number(reference.get("previousClose"))
        if previous_close <= 0:
            stats["rejected_no_reference"] += 1
            continue

        trade = trades.get(symbol, {})
        quote = quotes.get(symbol, {})
        trade_price = _number(trade.get("price"))
        trade_fresh = trade_price > 0 and _fresh(trade, now_epoch, max_age_seconds)
        bid = _number(quote.get("bidPrice"))
        ask = _number(quote.get("askPrice"))
        quote_fresh = _fresh(quote, now_epoch, max_age_seconds)
        quote_crossed = bid > 0 and ask > 0 and bid > ask
        midpoint_valid = quote_fresh and bid > 0 and ask > 0 and not quote_crossed

        if trade_fresh:
            price = trade_price
            price_timestamp = _timestamp_epoch(trade)
            price_source = "aftermarket_trade"
            stats["trade_price_rows"] += 1
        elif midpoint_valid:
            price = (bid + ask) / 2.0
            price_timestamp = _timestamp_epoch(quote)
            price_source = "aftermarket_midpoint"
            stats["midpoint_price_rows"] += 1
        else:
            if quote_crossed:
                stats["rejected_crossed_quote"] += 1
            stats["rejected_no_fresh_price"] += 1
            continue

        stats["price_ready_rows"] += 1
        current_volume = _number(quote.get("volume")) if quote_fresh else 0.0
        baseline_volume = _number(close_volume_by_symbol.get(symbol))
        volume_ready = baseline_is_current and baseline_volume > 0 and current_volume > 0
        postmarket_volume = 0.0
        volume_reason = "ready"
        if not volume_ready:
            volume_reason = "missing_same_session_baseline"
            stats["rejected_missing_baseline"] += 1
        else:
            postmarket_volume = current_volume - baseline_volume
            if postmarket_volume < 0:
                volume_ready = False
                postmarket_volume = 0.0
                volume_reason = "cumulative_volume_regressed"
                stats["rejected_volume_regression"] += 1

        if volume_ready:
            stats["signal_ready_rows"] += 1

        normalized[symbol] = {
            "symbol": symbol,
            "price": price,
            "previousClose": previous_close,
            "volume": postmarket_volume,
            "timestamp": price_timestamp,
            "extended_price_source": price_source,
            "extended_price_age_seconds": max(0.0, now_epoch - price_timestamp),
            "postmarket_volume_ready": volume_ready,
            "postmarket_volume_reason": volume_reason,
            "regular_close_volume": baseline_volume,
            "current_cumulative_volume": current_volume,
            "reference_price_ignored": _number(reference.get("price")),
        }

    return PostmarketAdapterResult(quotes=normalized, stats=stats)

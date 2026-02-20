from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rank_candidates(
    quotes: list[dict[str, Any]],
    bias: float,
    top_n: int = 20,
    news_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Rank long candidates from quote snapshots.

    Expected (if available) in quote payload:
    - symbol
    - price
    - changesPercentage
    - volume
    - avgVolume
    """
    ranked: list[dict[str, Any]] = []
    by_symbol_news = {k.upper(): float(v) for k, v in (news_scores or {}).items()}

    for quote in quotes:
        symbol = str(quote.get("symbol") or "")
        if not symbol:
            continue

        price = _to_float(quote.get("price"), default=0.0)
        gap_pct = _to_float(
            quote.get("changesPercentage", quote.get("changePercentage")),
            default=0.0,
        )
        volume = _to_float(quote.get("volume"), default=0.0)
        avg_volume = _to_float(quote.get("avgVolume"), default=0.0)

        rel_vol = (volume / avg_volume) if avg_volume > 0 else 0.0
        # Cap at 10x: a 50x-volume spike is untradeable at open and would
        # otherwise dominate the entire ranking regardless of other factors.
        rel_vol_capped = min(rel_vol, 10.0)
        liquidity_penalty = 1.0 if price < 5.0 else 0.0

        # Risk-off days reduce long-breakout appetite.
        risk_off_penalty = abs(min(bias, 0.0)) * 2.0

        score = 0.0
        # Cap gap at ±10 % so extreme overnight gaps don't dominate the score;
        # a +20 % gap is usually untradeable at open anyway.
        score += 0.8 * max(min(gap_pct, 10.0), -10.0)
        score += 1.2 * rel_vol_capped
        score += 0.7 * max(bias, 0.0)
        news_score = by_symbol_news.get(symbol, 0.0)
        score += news_score
        score -= 1.5 * liquidity_penalty
        score -= risk_off_penalty

        ranked.append(
            {
                "symbol": symbol,
                "score": round(score, 4),
                "price": price,
                "gap_pct": gap_pct,
                "volume": volume,
                "avg_volume": avg_volume,
                "rel_volume": round(rel_vol, 4),
                "rel_volume_capped": round(rel_vol_capped, 4),
                "macro_bias": round(bias, 4),
                "news_catalyst_score": round(news_score, 4),
            }
        )

    # Sort by score (desc), then rel_volume_capped (desc), then symbol (asc) for deterministic tie-breaking
    ranked.sort(key=lambda row: (row["score"], row["rel_volume_capped"], row["symbol"]), reverse=True)
    return ranked[:top_n]

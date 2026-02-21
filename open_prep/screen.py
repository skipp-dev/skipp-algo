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
    - gap_pct (preferred from open_prep gap-mode enrichment)
    - changesPercentage
    - volume
    - avgVolume
    """
    ranked: list[dict[str, Any]] = []
    by_symbol_news: dict[str, float] = {}
    for key, value in (news_scores or {}).items():
        by_symbol_news[str(key).upper()] = _to_float(value, default=0.0)

    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            continue

        price = _to_float(quote.get("price"), default=0.0)
        gap_pct = _to_float(
            quote.get("gap_pct", quote.get("changesPercentage", quote.get("changePercentage"))),
            default=0.0,
        )
        gap_available_raw = quote.get("gap_available")
        gap_available = True if gap_available_raw is None else bool(gap_available_raw)
        gap_pct_for_scoring = gap_pct if gap_available else 0.0
        volume = _to_float(quote.get("volume"), default=0.0)
        avg_volume = _to_float(quote.get("avgVolume"), default=0.0)
        atr = _to_float(quote.get("atr"), default=0.0)

        rel_vol = (volume / avg_volume) if avg_volume > 0 else 0.0
        # Cap at 10x: a 50x-volume spike is untradeable at open and would
        # otherwise dominate the entire ranking regardless of other factors.
        rel_vol_capped = min(rel_vol, 10.0)
        liquidity_penalty = 1.0 if price < 5.0 else 0.0

        # Risk-off days reduce long-breakout appetite.
        risk_off_penalty = abs(min(bias, 0.0)) * 2.0

        gap_component = 0.8 * max(min(gap_pct_for_scoring, 10.0), -10.0)
        rvol_component = 1.2 * rel_vol_capped
        macro_component = 0.7 * max(bias, 0.0)
        news_score = by_symbol_news.get(symbol, 0.0)
        news_component = news_score
        liquidity_penalty_component = 1.5 * liquidity_penalty
        risk_off_penalty_component = risk_off_penalty

        score = 0.0
        # Cap gap at ±10 % so extreme overnight gaps don't dominate the score;
        # a +20 % gap is usually untradeable at open anyway.
        score += gap_component
        score += rvol_component
        score += macro_component
        score += news_component
        score -= liquidity_penalty_component
        score -= risk_off_penalty_component

        no_trade_reason: list[str] = []
        allowed_setups = ["orb", "gap_go", "vwap_reclaim", "hod_reclaim"]
        max_trades = 2
        data_sufficiency_low = avg_volume <= 0.0 or rel_vol <= 0.0

        if price < 5.0:
            no_trade_reason.append("price_below_5")
        if bias <= -0.75:
            no_trade_reason.append("macro_risk_off_extreme")
            allowed_setups = ["vwap_reclaim"]
            max_trades = 1
            if rel_vol <= 0.0:
                no_trade_reason.append("missing_rvol")
        if gap_pct <= -8.0:
            no_trade_reason.append("severe_gap_down")

        long_allowed = not any(
            r in no_trade_reason
            for r in [
                "price_below_5",
                "severe_gap_down",
                "missing_rvol",
                "macro_risk_off_extreme",
            ]
        )

        ranked.append(
            {
                "symbol": symbol,
                "score": round(score, 4),
                "price": price,
                "gap_pct": gap_pct,
                "gap_type": quote.get("gap_type"),
                "gap_available": gap_available,
                "gap_from_ts": quote.get("gap_from_ts"),
                "gap_to_ts": quote.get("gap_to_ts"),
                "gap_reason": quote.get("gap_reason"),
                "volume": volume,
                "avg_volume": avg_volume,
                "atr": round(atr, 4),
                "rel_volume": round(rel_vol, 4),
                "rel_volume_capped": round(rel_vol_capped, 4),
                "macro_bias": round(bias, 4),
                "news_catalyst_score": round(news_score, 4),
                "allowed_setups": allowed_setups,
                "max_trades": max_trades,
                "data_sufficiency": {
                    "low": data_sufficiency_low,
                    "avg_volume_missing": avg_volume <= 0.0,
                    "rel_volume_missing": rel_vol <= 0.0,
                },
                "score_breakdown": {
                    "gap_component": round(gap_component, 4),
                    "rvol_component": round(rvol_component, 4),
                    "macro_component": round(macro_component, 4),
                    "news_component": round(news_component, 4),
                    "liquidity_penalty": round(liquidity_penalty_component, 4),
                    "risk_off_penalty": round(risk_off_penalty_component, 4),
                },
                "long_allowed": long_allowed,
                "no_trade_reason": no_trade_reason,
            }
        )

    # Sort by score (desc), then rel_volume_capped (desc), then symbol (asc) for deterministic tie-breaking
    ranked.sort(key=lambda row: (-row["score"], -row["rel_volume_capped"], row["symbol"]))
    return ranked[:top_n]

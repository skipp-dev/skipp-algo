from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trail_stop_profiles_from_atr(row: dict[str, Any]) -> dict[str, Any]:
    """Return ATR-based trailing-stop distances for multiple aggressiveness profiles."""
    atr = _to_float(
        row.get("atr", row.get("atr_14", row.get("atr14", row.get("average_true_range")))),
        default=0.0,
    )
    multipliers = {
        "tight": 1.0,
        "balanced": 1.5,
        "wide": 2.0,
    }
    distances = {name: round(atr * mult, 4) for name, mult in multipliers.items()}

    stop_reference_source = "none"
    stop_reference_price = 0.0
    for field in ("entry_price", "vwap", "price"):
        candidate = _to_float(row.get(field), default=0.0)
        if candidate > 0.0:
            stop_reference_source = field
            stop_reference_price = candidate
            break

    stop_prices: dict[str, float | None]
    if stop_reference_price > 0.0 and atr > 0.0:
        # Long-side defaults: stop trails below the chosen reference level.
        stop_prices = {
            name: round(max(stop_reference_price - dist, 0.0), 4)
            for name, dist in distances.items()
        }
    else:
        stop_prices = {name: None for name in multipliers}

    return {
        "atr": round(atr, 4),
        "unit": "price_distance",
        "multipliers": multipliers,
        "distances": distances,
        "stop_reference_source": stop_reference_source,
        "stop_reference_price": round(stop_reference_price, 4) if stop_reference_price > 0.0 else None,
        "stop_prices": stop_prices,
        "note": (
            "ATR unavailable in candidate payload; trail-stop distances default to 0.0."
            if atr <= 0.0
            else (
                "Stop reference unavailable (entry_price/vwap/price missing); only distance values returned."
                if stop_reference_price <= 0.0
                else "Trail distances are absolute price offsets from the selected stop reference."
            )
        ),
    }


def _setup_type_from_bias(bias: float) -> str:
    if bias >= 0.25:
        return "ORB / Gap&Go"
    if bias <= -0.25:
        return "VWAP-Reclaim only"
    return "ORB or VWAP-Hold"


def _risk_note_from_bias(bias: float) -> str:
    if bias >= 0.25:
        return "Risk-on day: allow momentum continuation entries."
    if bias <= -0.25:
        return "Risk-off day: avoid chasing first spike; require reclaim + hold."
    return "Neutral macro: trade only A+ confirmations."


def build_trade_cards(
    ranked_candidates: list[dict[str, Any]],
    bias: float,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Create deterministic trade cards suitable for human or LLM refinement."""
    cards: list[dict[str, Any]] = []
    setup_type = _setup_type_from_bias(bias)
    bias_note = _risk_note_from_bias(bias)

    for row in ranked_candidates[:top_n]:
        symbol = str(row.get("symbol", ""))
        if not symbol:
            continue

        gap_pct = _to_float(row.get("gap_pct"), default=0.0)
        if gap_pct >= 1.0:
            entry_trigger = "Break and hold above opening range high (gap-up continuation)."
            invalidation = "Fill of pre-market gap below VWAP or close below opening range low."
        elif gap_pct <= -1.0:
            entry_trigger = "VWAP reclaim and hold; wait for first 5-min bullish close above VWAP."
            invalidation = "Rejection at VWAP on first test or new intraday low after entry."
        else:
            entry_trigger = "Break and hold above opening range high OR first pullback reclaim above VWAP."
            invalidation = "Loss of VWAP after entry or close below opening range low."

        cards.append(
            {
                "symbol": symbol,
                "setup_type": setup_type,
                "entry_trigger": entry_trigger,
                "invalidation": invalidation,
                "risk_management": "Move stop to break-even at +1R; scale partial at +1.5R.",
                "trail_stop_atr": _trail_stop_profiles_from_atr(row),
                "context": {
                    "macro_bias": round(bias, 4),
                    "candidate_score": row.get("score"),
                    "gap_pct": row.get("gap_pct"),
                    "rel_volume": row.get("rel_volume"),
                    "long_allowed": bool(row.get("long_allowed", True)),
                    "no_trade_reason": row.get("no_trade_reason", []),
                    "note": bias_note,
                },
            }
        )

    return cards

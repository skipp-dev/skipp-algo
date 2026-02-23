from __future__ import annotations

from typing import Any

from .utils import to_float as _to_float


def _trail_stop_profiles_from_atr(row: dict[str, Any]) -> dict[str, Any]:
    """Return ATR-based trailing-stop distances for multiple aggressiveness profiles."""
    atr = _to_float(
        row.get("atr", row.get("atr_14", row.get("atr14", row.get("average_true_range")))),
        default=0.0,
    )
    multipliers = {
        "tight": 1.0,
        "mid": 1.5,
        "wide": 2.0,
    }
    distances = {name: round(atr * mult, 4) for name, mult in multipliers.items()}

    stop_reference_source: str | None = None
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

    # Backward-compatibility aliases for existing consumers expecting "balanced".
    distances["balanced"] = distances["mid"]
    stop_prices["balanced"] = stop_prices["mid"]
    multipliers["balanced"] = multipliers["mid"]

    return {
        "atr": round(atr, 4),
        "unit": "price_distance",
        "multipliers": multipliers,
        "distances": distances,
        "stop_reference_source": stop_reference_source,  # field name or None
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


def _setup_type_from_bias(bias: float, allowed_setups: list[str] | None = None) -> str:
    if allowed_setups and "orb" not in allowed_setups and "gap_go" not in allowed_setups:
        return "VWAP-Reclaim only"
    if bias >= 0.25:
        return "ORB / Gap&Go"
    if bias <= -0.25:
        return "VWAP-Reclaim only"
    return "ORB or VWAP-Hold"


def _risk_note_from_bias(bias: float, allowed_setups: list[str] | None = None) -> str:
    if allowed_setups and "orb" not in allowed_setups and "gap_go" not in allowed_setups:
        return "macro_risk_off_extreme: only reclaim setups allowed."
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

    for row in ranked_candidates[:top_n]:
        symbol = str(row.get("symbol", ""))
        if not symbol:
            continue

        allowed_setups = row.get("allowed_setups")
        setup_type = _setup_type_from_bias(bias, allowed_setups)
        bias_note = _risk_note_from_bias(bias, allowed_setups)

        gap_pct = _to_float(row.get("gap_pct"), default=0.0)
        gap_available = bool(row.get("gap_available", True))
        earnings_bmo = bool(row.get("earnings_bmo", False))
        is_premarket_mover = bool(row.get("is_premarket_mover", False))

        if earnings_bmo:
            entry_trigger = (
                "Earnings BMO catalyst: wait for initial reaction, then break and hold "
                "above the post-earnings opening range high. Avoid chasing first 5-min spike."
            )
            invalidation = (
                "Rejection below VWAP after earnings gap, or fill of the entire gap."
            )
        elif gap_available and gap_pct >= 1.0:
            entry_trigger = "Break and hold above opening range high (gap-up continuation)."
            invalidation = "Fill of pre-market gap below VWAP or close below opening range low."
        elif gap_available and gap_pct <= -1.0:
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
                "key_levels": {
                    "pdh": row.get("pdh"),
                    "pdl": row.get("pdl"),
                    "pdh_source": row.get("pdh_source"),
                    "pdl_source": row.get("pdl_source"),
                    "dist_to_pdh_atr": row.get("dist_to_pdh_atr"),
                    "dist_to_pdl_atr": row.get("dist_to_pdl_atr"),
                },
                "context": {
                    "macro_bias": round(bias, 4),
                    "candidate_score": row.get("score"),
                    "gap_pct": row.get("gap_pct"),
                    "rel_volume": row.get("rel_volume"),
                    "volume_ratio": row.get("volume_ratio"),
                    "is_hvb": row.get("is_hvb"),
                    "momentum_z_score": row.get("momentum_z_score"),
                    "earnings_today": row.get("earnings_today", False),
                    "earnings_timing": row.get("earnings_timing"),
                    "earnings_bmo": earnings_bmo,
                    "is_premarket_mover": is_premarket_mover,
                    "premarket_change_pct": row.get("premarket_change_pct"),
                    "long_allowed": bool(row.get("long_allowed", True)),
                    "no_trade_reason": row.get("no_trade_reason", []),
                    "allowed_setups": allowed_setups,
                    "max_trades": row.get("max_trades", 2),
                    "note": bias_note,
                },
            }
        )

    return cards

from __future__ import annotations

from typing import Any


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

        gap_pct = float(row.get("gap_pct") or 0.0)
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
                "context": {
                    "macro_bias": round(bias, 4),
                    "candidate_score": row.get("score"),
                    "gap_pct": row.get("gap_pct"),
                    "rel_volume": row.get("rel_volume"),
                    "note": bias_note,
                },
            }
        )

    return cards

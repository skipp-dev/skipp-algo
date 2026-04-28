"""Realtime promotion helpers that are safe to import without Streamlit."""

from __future__ import annotations

from typing import Any


def promote_a0a1_signals(
    ranked_v2: list[dict[str, Any]],
    filtered_out_v2: list[dict[str, Any]],
    rt_signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], dict[str, dict[str, Any]]]:
    """Auto-promote A0/A1 realtime signals that fell below the top-n cutoff."""
    a0a1_map: dict[str, dict[str, Any]] = {
        str(signal.get("symbol", "")).upper(): signal
        for signal in rt_signals
        if signal.get("level") in ("A0", "A1")
    }
    promoted_syms: set[str] = set()

    if not a0a1_map:
        return ranked_v2, filtered_out_v2, promoted_syms, a0a1_map

    ranked_symbols = {str(row.get("symbol", "")).upper() for row in ranked_v2}
    below_cutoff_map: dict[str, dict[str, Any]] = {}
    for filtered_row in filtered_out_v2:
        if filtered_row.get("filter_reasons") == ["below_top_n_cutoff"]:
            symbol = str(filtered_row.get("symbol", "")).upper()
            below_cutoff_map[symbol] = filtered_row

    for symbol, signal in a0a1_map.items():
        if symbol in ranked_symbols:
            continue
        cutoff_entry = below_cutoff_map.get(symbol)
        if cutoff_entry is None:
            continue
        ranked_v2.append(
            {
                "symbol": symbol,
                "score": cutoff_entry.get("score", 0.0),
                "gap_pct": cutoff_entry.get("gap_pct", 0.0),
                "price": cutoff_entry.get("price", signal.get("price", 0.0)),
                "confidence_tier": cutoff_entry.get("confidence_tier", ""),
                "rt_promoted": True,
                "rt_level": signal.get("level", ""),
                "rt_direction": signal.get("direction", ""),
                "rt_pattern": signal.get("pattern", ""),
                "rt_change_pct": signal.get("change_pct", 0.0),
                "rt_volume_ratio": signal.get("volume_ratio", 0.0),
            }
        )
        promoted_syms.add(symbol)
        filtered_out_v2 = [
            filtered_row
            for filtered_row in filtered_out_v2
            if str(filtered_row.get("symbol", "")).upper() != symbol
        ]

    return ranked_v2, filtered_out_v2, promoted_syms, a0a1_map

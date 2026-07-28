"""Exact observation-only replay for §15 symbol-regime weights.

The live scorer intentionally remains on its current inputs. A second full
scorer pass receives measured ADX and Bollinger-band width from the ATR candle
cache. Comparing completed scorer outputs captures component caps, penalties,
haircuts, tiering and rank movement that cannot be reconstructed from a
post-cap score breakdown.
"""
from __future__ import annotations

import math
from typing import Any, Final

SCORING_REGIME: Final[str] = "NEUTRAL"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def build_exact_shadow_quotes(
    quotes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Copy quotes and expose measured regime inputs only to the shadow pass.

    EWMA remains absent from ``daily_bars`` and therefore neutral in both
    scorer passes. Its independently measured score is returned as metadata
    for a new calibration cohort, never as a live score input.
    """
    shadow_quotes: list[dict[str, Any]] = []
    technical_by_symbol: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        copied = dict(quote)
        symbol = str(quote.get("symbol") or "").strip().upper()
        adx = _finite(quote.get("_shadow_adx"))
        bb_width = _finite(quote.get("_shadow_bb_width_pct"))
        ewma_score = _finite(quote.get("ewma_score_shadow"))
        source = str(quote.get("_shadow_technical_source") or "unavailable")
        complete = adx is not None and bb_width is not None
        if complete:
            copied["adx"] = adx
            copied["bb_width_pct"] = bb_width
        else:
            copied.pop("adx", None)
            copied.pop("bb_width_pct", None)
        # A future producer must not accidentally activate uncalibrated EWMA
        # in this §15-only replay.
        copied.pop("daily_bars", None)
        shadow_quotes.append(copied)
        if symbol:
            technical_by_symbol[symbol] = {
                "adx": adx,
                "bb_width_pct": bb_width,
                "ewma_score_shadow": ewma_score,
                "technical_source": source,
                "technical_complete": complete,
            }
    return shadow_quotes, technical_by_symbol


def attach_exact_regime_shadow(
    baseline_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    technical_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach exact score/rank comparisons to baseline rows in place.

    ``comparisons`` covers the complete scoring universe, not only served
    top-N rows, avoiding selection bias in the later wire-or-not report.
    """
    shadow_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): (rank, row)
        for rank, row in enumerate(shadow_rows, start=1)
        if str(row.get("symbol") or "").strip()
    }
    exact = 0
    unresolved = 0
    rank_changes = 0
    for baseline_rank, baseline in enumerate(baseline_rows, start=1):
        symbol = str(baseline.get("symbol") or "").strip().upper()
        technical = technical_by_symbol.get(symbol, {})
        paired = shadow_by_symbol.get(symbol)
        baseline_score = _finite(baseline.get("score"))
        if paired is None or baseline_score is None:
            unresolved += 1
            baseline["regime_weight_shadow"] = {
                "schema_version": 2,
                "symbol": symbol,
                "exact_second_scorer_pass": False,
                "regime_at_scoring": str(baseline.get("symbol_regime") or SCORING_REGIME),
                "measured_regime": None,
                "baseline_score": baseline_score,
                "shadow_score": None,
                "score_delta": None,
                "baseline_rank": baseline_rank,
                "shadow_rank": None,
                "rank_delta": None,
                "would_change_score": None,
                "technical_source": technical.get("technical_source", "unavailable"),
                "measured_adx": technical.get("adx"),
                "measured_bb_width_pct": technical.get("bb_width_pct"),
                "unresolved": ["shadow_pair_or_finite_score_missing"],
            }
            baseline["ewma_score_shadow"] = technical.get("ewma_score_shadow")
            continue

        shadow_rank, shadow = paired
        shadow_score = _finite(shadow.get("score"))
        is_exact = shadow_score is not None and bool(technical.get("technical_complete"))
        if is_exact:
            exact += 1
            score_delta = round(shadow_score - baseline_score, 6)
            rank_delta = baseline_rank - shadow_rank
            rank_changes += int(rank_delta != 0)
            unresolved_fields: list[str] = []
        else:
            unresolved += 1
            score_delta = None
            rank_delta = None
            unresolved_fields = ["measured_adx_or_bb_width_missing"]
        baseline["regime_weight_shadow"] = {
            "schema_version": 2,
            "symbol": symbol,
            "exact_second_scorer_pass": is_exact,
            "regime_at_scoring": str(baseline.get("symbol_regime") or SCORING_REGIME),
            "measured_regime": str(shadow.get("symbol_regime") or SCORING_REGIME),
            "baseline_score": baseline_score,
            "shadow_score": shadow_score if is_exact else None,
            "score_delta": score_delta,
            "baseline_rank": baseline_rank,
            "shadow_rank": shadow_rank if is_exact else None,
            "rank_delta": rank_delta,
            "would_change_score": score_delta != 0.0 if score_delta is not None else None,
            "technical_source": technical.get("technical_source", "unavailable"),
            "measured_adx": technical.get("adx"),
            "measured_bb_width_pct": technical.get("bb_width_pct"),
            "unresolved": unresolved_fields,
        }
        baseline["ewma_score_shadow"] = technical.get("ewma_score_shadow")

    return {
        "schema_version": 2,
        "baseline_rows": len(baseline_rows),
        "shadow_rows": len(shadow_rows),
        "exact_rows": exact,
        "unresolved_rows": unresolved,
        "rank_changed_rows": rank_changes,
        "comparisons": [
            dict(row["regime_weight_shadow"])
            for row in baseline_rows
            if isinstance(row.get("regime_weight_shadow"), dict)
        ],
        "live_ranking_changed": False,
        "ewma_live_weight_enabled": False,
    }

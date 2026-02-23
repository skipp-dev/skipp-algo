from __future__ import annotations

from typing import Any
from .utils import to_float as _to_float

# ---------------------------------------------------------------------------
# Gap-GO / Gap-WATCH classifier defaults
# ---------------------------------------------------------------------------
GO_MIN_GAP_PCT = 1.0
GO_MIN_EXT_SCORE = 0.9
GO_MIN_EXT_VOL_RATIO = 0.06
WATCH_MIN_GAP_PCT = 0.5
DQ_MAX_SPREAD_BPS = 60.0
MACRO_SHORT_BIAS_THRESHOLD = -0.35


def _push_reason(reasons: list[str], code: str) -> None:
    if code and code not in reasons:
        reasons.append(code)


def classify_long_gap(
    row: dict[str, Any],
    *,
    bias: float,
    go_min_gap_pct: float = GO_MIN_GAP_PCT,
    go_min_ext_score: float = GO_MIN_EXT_SCORE,
    go_min_ext_vol_ratio: float = GO_MIN_EXT_VOL_RATIO,
    watch_min_gap_pct: float = WATCH_MIN_GAP_PCT,
    dq_max_spread_bps: float = DQ_MAX_SPREAD_BPS,
    macro_short_bias_threshold: float = MACRO_SHORT_BIAS_THRESHOLD,
) -> dict[str, Any]:
    """Classify a quote into GAP-GO / GAP-WATCH / SKIP buckets (long only).

    Returns::

        {
            "bucket": "GO" | "WATCH" | "SKIP",
            "no_trade_reason": "a;b;c"  (empty string when GO),
            "warn_flags": "x;y"          (informational, never blocks GO),
            "gap_grade": float           (0..5 composite quality score),
        }
    """
    reasons: list[str] = []
    warn_flags: list[str] = []

    gap_available = bool(row.get("gap_available", False))
    gap_pct = float(row.get("gap_pct") or 0.0)
    gap_reason = str(row.get("gap_reason") or "")
    ext_score = float(row.get("ext_hours_score") or 0.0)
    ext_vol_ratio = float(row.get("ext_volume_ratio") or 0.0)
    stale = bool(row.get("premarket_stale", False))
    spread_bps_raw = row.get("premarket_spread_bps")
    spread_bps: float | None = None if spread_bps_raw is None else float(spread_bps_raw)

    earnings_risk = bool(row.get("earnings_risk_window", False))
    corp_penalty = float(row.get("corporate_action_penalty") or 0.0)

    # --- Hard data-quality gates (block GO *and* WATCH) -----------------
    if not gap_available:
        _push_reason(reasons, "gap_not_available")
    if gap_reason in {
        "premarket_unavailable",
        "missing_quote_timestamp",
        "stale_quote_unknown_timestamp",
    }:
        _push_reason(reasons, "premarket_unavailable")
    if stale:
        _push_reason(reasons, "premarket_stale")
    if spread_bps is not None and spread_bps > dq_max_spread_bps:
        _push_reason(reasons, "spread_too_wide")
    if gap_reason == "missing_previous_close":
        _push_reason(reasons, "data_missing_prev_close")

    # --- Warn-only flags (never block GO) --------------------------------
    if earnings_risk:
        _push_reason(warn_flags, "earnings_risk_window")
    if corp_penalty >= 1.0:
        _push_reason(warn_flags, "corporate_action_risk")
    if bias < macro_short_bias_threshold:
        _push_reason(warn_flags, "macro_short_bias")

    # --- Strength gates (distinguish GO from WATCH) ----------------------
    if gap_pct < go_min_gap_pct:
        _push_reason(reasons, "gap_too_small")
    if ext_score < go_min_ext_score:
        _push_reason(reasons, "ext_score_too_low")
    if ext_vol_ratio < go_min_ext_vol_ratio:
        _push_reason(reasons, "ext_vol_too_low")

    # --- Gap grade (0..5 composite) --------------------------------------
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    g = _clamp(gap_pct / 3.0, 0.0, 2.0)
    e = _clamp(ext_score / 2.0, 0.0, 2.0)
    v = _clamp(ext_vol_ratio / 0.10, 0.0, 1.0)
    gap_grade = round(g + e + v, 3)

    # --- Bucket decision --------------------------------------------------
    hard_block_codes = {
        "gap_not_available",
        "premarket_stale",
        "premarket_unavailable",
        "spread_too_wide",
        "data_missing_prev_close",
    }
    strength_codes = {"gap_too_small", "ext_score_too_low", "ext_vol_too_low"}

    hard_block = any(r in hard_block_codes for r in reasons)
    strength_missing = any(r in strength_codes for r in reasons)

    if (not hard_block) and (not strength_missing) and gap_pct > 0:
        bucket = "GO"
        no_trade_reason = ""
    elif (not hard_block) and gap_pct >= watch_min_gap_pct:
        bucket = "WATCH"
        no_trade_reason = ";".join(reasons)
    else:
        bucket = "SKIP"
        no_trade_reason = ";".join(reasons)

    return {
        "bucket": bucket,
        "no_trade_reason": no_trade_reason,
        "warn_flags": ";".join(warn_flags),
        "gap_grade": gap_grade,
    }


MIN_PRICE_THRESHOLD = 5.0
SEVERE_GAP_DOWN_THRESHOLD = -8.0
RISK_OFF_EXTREME_THRESHOLD = -0.75

GAP_CAP_ABS = 10.0
RVOL_CAP = 10.0

WEIGHT_GAP = 0.8
WEIGHT_RVOL = 1.2
WEIGHT_MACRO = 0.7
WEIGHT_MOMENTUM_Z = 0.5
WEIGHT_HVB = 0.3
WEIGHT_EARNINGS_BMO = 1.5
WEIGHT_LIQUIDITY_PENALTY = 1.5
RISK_OFF_PENALTY_MULTIPLIER = 2.0
WEIGHT_EXT_HOURS = 1.0
WEIGHT_CORPORATE_ACTION_PENALTY = 1.0
WEIGHT_ANALYST_CATALYST = 0.5


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
        momentum_z_score = _to_float(quote.get("momentum_z_score"), default=0.0)
        momentum_z_capped = max(min(momentum_z_score, 5.0), -5.0)

        rel_vol = _to_float(quote.get("volume_ratio"), default=0.0)
        if rel_vol <= 0.0:
            rel_vol = (volume / avg_volume) if avg_volume > 0 else 0.0
        is_hvb = bool(quote.get("is_hvb", False))
        earnings_today = bool(quote.get("earnings_today", False))
        earnings_timing = quote.get("earnings_timing") or ""
        is_premarket_mover = bool(quote.get("is_premarket_mover", False))
        ext_hours_score = _to_float(quote.get("ext_hours_score"), default=0.0)
        ext_volume_ratio = _to_float(quote.get("ext_volume_ratio"), default=0.0)
        premarket_stale = bool(quote.get("premarket_stale", False))
        premarket_spread_bps: float | None = _to_float(
            quote.get("premarket_spread_bps"), default=float("nan")
        )
        if premarket_spread_bps != premarket_spread_bps:
            premarket_spread_bps = None
        corporate_action_penalty = _to_float(quote.get("corporate_action_penalty"), default=0.0)
        analyst_catalyst_score = _to_float(quote.get("analyst_catalyst_score"), default=0.0)
        split_today = bool(quote.get("split_today", False))
        dividend_today = bool(quote.get("dividend_today", False))
        ipo_window = bool(quote.get("ipo_window", False))
        premarket_change_raw = quote.get("premarket_change_pct")
        premarket_change_pct_val = _to_float(premarket_change_raw, default=float("nan"))
        premarket_change_pct: float | None = (
            None if premarket_change_pct_val != premarket_change_pct_val else premarket_change_pct_val
        )
        # Cap at 10x: a 50x-volume spike is untradeable at open and would
        # otherwise dominate the entire ranking regardless of other factors.
        rel_vol_capped = min(rel_vol, RVOL_CAP)
        liquidity_penalty = 1.0 if price < MIN_PRICE_THRESHOLD else 0.0

        # Risk-off days reduce long-breakout appetite.
        risk_off_penalty = abs(min(bias, 0.0)) * RISK_OFF_PENALTY_MULTIPLIER

        gap_component = WEIGHT_GAP * max(min(gap_pct_for_scoring, GAP_CAP_ABS), -GAP_CAP_ABS)
        rvol_component = WEIGHT_RVOL * rel_vol_capped
        macro_component = WEIGHT_MACRO * max(bias, 0.0)
        momentum_component = WEIGHT_MOMENTUM_Z * momentum_z_capped
        hvb_component = WEIGHT_HVB if is_hvb else 0.0
        # BMO earnings are the strongest pre-market catalyst — symbols reporting
        # before market open deserve a significant ranking boost.
        earnings_bmo = earnings_today and str(earnings_timing).lower() in {"bmo", "before market open"}
        earnings_bmo_component = WEIGHT_EARNINGS_BMO if earnings_bmo else 0.0
        news_score = by_symbol_news.get(symbol, 0.0)
        news_component = news_score
        ext_hours_component = WEIGHT_EXT_HOURS * ext_hours_score
        corporate_action_penalty_component = WEIGHT_CORPORATE_ACTION_PENALTY * max(corporate_action_penalty, 0.0)
        analyst_catalyst_component = WEIGHT_ANALYST_CATALYST * analyst_catalyst_score
        liquidity_penalty_component = WEIGHT_LIQUIDITY_PENALTY * liquidity_penalty
        risk_off_penalty_component = risk_off_penalty

        score = 0.0
        # Cap gap at ±10 % so extreme overnight gaps don't dominate the score;
        # a +20 % gap is usually untradeable at open anyway.
        score += gap_component
        score += rvol_component
        score += macro_component
        score += momentum_component
        score += hvb_component
        score += earnings_bmo_component
        score += news_component
        score += ext_hours_component
        score += analyst_catalyst_component
        score -= liquidity_penalty_component
        score -= corporate_action_penalty_component
        score -= risk_off_penalty_component

        no_trade_reason: list[str] = []
        allowed_setups = ["orb", "gap_go", "vwap_reclaim", "hod_reclaim"]
        max_trades = 2
        data_sufficiency_low = avg_volume <= 0.0 or rel_vol <= 0.0

        if price < MIN_PRICE_THRESHOLD:
            no_trade_reason.append("price_below_5")
        if bias <= RISK_OFF_EXTREME_THRESHOLD:
            no_trade_reason.append("macro_risk_off_extreme")
            allowed_setups = ["vwap_reclaim"]
            max_trades = 1
            if rel_vol <= 0.0:
                no_trade_reason.append("missing_rvol")
        if gap_pct <= SEVERE_GAP_DOWN_THRESHOLD:
            no_trade_reason.append("severe_gap_down")
        if split_today:
            no_trade_reason.append("split_today")
        if ipo_window:
            no_trade_reason.append("ipo_window")
        if bias < -0.25 and bias > RISK_OFF_EXTREME_THRESHOLD:
            no_trade_reason.append("macro_bias_short")
        if premarket_stale:
            no_trade_reason.append("premarket_stale")
        if premarket_spread_bps is not None and premarket_spread_bps > 200.0:
            no_trade_reason.append("spread_too_wide")
        if avg_volume > 0.0 and avg_volume < 100_000:
            no_trade_reason.append("insufficient_liquidity")
        if atr <= 0.0:
            no_trade_reason.append("atr_missing")
        earnings_risk_window = bool(quote.get("earnings_risk_window", False))
        if earnings_risk_window:
            no_trade_reason.append("earnings_risk_window")

        long_allowed = not any(
            r in no_trade_reason
            for r in [
                "price_below_5",
                "severe_gap_down",
                "missing_rvol",
                "macro_risk_off_extreme",
                "split_today",
                "ipo_window",
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
                "volume_ratio": round(rel_vol, 4),
                "rel_volume_capped": round(rel_vol_capped, 4),
                "is_hvb": is_hvb,
                "momentum_z_score": round(momentum_z_capped, 4),
                "pdh": quote.get("pdh"),
                "pdl": quote.get("pdl"),
                "pdh_source": quote.get("pdh_source"),
                "pdl_source": quote.get("pdl_source"),
                "dist_to_pdh_atr": quote.get("dist_to_pdh_atr"),
                "dist_to_pdl_atr": quote.get("dist_to_pdl_atr"),
                "earnings_today": earnings_today,
                "earnings_timing": earnings_timing or None,
                "earnings_bmo": earnings_bmo,
                "is_premarket_mover": is_premarket_mover,
                "premarket_change_pct": premarket_change_pct,
                "ext_hours_score": round(ext_hours_score, 4),
                "ext_volume_ratio": round(ext_volume_ratio, 6),
                "premarket_stale": premarket_stale,
                "premarket_spread_bps": premarket_spread_bps,
                "split_today": split_today,
                "dividend_today": dividend_today,
                "ipo_window": ipo_window,
                "corporate_action_penalty": round(max(corporate_action_penalty, 0.0), 4),
                "analyst_catalyst_score": round(analyst_catalyst_score, 4),
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
                    "momentum_component": round(momentum_component, 4),
                    "hvb_component": round(hvb_component, 4),
                    "earnings_bmo_component": round(earnings_bmo_component, 4),
                    "news_component": round(news_component, 4),
                    "ext_hours_component": round(ext_hours_component, 4),
                    "analyst_catalyst_component": round(analyst_catalyst_component, 4),
                    "corporate_action_penalty": round(corporate_action_penalty_component, 4),
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

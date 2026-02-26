from __future__ import annotations

from typing import Any

from .utils import MIN_PRICE_THRESHOLD, SEVERE_GAP_DOWN_THRESHOLD
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


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


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
            "no_trade_reason": ["a", "b", "c"]  (empty list when GO),
            "warn_flags": "x;y"          (informational, never blocks GO),
            "gap_grade": float           (0..5 composite quality score),
        }
    """
    reasons: list[str] = []
    warn_flags: list[str] = []

    gap_available = bool(row.get("gap_available", False))
    gap_pct = _to_float(row.get("gap_pct"), default=0.0)
    gap_reason = str(row.get("gap_reason") or "")
    ext_score = _to_float(row.get("ext_hours_score"), default=0.0)
    ext_vol_ratio = _to_float(row.get("ext_volume_ratio"), default=0.0)
    stale = bool(row.get("premarket_stale", False))
    spread_bps_raw = row.get("premarket_spread_bps")
    spread_bps: float | None = None if spread_bps_raw is None else _to_float(spread_bps_raw, default=0.0)

    earnings_risk = bool(row.get("earnings_risk_window", False))
    corp_penalty = _to_float(row.get("corporate_action_penalty"), default=0.0)

    # --- Data-quality checks (warn-only, fail-open) ----------------------
    if not gap_available:
        _push_reason(warn_flags, "gap_not_available")
    if gap_reason in {
        "premarket_unavailable",
        "missing_quote_timestamp",
        "stale_quote_unknown_timestamp",
    }:
        _push_reason(warn_flags, "premarket_unavailable")
    if stale:
        _push_reason(warn_flags, "premarket_stale")
    if spread_bps is not None and spread_bps > dq_max_spread_bps:
        _push_reason(warn_flags, "spread_too_wide")
    if gap_reason == "missing_previous_close":
        _push_reason(warn_flags, "data_missing_prev_close")

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
    g = _clamp(gap_pct / 3.0, 0.0, 2.0)
    e = _clamp(ext_score / 2.0, 0.0, 2.0)
    v = _clamp(ext_vol_ratio / 0.10, 0.0, 1.0)
    gap_grade = round(g + e + v, 3)

    # --- Bucket decision --------------------------------------------------
    strength_codes = {"gap_too_small", "ext_score_too_low", "ext_vol_too_low"}

    strength_missing = any(r in strength_codes for r in reasons)

    if (not strength_missing) and gap_pct > 0:
        bucket = "GO"
        no_trade_reason: list[str] = []
    elif gap_pct >= watch_min_gap_pct:
        bucket = "WATCH"
        no_trade_reason = list(reasons)
    else:
        bucket = "SKIP"
        no_trade_reason = list(reasons)

    return {
        "bucket": bucket,
        "no_trade_reason": no_trade_reason,
        "warn_flags": ";".join(warn_flags),
        "gap_grade": gap_grade,
    }


# ---------------------------------------------------------------------------
# Gap warn-flags (LONG-only informational flags for chart confirmation)
# ---------------------------------------------------------------------------

GAP_UP_MIN_PCT = 0.30
GAP_DOWN_MIN_PCT = -0.30
FALLING_KNIFE_GAP_PCT = -0.50
RECLAIM_BUFFER = 0.0015  # 0.15 %
GAP_LARGE_ATR_RATIO = 0.80
SPREAD_WARN_BPS = 40.0


def compute_gap_warn_flags(row: dict[str, Any]) -> list[str]:
    """Compute LONG-only gap warn flags from a single enriched quote row.

    Flags are informational and never block trading.  They augment the
    existing ``warn_flags`` from :func:`classify_long_gap`.

    Possible flags::

        gap_up_hold_ok          — gap-up & price holds above key levels
        gap_up_fade_risk        — gap-up but price fading below key levels
        gap_down_reversal_ok    — gap-down but reclaiming key levels
        gap_down_falling_knife  — severe gap-down with no reclaim signal
        gap_large_atr           — gap magnitude exceeds 80 % of ATR
        warn_spread_wide        — premarket spread > 40 bps
        warn_premarket_stale    — premarket quote is stale
        warn_no_pmh             — gap-up but no premarket high available
    """
    flags: list[str] = []

    gap_pct = _to_float(row.get("gap_pct"), default=0.0)
    price = _to_float(row.get("price"), default=0.0)

    vwap_raw = row.get("vwap")
    vwap: float | None = None if vwap_raw is None else _to_float(vwap_raw, default=0.0) or None

    pdl_raw = row.get("pdl")
    pdl: float | None = None if pdl_raw is None else _to_float(pdl_raw, default=0.0) or None

    pdh_raw = row.get("pdh")
    pdh: float | None = None if pdh_raw is None else _to_float(pdh_raw, default=0.0) or None

    pmh_raw = row.get("premarket_high")
    pmh: float | None = None if pmh_raw is None else _to_float(pmh_raw, default=0.0) or None

    atr_raw = row.get("atr")
    atr: float | None = None if atr_raw is None else _to_float(atr_raw, default=0.0) or None

    prev_close_raw = row.get("previousClose")
    prev_close: float | None = None if prev_close_raw is None else _to_float(prev_close_raw, default=0.0) or None

    momentum_z = _to_float(row.get("momentum_z_score"), default=0.0)
    ext_score = _to_float(row.get("ext_hours_score"), default=0.0)
    spread_bps_raw = row.get("premarket_spread_bps")
    stale = bool(row.get("premarket_stale", False))

    buf = RECLAIM_BUFFER

    # ATR % normalisation
    atr_pct: float | None = None
    if atr is not None and prev_close is not None and atr > 0 and prev_close > 0:
        atr_pct = (atr / prev_close) * 100.0

    def _above(level: float | None) -> bool:
        if level is None or level <= 0 or price <= 0:
            return False
        return price > level * (1.0 + buf)

    def _below(level: float | None) -> bool:
        if level is None or level <= 0 or price <= 0:
            return False
        return price < level * (1.0 - buf)

    # --- GAP UP ---
    if gap_pct > GAP_UP_MIN_PCT:
        hold_ok = False
        if vwap is not None and vwap > 0 and price > vwap:
            if pmh is not None and pmh > 0:
                hold_ok = price > pmh
            elif pdh is not None and pdh > 0:
                hold_ok = price > pdh
            else:
                hold_ok = True
        if hold_ok:
            flags.append("gap_up_hold_ok")

        fade_risk = False
        if vwap is not None and vwap > 0 and price < vwap:
            fade_risk = True
        if pmh is not None and pmh > 0 and price < pmh:
            fade_risk = True
        if fade_risk:
            flags.append("gap_up_fade_risk")

        if pmh is None:
            flags.append("warn_no_pmh")

    # --- GAP DOWN ---
    if gap_pct < GAP_DOWN_MIN_PCT:
        if _above(vwap) or _above(pdl) or _above(pmh):
            if ext_score > -0.8:
                flags.append("gap_down_reversal_ok")

        if (
            gap_pct < FALLING_KNIFE_GAP_PCT
            and _below(pdl)
            and momentum_z < 0.0
            and ext_score < -0.30
        ):
            flags.append("gap_down_falling_knife")

    # --- Large relative gap (ATR-normalised) ---
    if atr_pct is not None and atr_pct > 0:
        if abs(gap_pct) > GAP_LARGE_ATR_RATIO * atr_pct:
            flags.append("gap_large_atr")

    # --- Data quality / liquidity warnings ---
    if spread_bps_raw is not None:
        spread_bps = _to_float(spread_bps_raw, default=0.0)
        if spread_bps > SPREAD_WARN_BPS:
            flags.append("warn_spread_wide")

    if stale:
        flags.append("warn_premarket_stale")

    return flags


# Filter thresholds (MIN_PRICE_THRESHOLD and SEVERE_GAP_DOWN_THRESHOLD imported from utils)
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
WEIGHT_NEWS = 0.8
WEIGHT_EXT_HOURS = 1.0
WEIGHT_CORPORATE_ACTION_PENALTY = 1.0
WEIGHT_ANALYST_CATALYST = 0.5


def rank_candidates(
    quotes: list[dict[str, Any]],
    bias: float,
    top_n: int = 20,
    news_scores: dict[str, float] | None = None,
    news_metrics: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank long candidates from quote snapshots.

    .. deprecated::
        Use ``scorer.rank_candidates_v2`` instead.  This v1 ranker is kept
        for backward compatibility with external scripts that import it
        directly.  It lacks sector-relative scoring, freshness decay,
        diminishing-returns compression and adaptive gating that v2 provides.

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
    by_symbol_news_metrics: dict[str, dict[str, Any]] = {}
    for nm_key, nm_val in (news_metrics or {}).items():
        if isinstance(nm_val, dict):
            by_symbol_news_metrics[str(nm_key).upper()] = nm_val

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
        gap_available = False if gap_available_raw is None else bool(gap_available_raw)
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
        news_component = WEIGHT_NEWS * news_score
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
                "gap_scope": quote.get("gap_scope"),
                "gap_available": gap_available,
                "gap_from_ts": quote.get("gap_from_ts"),
                "gap_to_ts": quote.get("gap_to_ts"),
                "gap_reason": quote.get("gap_reason"),
                "gap_bucket": quote.get("gap_bucket"),
                "gap_grade": quote.get("gap_grade"),
                "warn_flags": quote.get("warn_flags", ""),
                "volume": volume,
                "avg_volume": avg_volume,
                "atr": round(atr, 4),
                "atr_pct": quote.get("atr_pct"),
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
                "premarket_high": quote.get("premarket_high"),
                "premarket_low": quote.get("premarket_low"),
                "ext_hours_score": round(ext_hours_score, 4),
                "premarket_stale": premarket_stale,
                "premarket_spread_bps": premarket_spread_bps,
                "split_today": split_today,
                "dividend_today": dividend_today,
                "ipo_window": ipo_window,
                "corporate_action_penalty": round(max(corporate_action_penalty, 0.0), 4),
                "analyst_catalyst_score": round(analyst_catalyst_score, 4),
                "macro_bias": round(bias, 4),
                "news_catalyst_score": round(news_score, 4),
                "news_sentiment_emoji": by_symbol_news_metrics.get(symbol, {}).get("sentiment_emoji", "🟡"),
                "news_sentiment_label": by_symbol_news_metrics.get(symbol, {}).get("sentiment_label", "neutral"),
                "news_sentiment_score": by_symbol_news_metrics.get(symbol, {}).get("sentiment_score", 0.0),
                "upgrade_downgrade_emoji": quote.get("upgrade_downgrade_emoji", ""),
                "upgrade_downgrade_label": quote.get("upgrade_downgrade_label", ""),
                "upgrade_downgrade_action": quote.get("upgrade_downgrade_action", ""),
                "upgrade_downgrade_firm": quote.get("upgrade_downgrade_firm", ""),
                "upgrade_downgrade_date": quote.get("upgrade_downgrade_date"),
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

    # Sort by score (desc), then symbol (asc) for deterministic tie-breaking
    ranked.sort(key=lambda row: (-row["score"], row["symbol"]))
    return ranked[:top_n]

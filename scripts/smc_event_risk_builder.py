"""V5 Event Risk Layer builder.

Derives a flat event-risk block from calendar events, news/sentiment
output, and optional manual overrides.  Every field is a Pine-compatible
scalar or CSV ticker list.

The canonical output matches :class:`EventRiskBlock` in
``smc_enrichment_types``.

Usage::

    from scripts.smc_event_risk_builder import build_event_risk

    risk = build_event_risk(
        calendar=enrichment.get("calendar", {}),
        news=enrichment.get("news", {}),
        overrides=operator_overrides,
    )
    enrichment["event_risk"] = risk
"""
from __future__ import annotations

import logging
from datetime import datetime, time, UTC
from typing import Any

logger = logging.getLogger(__name__)


# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "EVENT_WINDOW_STATE": "CLEAR",
    "EVENT_RISK_LEVEL": "NONE",
    "NEXT_EVENT_CLASS": "",
    "NEXT_EVENT_NAME": "",
    "NEXT_EVENT_TIME": "",
    "NEXT_EVENT_IMPACT": "NONE",
    "EVENT_RESTRICT_BEFORE_MIN": 0,
    "EVENT_RESTRICT_AFTER_MIN": 0,
    "EVENT_COOLDOWN_ACTIVE": False,
    "MARKET_EVENT_BLOCKED": False,
    "SYMBOL_EVENT_BLOCKED": False,
    "EARNINGS_SOON_TICKERS": "",
    "HIGH_RISK_EVENT_TICKERS": "",
    "EVENT_PROVIDER_STATUS": "ok",
}

# ── Impact → restriction mapping ───────────────────────────────────
# Minutes to restrict trading before and after each impact level.
# Kept as plain constants — no magic heuristics.

IMPACT_RESTRICT: dict[str, tuple[int, int]] = {
    "HIGH": (30, 15),
    "MEDIUM": (15, 5),
    "LOW": (5, 0),
    "NONE": (0, 0),
}

# ── Risk-level classification thresholds ────────────────────────────

_RISK_LEVEL_FROM_IMPACT: dict[str, str] = {
    "HIGH": "HIGH",
    "MEDIUM": "ELEVATED",
    "LOW": "LOW",
    "NONE": "NONE",
}


# ── Public API ──────────────────────────────────────────────────────


def build_event_risk(
    *,
    calendar: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the v5 event-risk block.

    Parameters
    ----------
    calendar:
        Normalized calendar block from the enrichment pipeline.
        Expected keys: ``high_impact_macro_today``, ``macro_event_name``,
        ``macro_event_time``, ``earnings_today_tickers``,
        ``earnings_tomorrow_tickers``, ``earnings_bmo_tickers``,
        ``earnings_amc_tickers``.
    news:
        News/sentiment block from the enrichment pipeline.
        Expected keys: ``bearish_tickers``, ``news_heat_global``.
    overrides:
        Optional operator overrides.  Any key matching a field in the
        output will replace the derived value.  This is the only place
        where manual policy injection happens.
    now:
        Current UTC timestamp.  Defaults to ``datetime.now(UTC)``.
        Injecting this makes the builder fully deterministic for tests.

    Returns
    -------
    dict[str, Any]
        Flat dict matching :class:`EventRiskBlock`.  Every key has a
        guaranteed value — callers never need to default-guard.
    """
    cal = calendar or {}
    nws = news or {}
    ovr = overrides or {}
    if now is None:
        now = datetime.now(UTC)

    result = dict(DEFAULTS)

    # ── 1. Macro event detection ────────────────────────────────
    high_impact = bool(cal.get("high_impact_macro_today", False))
    macro_name = str(cal.get("macro_event_name", "")).strip()
    macro_time_raw = str(cal.get("macro_event_time", "")).strip()

    if high_impact and macro_name:
        impact = "HIGH"
        result["NEXT_EVENT_CLASS"] = "MACRO"
        result["NEXT_EVENT_NAME"] = macro_name
        result["NEXT_EVENT_TIME"] = macro_time_raw
        result["NEXT_EVENT_IMPACT"] = impact
        result["EVENT_RISK_LEVEL"] = _RISK_LEVEL_FROM_IMPACT[impact]

        before_min, after_min = IMPACT_RESTRICT[impact]
        result["EVENT_RESTRICT_BEFORE_MIN"] = before_min
        result["EVENT_RESTRICT_AFTER_MIN"] = after_min

        window_state = _compute_window_state(
            macro_time_raw, now, before_min, after_min,
        )
        result["EVENT_WINDOW_STATE"] = window_state

        if window_state == "ACTIVE":
            result["MARKET_EVENT_BLOCKED"] = True
        if window_state == "COOLDOWN":
            result["EVENT_COOLDOWN_ACTIVE"] = True

    # ── 2. Earnings detection ───────────────────────────────────
    earnings_soon = _merge_ticker_lists(
        cal.get("earnings_today_tickers", ""),
        cal.get("earnings_tomorrow_tickers", ""),
        cal.get("earnings_bmo_tickers", ""),
        cal.get("earnings_amc_tickers", ""),
    )
    result["EARNINGS_SOON_TICKERS"] = earnings_soon

    if earnings_soon:
        # Earnings are symbol-level events, not market-level
        result["SYMBOL_EVENT_BLOCKED"] = True
        # If no macro event was detected, promote class to EARNINGS
        if not result["NEXT_EVENT_CLASS"]:
            result["NEXT_EVENT_CLASS"] = "EARNINGS"
            result["NEXT_EVENT_NAME"] = "Earnings"
            result["NEXT_EVENT_IMPACT"] = "MEDIUM"
            result["EVENT_RISK_LEVEL"] = _RISK_LEVEL_FROM_IMPACT["MEDIUM"]
            before_min, after_min = IMPACT_RESTRICT["MEDIUM"]
            result["EVENT_RESTRICT_BEFORE_MIN"] = before_min
            result["EVENT_RESTRICT_AFTER_MIN"] = after_min

    # ── 3. News-based high-risk tickers ─────────────────────────
    bearish_tickers = nws.get("bearish_tickers", [])
    heat_global = float(nws.get("news_heat_global", 0.0))

    high_risk_from_news: list[str] = []
    if isinstance(bearish_tickers, list) and bearish_tickers:
        high_risk_from_news = [str(t).strip().upper() for t in bearish_tickers if str(t).strip()]
    # Heat > 0.8 means the overall news environment is extremely negative
    if heat_global > 0.8 and not result["MARKET_EVENT_BLOCKED"]:
        result["EVENT_RISK_LEVEL"] = max(
            result["EVENT_RISK_LEVEL"],
            "ELEVATED",
            key=lambda v: ["NONE", "LOW", "ELEVATED", "HIGH"].index(v),
        )

    high_risk_tickers = _merge_ticker_lists(
        ",".join(high_risk_from_news),
        earnings_soon,
    )
    result["HIGH_RISK_EVENT_TICKERS"] = high_risk_tickers

    # ── 4. Provider status ──────────────────────────────────────
    # If calendar was empty and news was empty, mark as degraded
    if not cal and not nws:
        result["EVENT_PROVIDER_STATUS"] = "no_data"
    elif not cal:
        result["EVENT_PROVIDER_STATUS"] = "calendar_missing"
    elif not nws:
        result["EVENT_PROVIDER_STATUS"] = "news_missing"

    # ── 5. Manual overrides (last, flat merge) ──────────────────
    for key, value in ovr.items():
        if key in DEFAULTS:
            result[key] = value
            logger.info("Event risk override applied: %s = %r", key, value)

    return result


# ── Internal helpers ────────────────────────────────────────────────


def _compute_window_state(
    event_time_raw: str,
    now: datetime,
    before_min: int,
    after_min: int,
) -> str:
    """Classify the current time relative to the event window.

    Returns one of: ``"PRE_EVENT"``, ``"ACTIVE"``, ``"COOLDOWN"``,
    ``"CLEAR"``.
    """
    event_time = _parse_event_time(event_time_raw)
    if event_time is None:
        # Cannot parse → treat as PRE_EVENT (safe default: restrict)
        return "PRE_EVENT" if before_min > 0 else "CLEAR"

    # Build event datetime using today's date
    event_dt = datetime.combine(now.date(), event_time, tzinfo=UTC)

    delta_minutes = (event_dt - now).total_seconds() / 60.0

    if delta_minutes > before_min:
        return "CLEAR"
    if delta_minutes > 0:
        return "PRE_EVENT"
    if abs(delta_minutes) <= after_min:
        return "COOLDOWN"
    return "CLEAR"


def _parse_event_time(raw: str) -> time | None:
    """Try common time formats.  Returns None on failure."""
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(raw.strip(), fmt).time()
        except ValueError:
            continue
    return None


def _merge_ticker_lists(*csv_strings: str) -> str:
    """Merge multiple comma-separated ticker strings, deduplicated and sorted."""
    tickers: set[str] = set()
    for csv in csv_strings:
        if not csv:
            continue
        for token in str(csv).split(","):
            token = token.strip().upper()
            if token:
                tickers.add(token)
    return ",".join(sorted(tickers))

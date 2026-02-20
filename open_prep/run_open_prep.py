from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .trade_cards import build_trade_cards
from .bea import build_bea_audit_payload
from .macro import (
    FMPClient,
    dedupe_events,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    get_consensus,
    macro_bias_with_components,
)
from .news import build_news_scores
from .screen import rank_candidates

DEFAULT_UNIVERSE = [
    "NVDA",
    "PLTR",
    "PWR",
    "TSLA",
    "AMD",
    "META",
    "MSFT",
    "AMZN",
    "GOOGL",
    "SMCI",
]

PREFERRED_US_OPEN_UTC_TIMES: tuple[str, ...] = ("13:30:00", "14:30:00", "15:00:00")


def _extract_time_str(event_date: str) -> str:
    """Extract HH:MM:SS time component from a date string.

    Handles both space-separated ("YYYY-MM-DD HH:MM:SS") and
    ISO-8601 T-separated ("YYYY-MM-DDTHH:MM:SS") formats.
    Returns "99:99:99" when no time component is found (whole-day events).
    """
    for sep in (" ", "T"):
        idx = event_date.find(sep)
        if idx != -1:
            time_part = event_date[idx + 1 :].strip()
            match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", time_part)
            if not match:
                continue

            hour = int(match.group(1))
            minute = int(match.group(2))
            second = int(match.group(3) or "0")
            if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
                return f"{hour:02d}:{minute:02d}:{second:02d}"
    return "99:99:99"


def _macro_relevance_score(event_name: str) -> int:
    name = event_name.lower()
    score = 0

    # Rates/inflation/labor shocks first.
    if any(token in name for token in ("cpi", "ppi", "pce", "nonfarm payroll", "jobless claims")):
        score += 30
    # Growth pulse tier.
    elif any(token in name for token in ("gdp", "ism", "retail sales", "consumer sentiment")):
        score += 20
    # Housing and secondary surveys.
    elif any(token in name for token in ("home sales", "housing", "durable goods", "factory orders")):
        score += 10

    return score


def _sort_macro_events(events: list[dict]) -> list[dict]:
    def key_fn(event: dict) -> tuple[int, int, int, str, str]:
        impact_raw = str(event.get("impact", event.get("importance", event.get("priority"))) or "").lower()
        impact_rank = 2 if impact_raw == "high" else 1 if impact_raw in {"medium", "mid", "moderate"} else 0

        date_str = str(event.get("date") or "")
        time_str = _extract_time_str(date_str)
        open_time_rank = 1 if time_str in PREFERRED_US_OPEN_UTC_TIMES else 0

        name = str(event.get("event") or event.get("name") or "")
        relevance = _macro_relevance_score(name)

        # Desc for impact/open-time/relevance, asc for date+name (stable tiebreaker).
        return (-impact_rank, -open_time_rank, -relevance, date_str, name.lower())

    return sorted(events, key=key_fn)


def _filter_events_by_cutoff_utc(
    events: list[dict], cutoff_utc: str, include_untimed: bool = True
) -> list[dict]:
    """Keep events whose time component is <= cutoff_utc (HH:MM:SS).

    Events without a time component in their date field are treated as
    whole-day releases and included by default (include_untimed=True),
    so day-scope macro announcements are never silently dropped.
    Both space-separated and ISO T-separated date strings are handled.
    """
    out: list[dict] = []
    cutoff = _normalize_cutoff_utc(cutoff_utc)

    for event in events:
        date_str = str(event.get("date") or "")
        time_str = _extract_time_str(date_str)
        if time_str == "99:99:99":
            # No intraday timestamp — treat as a whole-day release.
            if include_untimed:
                out.append(event)
            continue
        if time_str <= cutoff:
            out.append(event)
    return out


def _normalize_cutoff_utc(cutoff_utc: str) -> str:
    """Validate and normalize cutoff time to HH:MM:SS."""
    raw = str(cutoff_utc or "").strip()
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Expected HH:MM or HH:MM:SS")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError("Expected numeric HH:MM or HH:MM:SS") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("Time parts out of range (HH 0-23, MM/SS 0-59)")

    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build macro-aware long-breakout candidates ahead of US open."
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_UNIVERSE),
        help="Comma-separated ticker universe.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=3,
        help="How many calendar days to scan for macro events.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many ranked candidates to keep.",
    )
    parser.add_argument(
        "--trade-cards",
        type=int,
        default=5,
        help="How many trade cards to generate from top ranked names.",
    )
    parser.add_argument(
        "--max-macro-events",
        type=int,
        default=15,
        help="Maximum number of macro events to include per output list.",
    )
    parser.add_argument(
        "--pre-open-only",
        action="store_true",
        help="If set, only include today's events up to the cutoff UTC time.",
    )
    parser.add_argument(
        "--pre-open-cutoff-utc",
        type=str,
        default="16:00:00",
        help="UTC cutoff (HH:MM:SS) used with --pre-open-only, default 16:00:00.",
    )
    return parser.parse_args()


def _event_is_today(event: dict, today: date) -> bool:
    """Match an event to today regardless of whether FMP returns ISO or US-style dates."""
    date_str = str(event.get("date") or "")
    # ISO: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...
    if date_str.startswith(today.isoformat()):
        return True
    # US format: MM/DD/YYYY [HH:MM:SS]
    date_part = date_str.split(" ")[0]
    parts = date_part.split("/")
    if len(parts) == 3:
        try:
            year = int(parts[2])
            if year < 100:
                year += 2000
            return date(year, int(parts[0]), int(parts[1])) == today
        except ValueError:
            pass
    return False


def _format_macro_events(events: list[dict], max_events: int) -> list[dict]:
    out: list[dict] = []
    for event in _sort_macro_events(events)[: max(max_events, 0)]:
        consensus_value, consensus_field = get_consensus(event)
        # Compute quality flags inline (same logic as macro._annotate_event_quality)
        # to avoid depending on mutation side-effects.
        quality_flags: list[str] = []
        if event.get("actual") is None:
            quality_flags.append("missing_actual")
        if consensus_value is None:
            quality_flags.append("missing_consensus")
        if not event.get("unit"):
            quality_flags.append("missing_unit")
        out.append(
            {
                "date": event.get("date"),
                "event": event.get("event") or event.get("name"),
                "canonical_event": event.get("canonical_event"),
                "impact": event.get("impact", event.get("importance", event.get("priority"))),
                "actual": event.get("actual"),
                "consensus": consensus_value,
                "consensus_field": consensus_field,
                "previous": event.get("previous"),
                "unit": event.get("unit"),
                "data_quality_flags": quality_flags,
                "dedup": event.get("dedup"),
                "country": event.get("country"),
                "currency": event.get("currency"),
            }
        )
    return out


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _calculate_atr14_from_eod(candles: list[dict]) -> float:
    """Calculate ATR(14) from EOD OHLC candles.

    Expects each candle to expose high, low, close. Uses classic True Range and
    returns SMA(TR, 14). If fewer than 14 valid bars are available, uses all
    available TR values (minimum 2 bars required).
    """
    parsed: list[tuple[str, float, float, float]] = []
    for c in candles:
        d = str(c.get("date") or "")
        if not d:
            continue
        high = _to_float(c.get("high"), default=float("nan"))
        low = _to_float(c.get("low"), default=float("nan"))
        close = _to_float(c.get("close"), default=float("nan"))
        if any(x != x for x in (high, low, close)):  # NaN check
            continue
        parsed.append((d, high, low, close))

    if len(parsed) < 2:
        return 0.0

    parsed.sort(key=lambda row: row[0])
    tr_values: list[float] = []
    prev_close: float | None = None
    for _, high, low, close in parsed:
        if prev_close is None:
            tr = max(high - low, 0.0)
        else:
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
        tr_values.append(max(tr, 0.0))
        prev_close = close

    if not tr_values:
        return 0.0
    window = tr_values[-14:] if len(tr_values) >= 14 else tr_values
    return round(sum(window) / len(window), 4)


def _atr14_by_symbol(
    client: FMPClient,
    symbols: list[str],
    as_of: date,
    lookback_days: int = 60,
) -> tuple[dict[str, float], dict[str, str]]:
    atr_map: dict[str, float] = {}
    errors: dict[str, str] = {}
    date_from = as_of - timedelta(days=max(lookback_days, 20))
    for symbol in symbols:
        try:
            candles = client.get_historical_price_eod_full(symbol, date_from, as_of)
            atr_map[symbol] = _calculate_atr14_from_eod(candles)
        except RuntimeError as exc:
            atr_map[symbol] = 0.0
            errors[symbol] = str(exc)
    return atr_map, errors


def _inputs_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> None:
    args = _parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        raise ValueError("No symbols provided. Use --symbols with comma-separated tickers.")

    today = datetime.now(UTC).date()
    end_date = today + timedelta(days=max(args.days_ahead, 1))

    client = FMPClient.from_env()
    try:
        macro_events = client.get_macro_calendar(today, end_date)
    except RuntimeError as exc:
        raise SystemExit(f"[open_prep] Macro calendar fetch failed: {exc}") from exc

    todays_events = [event for event in macro_events if _event_is_today(event, today)]

    if args.pre_open_only:
        try:
            todays_events = _filter_events_by_cutoff_utc(todays_events, args.pre_open_cutoff_utc)
        except ValueError as exc:
            raise SystemExit(f"[open_prep] Invalid --pre-open-cutoff-utc: {exc}") from exc

    todays_us_events = dedupe_events(filter_us_events(todays_events))
    todays_us_high_impact_events = filter_us_high_impact_events(todays_us_events)
    todays_us_mid_impact_events = filter_us_mid_impact_events(todays_us_events)

    macro_analysis = macro_bias_with_components(todays_events)
    bias = float(macro_analysis["macro_bias"])
    bea_audit_enabled = str(os.environ.get("OPEN_PREP_BEA_AUDIT", "1")).strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }
    bea_audit = build_bea_audit_payload(
        macro_analysis.get("events_for_bias", []),
        enabled=bea_audit_enabled,
    )

    # Optional catalyst boost from latest FMP articles (stable endpoint).
    # If news fetch fails, ranking still proceeds with pure market+macro features.
    news_scores: dict[str, float] = {}
    news_metrics: dict[str, dict] = {}
    news_fetch_error: str | None = None
    try:
        articles = client.get_fmp_articles(limit=250)
        news_scores, news_metrics = build_news_scores(symbols=symbols, articles=articles)
    except RuntimeError as exc:
        news_fetch_error = str(exc)

    try:
        quotes = client.get_batch_quotes(symbols)
    except RuntimeError as exc:
        raise SystemExit(f"[open_prep] Quote fetch failed: {exc}") from exc

    atr_by_symbol, atr_fetch_errors = _atr14_by_symbol(client=client, symbols=symbols, as_of=today)
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        if not sym:
            continue
        q["atr"] = atr_by_symbol.get(sym, 0.0)

    ranked = rank_candidates(
        quotes=quotes,
        bias=bias,
        top_n=max(args.top, 1),
        news_scores=news_scores,
    )
    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=max(args.trade_cards, 1))

    result = {
        "schema_version": "open_prep_v1",
        "code_version": os.environ.get("OPEN_PREP_CODE_VERSION", os.environ.get("GIT_SHA", "unknown")),
        "inputs_hash": _inputs_hash(
            {
                "run_date_utc": today.isoformat(),
                "symbols": symbols,
                "days_ahead": args.days_ahead,
                "top": args.top,
                "trade_cards": args.trade_cards,
                "max_macro_events": args.max_macro_events,
                "pre_open_only": args.pre_open_only,
                "pre_open_cutoff_utc": args.pre_open_cutoff_utc,
            }
        ),
        "run_date_utc": today.isoformat(),
        "pre_open_only": bool(args.pre_open_only),
        "pre_open_cutoff_utc": args.pre_open_cutoff_utc,
        "macro_bias": round(bias, 4),
        "macro_raw_score": round(float(macro_analysis.get("raw_score", 0.0)), 4),
        "macro_event_count_today": len(todays_events),
        "macro_us_event_count_today": len(todays_us_events),
        "macro_us_high_impact_event_count_today": len(todays_us_high_impact_events),
        "macro_us_mid_impact_event_count_today": len(todays_us_mid_impact_events),
        "macro_events_for_bias": _format_macro_events(
            macro_analysis.get("events_for_bias", []), args.max_macro_events
        ),
        "macro_score_components": macro_analysis.get("score_components", []),
        "bea_audit": bea_audit,
        "macro_us_high_impact_events_today": _format_macro_events(
            todays_us_high_impact_events, args.max_macro_events
        ),
        "macro_us_mid_impact_events_today": _format_macro_events(
            todays_us_mid_impact_events, args.max_macro_events
        ),
        "news_catalyst_by_symbol": news_metrics,
        "news_fetch_error": news_fetch_error,
        "atr14_by_symbol": atr_by_symbol,
        "atr_fetch_errors": atr_fetch_errors,
        "ranked_candidates": ranked,
        "trade_cards": cards,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

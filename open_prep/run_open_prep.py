from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, date, datetime, timedelta

from .ai import build_trade_cards
from .macro import (
    FMPClient,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    macro_bias_score,
)
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
    cutoff = cutoff_utc.strip()
    # Normalize cutoff to HH:MM:SS to ensure lexicographical comparison works
    # (e.g. "9:30:00" -> "09:30:00")
    parts = cutoff.split(":")
    if len(parts) == 2:
        cutoff = f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    elif len(parts) >= 3:
        cutoff = f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"

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
        out.append(
            {
                "date": event.get("date"),
                "event": event.get("event") or event.get("name"),
                "impact": event.get("impact", event.get("importance", event.get("priority"))),
                "actual": event.get("actual"),
                "consensus": event.get("consensus", event.get("forecast", event.get("estimate"))),
                "previous": event.get("previous"),
                "country": event.get("country"),
                "currency": event.get("currency"),
            }
        )
    return out


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
        todays_events = _filter_events_by_cutoff_utc(todays_events, args.pre_open_cutoff_utc)

    todays_us_events = filter_us_events(todays_events)
    todays_us_high_impact_events = filter_us_high_impact_events(todays_events)
    todays_us_mid_impact_events = filter_us_mid_impact_events(todays_events)

    bias = macro_bias_score(todays_events)
    try:
        quotes = client.get_batch_quotes(symbols)
    except RuntimeError as exc:
        raise SystemExit(f"[open_prep] Quote fetch failed: {exc}") from exc
    ranked = rank_candidates(quotes=quotes, bias=bias, top_n=max(args.top, 1))
    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=max(args.trade_cards, 1))

    result = {
        "run_date_utc": today.isoformat(),
        "pre_open_only": bool(args.pre_open_only),
        "pre_open_cutoff_utc": args.pre_open_cutoff_utc,
        "macro_bias": round(bias, 4),
        "macro_event_count_today": len(todays_events),
        "macro_us_event_count_today": len(todays_us_events),
        "macro_us_high_impact_event_count_today": len(todays_us_high_impact_events),
        "macro_us_mid_impact_event_count_today": len(todays_us_mid_impact_events),
        "macro_us_high_impact_events_today": _format_macro_events(
            todays_us_high_impact_events, args.max_macro_events
        ),
        "macro_us_mid_impact_events_today": _format_macro_events(
            todays_us_mid_impact_events, args.max_macro_events
        ),
        "ranked_candidates": ranked,
        "trade_cards": cards,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Write the pre-trade earnings calendar JSONL from FMP.

Drop-in producer for the artefact ``smc_integration.earnings_filter`` consumes,
emitting the same record shape as ``scripts.wsh_earnings_calendar`` so the
consumer, the drivers and the audit rows need no knowledge of the source.

WHY A SECOND SOURCE (2026-08-19). The IBKR/WSH producer had delivered ZERO
events on every one of the 41 days since 2026-06-11. Measured causes, in the
order that matters:

* ``reports/databento_watchlist_top5_pre1530.csv`` carries no ``con_id``
  column, so ``_read_watchlist_symbols`` assigns the ``-1`` sentinel and
  ``reqWshEventData`` skips **every** symbol. This alone is sufficient: a WSH
  entitlement would not have produced a single event.
* The account may additionally lack the WSH entitlement (IBKR error 10276).

FMP needs neither conIds nor an entitlement, is already a paid production
dependency (news + fundamentals), and its earnings route already feeds the
outlook scorer and the movers-earnings classifier
(``terminal_poller.fetch_fmp_earnings``, re-sourced from Benzinga 2026-07-09).
Measured 2026-08-19 against the live key: 3761 rows / 3718 tickers over 7 days,
and 5 of the 41 watchlist symbols carry an earnings date within 30 days.

Exit-code contract — deliberately identical to ``scripts.wsh_earnings_calendar``
so ``automation/launchd/run-c13-wsh.sh`` can treat both the same way:

    0 — completed with >=1 earnings event resolved
    2 — completed but the calendar yielded ZERO events for the watchlist
    1 — hard failure (no usable output written)

Note that rc=2 still writes the (empty) file: the degradation must stay
auditable. Since 2026-08-19 an empty file is no longer mistaken for "no
earnings today" — ``EarningsFilter`` treats it as missing data and, under the
default fail-closed policy, blocks.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text
from scripts.wsh_earnings_calendar import WSH_EVENTS_SCHEMA_VERSION

LOGGER = logging.getLogger("fmp_earnings_calendar")

# FMP reports a single earnings event kind. It is mapped onto the WSH
# vocabulary rather than extending it, so ``EarningsFilter`` needs no change:
# its EARNINGS_EVENT_TYPES is pinned against the WSH set and a new literal
# here would silently fall through the ``ev_type not in ...`` continue.
FMP_EVENT_TYPE = "Earnings"

# No conId concept in FMP. The WSH sentinel is reused so both sources produce
# structurally identical records.
FMP_CON_ID = -1
FMP_SOURCE = "fmp"

DEFAULT_WINDOW_DAYS = 14


@dataclass(frozen=True)
class FmpEarningsEvent:
    """One forward-looking earnings date, shaped like ``WshEvent``."""

    symbol: str
    con_id: int
    event_type: str
    event_date: str
    event_time: str | None
    timezone: str | None
    confidence: str | None
    source: str
    schema_version: str = WSH_EVENTS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_watchlist_symbols(csv_path: Path) -> list[str]:
    """Unique upper-cased symbols from the watchlist CSV.

    Unlike the WSH reader this needs no ``con_id`` column — which is precisely
    why this producer works where that one cannot.
    """
    seen: list[str] = []
    known: set[str] = set()
    with csv_path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = str(row.get("symbol", "")).strip().upper()
            if symbol and symbol not in known:
                known.add(symbol)
                seen.append(symbol)
    return seen


def fetch_events(
    symbols: list[str],
    *,
    api_key: str,
    start: _dt.date,
    window_days: int,
) -> list[FmpEarningsEvent]:
    """Fetch the calendar once and keep only the watchlist symbols.

    One ranged call for the whole window, not one call per symbol: the FMP
    calendar route is date-ranged, and per-symbol fanout would multiply the
    request count by the watchlist size for identical data.
    """
    from terminal_poller import fetch_fmp_earnings

    end = start + _dt.timedelta(days=window_days)
    rows = fetch_fmp_earnings(api_key, start.isoformat(), end.isoformat())
    wanted = set(symbols)
    events: list[FmpEarningsEvent] = []
    for row in rows or []:
        symbol = str(row.get("ticker", "")).strip().upper()
        if not symbol or symbol not in wanted:
            continue
        event_date = str(row.get("date", "")).strip()
        try:
            _dt.date.fromisoformat(event_date)
        except ValueError:
            LOGGER.warning("skipping %s: unparseable date %r", symbol, event_date)
            continue
        timing = row.get("earnings_timing")
        events.append(
            FmpEarningsEvent(
                symbol=symbol,
                con_id=FMP_CON_ID,
                event_type=FMP_EVENT_TYPE,
                event_date=event_date,
                event_time=str(timing).strip() if timing else None,
                timezone=None,
                confidence=None,
                source=FMP_SOURCE,
            )
        )
    events.sort(key=lambda e: (e.event_date, e.symbol))
    return events


def write_jsonl(events: list[FmpEarningsEvent], output: Path) -> None:
    """Atomically replace ``output`` with the calendar.

    Atomic because a reader runs concurrently: the launchd driver writes this
    file while the incubation run may already be indexing it. A torn write
    would surface as a short calendar — i.e. as "no earnings for this symbol",
    the exact failure mode this change exists to remove.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(event.to_dict(), sort_keys=True) + "\n" for event in events
    )
    # Argument order is (text, target) — reversed here at first and the whole
    # calendar became the filename ("File name too long").
    atomic_write_text(payload, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--start-date",
        default=None,
        help="ISO window start; defaults to today (UTC).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.window_days < 1:
        LOGGER.error("--window-days must be >= 1, got %s", args.window_days)
        return 1

    api_key = os.environ.get("FMP_API_KEY", "").strip()
    if not api_key:
        # Railway hands a missing secret over as "", so an empty value is the
        # same fault as an unset one and must not read as "no earnings".
        LOGGER.error("FMP_API_KEY is unset or empty; no calendar written")
        return 1

    if not args.watchlist.is_file():
        LOGGER.error("watchlist not found: %s", args.watchlist)
        return 1

    symbols = read_watchlist_symbols(args.watchlist)
    if not symbols:
        LOGGER.error("watchlist %s carries no symbols", args.watchlist)
        return 1

    start = (
        _dt.date.fromisoformat(args.start_date)
        if args.start_date
        else _dt.datetime.now(_dt.UTC).date()
    )

    try:
        events = fetch_events(
            symbols, api_key=api_key, start=start, window_days=args.window_days
        )
    except Exception as exc:  # hard failure must be rc=1, never a silent []
        LOGGER.error("FMP earnings fetch failed: %s", exc)
        return 1

    write_jsonl(events, args.output)
    LOGGER.info(
        "wrote %d earnings event(s) for %d watchlist symbol(s) to %s",
        len(events),
        len(symbols),
        args.output,
    )
    return 0 if events else 2


if __name__ == "__main__":
    raise SystemExit(main())

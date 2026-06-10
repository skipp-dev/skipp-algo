"""C13/T7.1 — Wall Street Horizon earnings-calendar wrapper.

Pulls forward-looking earnings/dividend/expiration events for a given
list of symbols from the IBKR Wall Street Horizon ($49/Mo retail) feed
via ``IBApi.EClient.reqWshMetaData`` + ``reqWshEventData``.

Reference docs:
- https://interactivebrokers.github.io/tws-api/fundamentals.html
- https://interactivebrokers.github.io/tws-api/wshe_filters.html

The module is intentionally I/O-narrow:

* **Inputs.** A list of (symbol, conId) pairs and a forward-window in
  days. Network access goes through ``ib_async`` to a running TWS /
  IB Gateway session.
* **Outputs.** A JSONL artefact ``cache/live/wsh_events_<DATE>.jsonl``
  with one line per (symbol, event) pair. Schema version 1.0.0.

The C13 Phase-A pre-trade filter consumes the JSONL via
:mod:`smc_integration.earnings_filter`.

CLI
---
::

    python -m scripts.wsh_earnings_calendar \
        --watchlist reports/databento_watchlist_top5_pre1530.csv \
        --window-days 14 \
        --output cache/live/wsh_events_2026-04-27.jsonl
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Producer-side schema; bump when fields are removed (additive ok).
WSH_EVENTS_SCHEMA_VERSION = "1.0.0"

# Window default — 14 calendar days forward, matches pre-trade filter
# horizon in the C13 sprint plan.
DEFAULT_WINDOW_DAYS = 14

# Earnings event-type codes per WSH filter doc. These are the only
# event types the Phase-A filter reasons about; anything else is
# logged but ignored (additive contract).
WSH_EARNINGS_EVENT_TYPES: frozenset[str] = frozenset({
    "Earnings",
    "EarningsAnnouncement",
    "EarningsDated",
    "EarningsRevised",
})


@dataclass(frozen=True)
class WshEvent:
    """Single forward-looking event for one symbol."""

    symbol: str
    con_id: int
    event_type: str
    event_date: str  # ISO-8601 YYYY-MM-DD
    event_time: str | None  # ISO-8601 HH:MM if known, else None
    timezone: str | None
    confidence: str | None  # WSH confidence flag (e.g. "Confirmed", "Inferred")
    source: str
    schema_version: str = WSH_EVENTS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WshFetchSummary:
    """Bookkeeping for a single calendar fetch."""

    symbols_requested: int
    symbols_with_events: int
    events_total: int
    earnings_events: int
    fetch_started_at: str
    fetch_completed_at: str
    window_days: int
    output_path: str
    errors: list[str] = field(default_factory=list)
    # Feed-health verdict for downstream/cron consumers. ``ok`` means the
    # pull resolved at least one event; ``degraded:no-events`` means the feed
    # returned ZERO events while reporting errors (e.g. IBKR entitlement
    # missing / watchlist rows lack conIds) — i.e. the earnings filter would
    # silently gate against an empty set. (F3, 2026-06-10)
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _import_ib_async() -> Any:
    """Import ib_async.IB lazily so CI without IBKR deps still works."""
    try:
        from ib_async import IB
    except ImportError as exc:  # pragma: no cover — exercised in live runtime
        raise RuntimeError(
            "ib_async is not installed. Install with "
            "`pip install -r requirements.txt`."
        ) from exc
    return IB


def _atomic_write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """Atomically write JSONL records to ``path``.

    Mirrors the flush+fsync+replace pattern from
    :func:`scripts.backfill_live_outcomes._atomic_write_jsonl`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, sort_keys=True))
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern above.
            json.dump(payload, fh, sort_keys=True, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def parse_wsh_event_data(
    *,
    symbol: str,
    con_id: int,
    raw_payload: str,
    source: str = "wsh",
) -> list[WshEvent]:
    """Parse one ``wshEventData`` JSON payload into ``WshEvent`` rows.

    The TWS ``wshEventData`` callback delivers a JSON-encoded string
    per request. We are conservative about its schema: we only require
    a top-level ``events`` list of dicts; missing keys yield ``None``.
    Anything that cannot be parsed is logged and skipped — the
    upstream cron must not crash on a single broken symbol.
    """
    if not raw_payload:
        return []
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        LOGGER.warning("wsh payload for %s is not JSON: %s", symbol, exc)
        return []
    if not isinstance(payload, dict):
        return []
    raw_events = payload.get("events") or []
    if not isinstance(raw_events, list):
        return []
    out: list[WshEvent] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        event_type = str(raw_event.get("type", "")).strip()
        if not event_type:
            continue
        event_date = str(raw_event.get("date", "")).strip()
        if not event_date:
            continue
        out.append(
            WshEvent(
                symbol=symbol,
                con_id=int(con_id),
                event_type=event_type,
                event_date=event_date,
                event_time=raw_event.get("time"),
                timezone=raw_event.get("tz"),
                confidence=raw_event.get("confidence"),
                source=source,
            )
        )
    return out


def fetch_wsh_calendar(
    symbols: list[tuple[str, int]],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    ib_client: Any | None = None,
    timeout_seconds: int = 30,
) -> tuple[list[WshEvent], list[str]]:
    """Fetch forward-looking events for ``symbols`` over ``window_days``.

    Returns ``(events, errors)``. Each error string is per-symbol so
    the caller can persist a partial JSONL even when half the symbols
    fail (Phase-A blocks no trade on missing WSH data).

    Pure-stdlib path: when ``ib_client`` is None we attempt to import
    ``ib_async.IB`` lazily; tests stub the client through the
    ``ib_client`` parameter.
    """
    events: list[WshEvent] = []
    errors: list[str] = []

    if not symbols:
        return events, errors

    if ib_client is None:
        IB = _import_ib_async()
        ib_client = IB()
    # The TWS WSH-MetaData call is a one-shot handshake per session;
    # callers are responsible for connect/disconnect lifecycle. We do
    # not connect here so unit tests can pass a fully-stubbed client.

    try:
        # ib_async sync helper: returns the metadata payload string
        # once the wshMetaData event fires (or raises on timeout).
        # The low-level ``reqWshMetaData(reqId=...)`` is the EClient
        # signature; ib_async's IB wrapper exposes the no-arg form
        # plus this sync convenience helper.
        ib_client.getWshMetaData()
    except Exception as exc:  # pragma: no cover — exercised live
        errors.append(f"reqWshMetaData failed: {exc}")
        return events, errors

    # WshEventData is the ib_async filter object; we import it lazily
    # to keep test stubs free of the ib_async dependency.
    try:
        from ib_async.objects import WshEventData
    except Exception as exc:  # pragma: no cover — only on missing dep
        errors.append(f"ib_async.WshEventData import failed: {exc}")
        return events, errors

    today_iso = _dt.datetime.now(_ET).date().isoformat()
    end_date_iso = (
        _dt.datetime.now(_ET).date() + _dt.timedelta(days=int(window_days))
    ).isoformat()

    for _idx, (symbol, con_id) in enumerate(symbols, start=1):
        if int(con_id) <= 0:
            # Honour the ``con_id == -1`` sentinel documented in
            # ``_read_watchlist_symbols``: WSH ``reqWshEventData`` is
            # keyed on a real IBKR conId, so calling it with -1 (or
            # any non-positive value) is a guaranteed error. Surface
            # it as a soft skip so the cron operator sees the gap
            # without aborting the whole run.
            errors.append(
                f"{symbol}: skipped reqWshEventData (con_id={con_id} <= 0; "
                "watchlist row missing IBKR conId)"
            )
            continue
        try:
            # Filter: earnings-family events only, forward window.
            wsh_filter = json.dumps({
                "country": "US",
                "watchlist": [str(con_id)],
                "filter_categories": ["earnings"],
                "future_days": int(window_days),
            })
            payload_str = ib_client.getWshEventData(
                WshEventData(
                    conId=int(con_id),
                    filter=wsh_filter,
                    startDate=today_iso,
                    endDate=end_date_iso,
                )
            )
        except Exception as exc:  # pragma: no cover — exercised live
            errors.append(f"{symbol}: reqWshEventData failed: {exc}")
            continue
        events.extend(
            parse_wsh_event_data(
                symbol=symbol,
                con_id=int(con_id),
                raw_payload=str(payload_str or ""),
            )
        )

    return events, errors


def filter_earnings_events(events: Iterable[WshEvent]) -> list[WshEvent]:
    """Return only earnings-family events (whitelist filter)."""
    return [e for e in events if e.event_type in WSH_EARNINGS_EVENT_TYPES]


def _read_watchlist_symbols(csv_path: Path) -> list[tuple[str, int]]:
    """Extract unique (symbol, con_id) pairs from a watchlist CSV.

    The current production watchlist
    (``reports/databento_watchlist_top5_pre1530.csv``) does not yet
    carry IBKR conIds — the live runner resolves them at intent-build
    time. For the WSH wrapper we accept either:

    * a CSV with a ``con_id`` column → use directly
    * a CSV with only ``symbol`` → ``con_id`` defaults to ``-1`` (a
      sentinel that downstream ``reqWshEventData`` calls skip)

    The cron operator is expected to materialise the conId mapping in
    a separate step before calling the wrapper for production runs.
    """
    seen: dict[str, int] = {}
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            con_id_raw = row.get("con_id") or row.get("conId") or "-1"
            try:
                con_id = int(con_id_raw)
            except (TypeError, ValueError):
                con_id = -1
            seen[symbol] = con_id
    return [(sym, cid) for sym, cid in seen.items()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "C13/T7.1 — fetch the WSH forward earnings calendar for the "
            "current SMC watchlist and persist a JSONL artefact."
        ),
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        required=True,
        help="Watchlist CSV (must carry symbol + optional con_id columns).",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"Forward-looking window in days (default: {DEFAULT_WINDOW_DAYS}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSONL path for the events feed.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional summary JSON (counts, errors, timestamps).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the IBKR call; write an empty events JSONL + summary.",
    )
    parser.add_argument(
        "--ib-host",
        default="127.0.0.1",
        help="TWS / IB Gateway host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--ib-port",
        type=int,
        default=7497,
        help="TWS / IB Gateway port (default: 7497, paper).",
    )
    parser.add_argument(
        "--ib-client-id",
        type=int,
        default=None,
        help=(
            "IB client id used for the WSH session. "
            "Default: rotating allocation via scripts.ib_client_id "
            "(cooperative registry, range 40-99) so multiple C13 jobs "
            "can share a TWS session without colliding."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # F-V4-A1b: configure root logging so logger.info / logging.* calls actually
    # surface on stdout when this script is invoked from a GitHub Actions workflow.
    # Without this, the pipeline runs silently and runner-side eviction or
    # mid-pipeline errors are impossible to triage. Also flush eagerly so partial
    # logs survive runner shutdown signals. Self-contained imports to avoid
    # disturbing module-level import order.
    import logging as _v4a1b_logging, sys as _v4a1b_sys, time as _v4a1b_time
    _v4a1b_logging.basicConfig(
        level=_v4a1b_logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=_v4a1b_sys.stderr,
        force=True,
    )
    _v4a1b_logging.Formatter.converter = _v4a1b_time.gmtime
    try:
        _v4a1b_sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        _v4a1b_sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


    args = _parse_args(argv)
    started = _dt.datetime.now(tz=_dt.UTC).isoformat()
    symbols = _read_watchlist_symbols(args.watchlist)
    if not symbols:
        LOGGER.error("watchlist %s is empty; aborting", args.watchlist)
        return 1

    if args.dry_run:
        events: list[WshEvent] = []
        errors: list[str] = ["dry-run"]
    else:
        # Live cron path: ``fetch_wsh_calendar`` explicitly does not
        # connect/disconnect (so unit tests can stub the client), so
        # the CLI owns the TWS lifecycle here. Without this block the
        # ``reqWshMetaData`` / ``reqWshEventData`` calls would fail on
        # an unconnected client.
        from ib_async import IB  # local import: optional dependency

        from scripts.ib_client_id import (
            allocate_ib_client_id,
            release_ib_client_id,
        )

        if args.ib_client_id is None:
            client_id = allocate_ib_client_id("c13_wsh")
            allocated = True
        else:
            client_id = args.ib_client_id
            allocated = False

        ib_client = IB()
        ib_client.connect(
            host=args.ib_host,
            port=args.ib_port,
            clientId=client_id,
        )
        try:
            events, errors = fetch_wsh_calendar(
                symbols,
                window_days=args.window_days,
                ib_client=ib_client,
            )
        finally:
            try:
                ib_client.disconnect()
            except Exception:  # pragma: no cover — exercised live
                LOGGER.warning("ib_client.disconnect() failed", exc_info=True)
            if allocated:
                try:
                    release_ib_client_id(client_id)
                except Exception:  # pragma: no cover
                    LOGGER.warning(
                        "release_ib_client_id(%s) failed", client_id, exc_info=True
                    )

    earnings = filter_earnings_events(events)
    _atomic_write_jsonl(
        args.output,
        (e.to_dict() for e in earnings),
    )

    completed = _dt.datetime.now(tz=_dt.UTC).isoformat()

    # F3 fail-loud: a live pull that returns ZERO events while reporting
    # provider errors is a DEGRADED feed, not a quiet success. Surfacing it
    # (status field + WARNING + exit code 2) prevents the earnings filter
    # from silently becoming a no-op. ``dry-run`` is an expected sentinel,
    # not a provider error, so it is excluded from the verdict.
    real_errors = [e for e in errors if e != "dry-run"]
    degraded = (not args.dry_run) and len(events) == 0 and bool(real_errors)
    status_val = "degraded:no-events" if degraded else "ok"

    summary = WshFetchSummary(
        symbols_requested=len(symbols),
        symbols_with_events=len({e.symbol for e in earnings}),
        events_total=len(events),
        earnings_events=len(earnings),
        fetch_started_at=started,
        fetch_completed_at=completed,
        window_days=int(args.window_days),
        output_path=str(args.output),
        errors=errors,
        status=status_val,
    )
    if args.summary_output:
        _atomic_write_json(args.summary_output, summary.to_dict())

    print(json.dumps(summary.to_dict(), sort_keys=True))

    if degraded:
        LOGGER.warning(
            "WSH feed DEGRADED: 0 events resolved for %d watchlist symbol(s) "
            "with %d provider error(s) — the earnings filter will gate against "
            "an EMPTY set (earnings protection effectively OFF). "
            "Likely causes: IBKR account lacks the WSH entitlement (Error "
            "10276), or watchlist rows are missing IBKR conIds. Errors: %s",
            len(symbols),
            len(real_errors),
            real_errors[:5],
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())

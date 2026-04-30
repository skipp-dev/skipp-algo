"""C13/T8.2 — Daily cron step that persists opening imbalances.

Iterates the daily watchlist, calls
:func:`scripts.imbalance_data.fetch_opening_imbalance` once per
symbol, and writes the snapshots to
``cache/live/imbalance_<DATE>.jsonl`` atomically.

The script is **passive** in C13 Phase A — it never blocks any trade
on missing data. Coverage and error counts are emitted as a summary
JSON for the cron-failure-alerting path.

CLI
---
::

    python -m scripts.collect_opening_imbalances \
        --watchlist reports/databento_watchlist_top5_pre1530.csv \
        --output cache/live/imbalance_2026-04-27.jsonl
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

from scripts.imbalance_data import (
    IMBALANCE_SCHEMA_VERSION,
    ImbalanceSnapshot,
    build_unavailable_snapshot,
    fetch_opening_imbalance,
    listing_to_imbalance_feed,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionSummary:
    """Bookkeeping for one collection run (one trade-day)."""

    trade_date: str
    symbols_total: int
    symbols_with_snapshot: int
    symbols_with_imbalance: int
    nyse_listings: int
    amex_listings: int
    nasdaq_listings: int
    other_listings: int
    coverage_pct: float
    started_at: str
    completed_at: str
    output_path: str
    schema_version: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _atomic_write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
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


def _read_watchlist_with_listing(
    csv_path: Path,
) -> list[tuple[str, str]]:
    """Extract (symbol, listing_exchange) tuples from a watchlist CSV.

    Listing exchange is taken from the ``exchange`` column (e.g.
    ``NYSE``, ``NASDAQ``, ``AMEX``); rows without it default to
    ``"UNKNOWN"``.
    """
    seen: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            listing = str(row.get("exchange", "")).strip().upper() or "UNKNOWN"
            seen[symbol] = listing
    return list(seen.items())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "C13/T8.2 — collect opening-auction imbalance snapshots for "
            "every symbol in the watchlist."
        ),
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        required=True,
        help="Watchlist CSV (must carry symbol + exchange columns).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSONL for imbalance snapshots.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional summary JSON (counts, errors).",
    )
    parser.add_argument(
        "--trade-date",
        default=None,
        help="ISO trade date (default: today UTC).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Seconds to sleep per symbol while ticks accumulate (default 5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the IBKR call; emit only UNAVAILABLE snapshots.",
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
            "IB client id used for the imbalance session. "
            "Default: rotating allocation via scripts.ib_client_id "
            "(cooperative registry, range 40-99) so multiple C13 jobs "
            "can share a TWS session without colliding."
        ),
    )
    return parser.parse_args(argv)


def _make_dry_run_snapshots(
    rows: list[tuple[str, str]],
    *,
    now_utc: _dt.datetime,
) -> list[ImbalanceSnapshot]:
    return [
        build_unavailable_snapshot(
            symbol=sym,
            listing_exchange=listing,
            error="DRY_RUN",
            now_utc=now_utc,
        )
        for sym, listing in rows
    ]


def collect_imbalances(
    rows: list[tuple[str, str]],
    *,
    fetch_fn: Any = fetch_opening_imbalance,
    poll_seconds: float = 5.0,
    now_utc: _dt.datetime | None = None,
) -> tuple[list[ImbalanceSnapshot], list[str]]:
    """Run ``fetch_fn`` over each (symbol, listing_exchange) row.

    Returns ``(snapshots, errors)``. The function never raises on a
    single broken symbol — it logs and continues. NASDAQ rows produce
    UNAVAILABLE snapshots without calling the fetch function (no
    subscription).
    """
    snapshots: list[ImbalanceSnapshot] = []
    errors: list[str] = []
    for symbol, listing in rows:
        feed = listing_to_imbalance_feed(listing)
        if feed == "UNAVAILABLE":
            snapshots.append(
                build_unavailable_snapshot(
                    symbol=symbol,
                    listing_exchange=listing,
                    error="NO_SUBSCRIPTION",
                    now_utc=now_utc,
                )
            )
            continue
        try:
            snapshot = fetch_fn(
                symbol=symbol,
                listing_exchange=listing,
                poll_seconds=poll_seconds,
                now_utc=now_utc,
            )
        except Exception as exc:  # pragma: no cover — exercised live
            errors.append(f"{symbol}: {exc}")
            snapshots.append(
                build_unavailable_snapshot(
                    symbol=symbol,
                    listing_exchange=listing,
                    error=f"FETCH_RAISED: {exc}",
                    now_utc=now_utc,
                )
            )
            continue
        snapshots.append(snapshot)
    return snapshots, errors


def _summarise(
    *,
    trade_date: str,
    rows: list[tuple[str, str]],
    snapshots: list[ImbalanceSnapshot],
    errors: list[str],
    started_at: str,
    completed_at: str,
    output_path: Path,
) -> CollectionSummary:
    # Apply the same normalisation as ``listing_to_imbalance_feed()``
    # in ``scripts.imbalance_data`` so values like ``"NYSE MKT"`` (with
    # space) bucket alongside ``"NYSE_MKT"``/``"NYSE_AMERICAN"`` rather
    # than slipping into ``other_listings`` and skewing ``coverage_pct``.
    def _norm(listing: str) -> str:
        return str(listing or "").strip().upper().replace(" ", "_")

    norm_listings = [_norm(ln) for _, ln in rows]
    nyse = sum(1 for n in norm_listings if n == "NYSE")
    amex = sum(1 for n in norm_listings if n in {"AMEX", "NYSE_MKT", "NYSE_AMERICAN"})
    nasdaq = sum(1 for n in norm_listings if n == "NASDAQ")
    other = max(0, len(rows) - nyse - amex - nasdaq)
    with_snap = sum(1 for s in snapshots if s.available)
    with_imbalance = sum(
        1 for s in snapshots if s.auction_imbalance_shares is not None
    )
    eligible = nyse + amex
    # ``coverage_pct`` measures "how many of the eligible (NYSE+AMEX)
    # rows produced an imbalance value". Counting ``with_imbalance``
    # across ALL listings would let a non-eligible listing (e.g. ARCA
    # routed via Smart) push the ratio above 1.0, which is meaningless.
    # We therefore restrict ``with_imbalance_eligible`` to snapshots
    # whose listing falls into the same NYSE/AMEX bucket used for the
    # denominator.
    eligible_listings = {"NYSE", "AMEX", "NYSE_MKT", "NYSE_AMERICAN"}
    with_imbalance_eligible = sum(
        1
        for s in snapshots
        if s.auction_imbalance_shares is not None
        and _norm(s.listing_exchange) in eligible_listings
    )
    coverage = (with_imbalance_eligible / eligible) if eligible else 0.0
    return CollectionSummary(
        trade_date=trade_date,
        symbols_total=len(rows),
        symbols_with_snapshot=with_snap,
        symbols_with_imbalance=with_imbalance,
        nyse_listings=nyse,
        amex_listings=amex,
        nasdaq_listings=nasdaq,
        other_listings=other,
        coverage_pct=round(coverage, 6),
        started_at=started_at,
        completed_at=completed_at,
        output_path=str(output_path),
        schema_version=IMBALANCE_SCHEMA_VERSION,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    now_utc = _dt.datetime.now(tz=_dt.UTC)
    started_at = now_utc.isoformat()
    trade_date = args.trade_date or now_utc.date().isoformat()

    rows = _read_watchlist_with_listing(args.watchlist)
    if not rows:
        LOGGER.error("watchlist %s is empty; aborting", args.watchlist)
        return 1

    if args.dry_run:
        snapshots = _make_dry_run_snapshots(rows, now_utc=now_utc)
        errors: list[str] = ["dry-run"]
    else:
        # Live cron path: ``fetch_opening_imbalance`` explicitly does
        # not connect/disconnect (so unit tests can stub the client),
        # so the CLI owns the TWS lifecycle here. Without this block
        # the per-symbol ``reqMktData`` calls would fail on an
        # unconnected client.
        from ib_async import IB  # local import: optional dependency

        from scripts.ib_client_id import (
            allocate_ib_client_id,
            release_ib_client_id,
        )

        if args.ib_client_id is None:
            client_id = allocate_ib_client_id("c13_imbalance")
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
            snapshots, errors = collect_imbalances(
                rows,
                fetch_fn=lambda **kw: fetch_opening_imbalance(
                    ib_client=ib_client, **kw
                ),
                poll_seconds=args.poll_seconds,
                now_utc=now_utc,
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

    _atomic_write_jsonl(
        args.output, (s.to_dict() for s in snapshots)
    )

    completed = _dt.datetime.now(tz=_dt.UTC).isoformat()
    summary = _summarise(
        trade_date=trade_date,
        rows=rows,
        snapshots=snapshots,
        errors=errors,
        started_at=started_at,
        completed_at=completed,
        output_path=args.output,
    )
    if args.summary_output:
        _atomic_write_json(args.summary_output, summary.to_dict())

    print(json.dumps(summary.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())

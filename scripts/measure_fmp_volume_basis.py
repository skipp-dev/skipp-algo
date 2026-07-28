#!/usr/bin/env python3
"""Collect one post-close FMP volume-basis measurement and update its summary."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from open_prep.macro import FMPClient
from open_prep.volume_source_audit import (
    build_multi_session_summary,
    build_volume_measurement,
)
from scripts.smc_atomic_write import atomic_write_json


def _symbols_from_payload(payload: Any, *, maximum: int) -> list[str]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [
            *list(payload.get("ranked_v2") or []),
            *list(payload.get("enriched_quotes") or []),
        ]
    else:
        rows = []
    seen: set[str] = set()
    symbols: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
        if len(symbols) >= maximum:
            break
    return symbols


def _load_history(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("measurement_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            values = payload.get("measurements")
            if isinstance(values, list):
                rows.extend(row for row in values if isinstance(row, dict))
    return rows


def collect_session(
    *,
    client: FMPClient,
    symbols: list[str],
    session_date: str,
    workers: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    quotes = client.get_batch_quotes(symbols)
    quotes_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in quotes
        if isinstance(row, dict)
    }
    day = date.fromisoformat(session_date)
    errors: dict[str, str] = {}

    def _one(symbol: str) -> dict[str, Any]:
        quote = quotes_by_symbol.get(symbol)
        if quote is None:
            raise ValueError("quote_missing")
        minute_rows = client.get_intraday_chart(symbol, interval="1min", day=day, limit=5000)
        eod_rows = client.get_historical_price_eod_full(symbol, day, day)
        return build_volume_measurement(
            symbol=symbol,
            session_date=session_date,
            quote_row=quote,
            minute_rows=minute_rows,
            eod_response=eod_rows,
        )

    measurements: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(symbols) or 1))) as pool:
        futures = {pool.submit(_one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                measurements.append(future.result())
            except Exception as exc:
                errors[symbol] = type(exc).__name__ + ":" + str(exc)[:160]
    return sorted(measurements, key=lambda row: str(row.get("symbol"))), dict(sorted(errors.items()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--symbols-from", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-symbols", type=int, default=20)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--minimum-sessions", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date.fromisoformat(args.session_date)
    payload = json.loads(args.symbols_from.read_text(encoding="utf-8"))
    symbols = _symbols_from_payload(payload, maximum=max(1, args.max_symbols))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    measurements: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    if symbols:
        try:
            measurements, errors = collect_session(
                client=FMPClient.from_env(),
                symbols=symbols,
                session_date=args.session_date,
                workers=args.workers,
            )
        except Exception as exc:
            errors["__run__"] = type(exc).__name__ + ":" + str(exc)[:160]
    measurement_path = args.output_dir / f"measurement_{args.session_date}.json"
    atomic_write_json({
        "schema_version": 1,
        "session_date": args.session_date,
        "symbols_requested": symbols,
        "measurements": measurements,
        "errors": errors,
    }, measurement_path, indent=2, sort_keys=True, fsync=True)
    summary = build_multi_session_summary(
        _load_history(args.output_dir),
        minimum_sessions=max(1, args.minimum_sessions),
    )
    atomic_write_json(summary, args.output_dir / "latest_summary.json", indent=2, sort_keys=True, fsync=True)
    print(json.dumps({
        "measurement": str(measurement_path),
        "symbols_measured": len(measurements),
        "errors": len(errors),
        "verdict": summary["verdict"],
        "sessions_observed": summary["sessions_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

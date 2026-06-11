from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.execute_ibkr_watchlist import (
    DEFAULT_RECONNECT_MAX_ATTEMPTS,
    DEFAULT_RECONNECT_WAIT_SECONDS,
    IBKRConnectionConfig,
    IBKRExecutionConfig,
    _import_ibkr_types,
    _normalize_schedule_value,
    _parse_symbol_filter,
    assert_paper_account_if_paper_port,
    build_order_intents,
    build_preview_payload,
    filter_watchlist,
    load_watchlist_frame,
    resolve_client_id,
    resolve_trade_date,
    supervise_open_execution,
)
from scripts.execute_ibkr_watchlist import (
    build_parser as build_execute_parser,
)
from scripts.generate_databento_watchlist import LongDipConfig
from scripts.smc_atomic_write import atomic_write_text

DEFAULT_SUPERVISOR_JSON = Path(__file__).resolve().parents[1] / "reports" / "ibkr_open_execution_supervisor.json"
DEFAULT_SUPERVISOR_EVENTS_CSV = Path(__file__).resolve().parents[1] / "reports" / "ibkr_open_execution_events.csv"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SMOKE_HALT_PATH = _REPO_ROOT / "cache" / "live" / "smoke_HALT"
# Maximum age of today's smoke JSONL to be considered valid (hours).
# The smoke fires at 08:00 ET; execution fires at ~09:28 ET (~88 min later).
# 4 hours gives ample margin while guarding against a stale file from yesterday.
_SMOKE_JSONL_MAX_AGE_HOURS = 4


def _repo_date_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _check_smoke_guard(skip: bool) -> None:
    """Abort with SystemExit if the pre-market smoke guard is tripped.

    Two blocking conditions (either is sufficient):

    1. ``cache/live/smoke_HALT`` exists — the smoke driver wrote this
       because the live round-trip left leftover orders (EXIT=3), breached
       risk limits (EXIT=2), or encountered an unexpected error.  The
       operator must remove the file manually once the root cause is resolved.

    2. No ``cache/live/smoke_<DATE>.jsonl`` for today's UTC date exists,
       OR the file is older than ``_SMOKE_JSONL_MAX_AGE_HOURS`` — meaning
       the smoke has not run or the result is stale.

    Pass ``--skip-smoke-guard`` on the CLI to bypass both checks (emergency
    use only; requires explicit acknowledgement in the audit trail).
    """
    if skip:
        print(
            "run_ibkr_open_execution: smoke guard BYPASSED via --skip-smoke-guard",
            flush=True,
        )
        return

    # 1. Hard-block: HALT sentinel.
    if _SMOKE_HALT_PATH.exists():
        content = _SMOKE_HALT_PATH.read_text(encoding="utf-8").strip()
        raise SystemExit(
            f"run_ibkr_open_execution: BLOCKED — smoke_HALT sentinel present\n"
            f"  path : {_SMOKE_HALT_PATH}\n"
            f"  content: {content}\n"
            "  Remove the file manually after investigating the root cause."
        )

    # 2. Smoke-not-run guard: today's audit JSONL must exist and be fresh.
    today = _repo_date_utc()
    smoke_jsonl = _REPO_ROOT / "cache" / "live" / f"smoke_{today}.jsonl"
    if not smoke_jsonl.exists():
        raise SystemExit(
            f"run_ibkr_open_execution: BLOCKED — pre-market smoke has not run today ({today}).\n"
            f"  Expected: {smoke_jsonl}\n"
            "  Ensure com.skippalgo.c13.ibkr-smoke fired and TWS was available on 127.0.0.1:7497.\n"
            "  Use --skip-smoke-guard to override (emergency only)."
        )
    # MTIME-RESOLVER-EXEMPT: st_mtime is an age/freshness check on a single
    # date-keyed sentinel file (no candidate ordering / artifact picking).
    age_hours = (datetime.now(UTC) - datetime.fromtimestamp(smoke_jsonl.stat().st_mtime, tz=UTC)).total_seconds() / 3600
    if age_hours > _SMOKE_JSONL_MAX_AGE_HOURS:
        raise SystemExit(
            f"run_ibkr_open_execution: BLOCKED — smoke JSONL is {age_hours:.1f}h old (limit {_SMOKE_JSONL_MAX_AGE_HOURS}h).\n"
            f"  path: {smoke_jsonl}\n"
            "  Re-run the smoke manually or use --skip-smoke-guard to override."
        )


def build_execution_event_log(submission: dict[str, Any], supervisor: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for placement in submission.get("placements", []):
        for order in placement.get("orders", []):
            rows.append(
                {
                    "timestamp": order.get("placed_at"),
                    "category": "submission",
                    "event_type": "order_submitted",
                    "symbol": placement.get("symbol"),
                    "level_tag": placement.get("level_tag"),
                    "order_ref": order.get("order_ref"),
                    "order_id": order.get("order_id"),
                    "status": order.get("status"),
                    "details": {
                        "action": order.get("action"),
                        "order_type": order.get("order_type"),
                        "exit_mode": placement.get("exit_mode"),
                    },
                }
            )

    if supervisor is None:
        return rows

    previous_signature: tuple[int, int, tuple[tuple[str, float], ...]] | None = None
    for snapshot in supervisor.get("snapshots", []):
        signature = (
            len(snapshot.get("open_orders", [])),
            len(snapshot.get("fills", [])),
            tuple(
                (str(position.get("symbol", "")), float(position.get("position", 0) or 0))
                for position in snapshot.get("positions", [])
            ),
        )
        if signature == previous_signature:
            continue
        previous_signature = signature
        rows.append(
            {
                "timestamp": snapshot.get("captured_at"),
                "category": "snapshot",
                "event_type": "state_change",
                "symbol": None,
                "level_tag": None,
                "order_ref": None,
                "order_id": None,
                "status": None,
                "details": {
                    "open_order_count": len(snapshot.get("open_orders", [])),
                    "fill_count": len(snapshot.get("fills", [])),
                    "positions": snapshot.get("positions", []),
                },
            }
        )

    for event in supervisor.get("events", []):
        _ts_source = "captured_at" if event.get("captured_at") else "trigger_at"
        rows.append(
            {
                "timestamp": event.get("captured_at") or event.get("trigger_at"),
                "timestamp_source": _ts_source,
                "category": "supervisor",
                "event_type": event.get("action"),
                "symbol": event.get("symbol"),
                "level_tag": None,
                "order_ref": None,
                "order_id": None,
                "status": event.get("status"),
                "details": event,
            }
        )

    final_snapshot = supervisor.get("final", {})
    rows.append(
        {
            "timestamp": None,
            "category": "supervisor",
            "event_type": "final_state",
            "symbol": None,
            "level_tag": None,
            "order_ref": None,
            "order_id": None,
            "status": "timed_out" if supervisor.get("timed_out") else "completed",
            "details": {
                "timed_out": bool(supervisor.get("timed_out")),
                "open_order_count": len(final_snapshot.get("open_orders", [])),
                "fill_count": len(final_snapshot.get("fills", [])),
                "position_count": len(final_snapshot.get("positions", [])),
            },
        }
    )
    return rows


def write_execution_event_log_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "category", "event_type", "symbol", "level_tag", "order_ref", "order_id", "status", "details", "timestamp_source"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "details": json.dumps(row.get("details"), separators=(",", ":"), default=str),
                }
            )


def build_parser() -> argparse.ArgumentParser:
    parser = build_execute_parser()
    parser.description = "Submit IBKR watchlist orders and supervise the opening execution lifecycle."
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0, help="Polling cadence for order/position supervision.")
    parser.add_argument("--supervisor-timeout-seconds", type=float, default=900.0, help="Maximum supervisor runtime before exiting with the latest reconciliation snapshot.")
    parser.add_argument("--supervisor-json", default=str(DEFAULT_SUPERVISOR_JSON), help="Output path for the combined submission + supervisor result.")
    parser.add_argument("--supervisor-events-csv", default=str(DEFAULT_SUPERVISOR_EVENTS_CSV), help="Output path for the compact supervisor event log CSV.")
    parser.add_argument("--reconnect-max-attempts", type=int, default=DEFAULT_RECONNECT_MAX_ATTEMPTS, help="Maximum reconnect attempts after a TWS disconnect during supervision.")
    parser.add_argument("--reconnect-wait-seconds", type=float, default=DEFAULT_RECONNECT_WAIT_SECONDS, help="Wait time between reconnect attempts during supervision.")
    parser.add_argument(
        "--skip-smoke-guard",
        action="store_true",
        default=False,
        help="Bypass the pre-market smoke guard (emergency use only — prints an explicit warning).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.place_orders:
        raise SystemExit("run_ibkr_open_execution.py requires --place-orders to avoid accidental dry-run supervision.")

    # Pre-market smoke guard: block execution if the adapter round-trip failed
    # or did not run today (com.skippalgo.c13.ibkr-smoke @ 08:00 ET).
    # Deliberately AFTER the --place-orders check (Copilot review #2691): the
    # guard only matters when real order placement is enabled, and a user who
    # forgets --place-orders should get the clearer usage error, not a
    # smoke-guard BLOCKED exit. Still runs before any IBKR connection.
    _check_smoke_guard(getattr(args, "skip_smoke_guard", False))

    # S3 (Copilot review #2689): auto-allocated clientIds are leased from the
    # registry and must be released on exit; explicit --client-id values are
    # never registered, so never released.
    client_id = resolve_client_id(args.client_id)
    try:
        _main_with_resolved_client_id(args, client_id)
    finally:
        if args.client_id is None:
            from scripts.ib_client_id import release_ib_client_id

            release_ib_client_id(client_id)


def _main_with_resolved_client_id(args: argparse.Namespace, client_id: int) -> None:
    connection_cfg = IBKRConnectionConfig(
        host=args.host,
        port=args.port,
        client_id=client_id,
        account=args.account,
        timeout_seconds=args.timeout_seconds,
        readonly=False,
    )
    execution_cfg = IBKRExecutionConfig(
        tif=args.tif,
        outside_rth=args.outside_rth,
        exit_mode=args.exit_mode,
        cancel_unfilled_after=_normalize_schedule_value(args.cancel_unfilled_after),
        time_stop_after=_normalize_schedule_value(args.time_stop_after),
        clock_timezone=args.clock_timezone,
    )
    max_gap_pct = None if args.max_gap_pct is not None and args.max_gap_pct < 0 else args.max_gap_pct
    watchlist_cfg = LongDipConfig(
        min_gap_pct=args.min_gap_pct,
        max_gap_pct=max_gap_pct,
        min_previous_close=args.min_previous_close,
        min_premarket_volume=args.min_premarket_volume,
        min_premarket_trade_count=args.min_premarket_trade_count,
        position_budget_usd=args.position_budget_usd,
        top_n=args.watchlist_top_n,
    )

    watchlist_csv = None if args.bundle else args.watchlist_csv
    watchlist, source_metadata = load_watchlist_frame(
        watchlist_csv=watchlist_csv,
        bundle=args.bundle,
        export_dir=args.export_dir,
        watchlist_cfg=watchlist_cfg,
    )
    selected_trade_date = resolve_trade_date(watchlist, args.trade_date)
    filtered_watchlist = filter_watchlist(
        watchlist,
        trade_date=selected_trade_date,
        symbols=_parse_symbol_filter(args.symbols),
        top_n=args.top_n,
    )
    intents = build_order_intents(filtered_watchlist, execution_cfg)
    preview_payload = build_preview_payload(
        intents,
        connection_cfg=connection_cfg,
        source_metadata={
            **source_metadata,
            "selected_trade_date": selected_trade_date.isoformat(),
            "symbols": _parse_symbol_filter(args.symbols),
            "top_n": args.top_n,
            "exit_mode": execution_cfg.exit_mode,
            "cancel_unfilled_after": execution_cfg.cancel_unfilled_after,
            "time_stop_after": execution_cfg.time_stop_after,
            "clock_timezone": execution_cfg.clock_timezone,
        },
    )

    if not intents:
        submission: dict[str, Any] = {"placements": []}
        event_log = build_execution_event_log(submission, None)
        result: dict[str, Any] = {
            "preview": preview_payload,
            "submission": submission,
            "supervisor": None,
            "event_log": event_log,
            "event_log_csv": str(Path(args.supervisor_events_csv).expanduser()),
        }
        output_path = Path(args.supervisor_json).expanduser()
        event_log_path = Path(args.supervisor_events_csv).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(result, indent=2, default=str), output_path)
        write_execution_event_log_csv(event_log, event_log_path)
        print("SUPERVISOR_JSON", output_path)
        print("SUPERVISOR_EVENTS_CSV", event_log_path)
        print(json.dumps(result, indent=2, default=str))
        return

    IB, _, _, _, _ = _import_ibkr_types()
    ib = IB()
    try:
        ib.connect(
            connection_cfg.host,
            connection_cfg.port,
            clientId=connection_cfg.client_id,
            timeout=connection_cfg.timeout_seconds,
            readonly=False,
        )
        # IBKR-audit 2026-06-11 (S5): abort if a live TWS hides behind the
        # paper port before any order is transmitted.
        assert_paper_account_if_paper_port(ib, connection_cfg)
        from scripts.execute_ibkr_watchlist import place_order_intents_with_ib

        submission = place_order_intents_with_ib(ib, intents, connection_cfg=connection_cfg, execution_cfg=execution_cfg)
        supervisor = supervise_open_execution(
            ib,
            connection_cfg=connection_cfg,
            execution_cfg=execution_cfg,
            trade_dates_by_symbol=submission["trade_dates_by_symbol"],
            entry_order_refs_by_symbol=submission["entry_order_refs_by_symbol"],
            all_order_refs_by_symbol=submission["all_order_refs_by_symbol"],
            poll_interval_seconds=args.poll_interval_seconds,
            timeout_seconds=args.supervisor_timeout_seconds,
            reconnect_max_attempts=args.reconnect_max_attempts,
            reconnect_wait_seconds=args.reconnect_wait_seconds,
        )
        event_log = build_execution_event_log(submission, supervisor)
        result = {
            "preview": preview_payload,
            "submission": submission,
            "supervisor": supervisor,
            "event_log": event_log,
            "event_log_csv": str(Path(args.supervisor_events_csv).expanduser()),
        }
    finally:
        if ib.isConnected():
            ib.disconnect()

    output_path = Path(args.supervisor_json).expanduser()
    event_log_path = Path(args.supervisor_events_csv).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(result, indent=2, default=str), output_path)
    write_execution_event_log_csv(result["event_log"], event_log_path)

    print("SELECTED_TRADE_DATE", selected_trade_date.isoformat())
    print("ORDER_INTENTS", len(intents))
    print("SUPERVISOR_JSON", output_path)
    print("SUPERVISOR_EVENTS_CSV", event_log_path)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

"""ADR-0023 §5 — turn the C8 incubation ledger into execution sessions.

:mod:`governance.execution_costs` measures realized cost from the audit JSON
that ``scripts/run_ibkr_open_execution.py --supervisor-json`` writes. That file
has never existed: no job invokes the script, so §5 has run only against the
flat pre-registered ``DEFAULT_COST_BPS = 5.0`` placeholder. The paper track
record lives in ``cache/live/incubation_*.jsonl`` instead — one line per
intent, written at submit time and **rewritten in place** by the daily
reconciler (``paper_submitted`` becomes ``filled`` / ``stop_hit``).

This module converts those lines into the session shape the estimator already
understands, deriving only what the ledger actually determines:

``entry_price``
    The bracket's limit reference for the entry leg (``lmt_price``).
``fill_price`` / ``filled_shares``
    The entry fill (VWAP and size). Slippage is measured against the limit.
``close_price`` (``stop_hit`` rows only)
    The exit fill. A stop carries no limit level, so the exit leg is
    **fee-only** by the estimator's own rule — its slippage is not invented.
direction
    Derived from the bracket (``stop_loss < entry_price < take_profit`` is a
    long) and **refused** when the bracket says otherwise. Every one of the 130
    rows on record is a long; a short would need its own measured convention,
    not a guess.

Rows that never reached the market (``submit_failed``, ``audit_only``) are not
orders. Whole days the reconciler never touched are **unknown, not unfilled**:
counting their submissions as misses would fabricate a fill-rate denominator,
so they are dropped and reported. Nothing here is silently truncated —
:class:`ConversionReport` carries every exclusion.

Pure (stdlib only, no I/O beyond reading the given paths' text); the CLI
wrapper lives in ``scripts/incubation_to_execution_sessions.py``.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ledger actions that mean an order really went to the broker.
_SUBMITTED_ACTIONS = frozenset({"paper_submitted", "filled", "stop_hit"})
# Ledger actions the reconciler writes only after it has seen a fill.
_FILLED_ACTIONS = frozenset({"filled", "stop_hit"})
# Ledger actions where no order ever reached the market.
_NEVER_SUBMITTED_ACTIONS = frozenset({"submit_failed", "audit_only"})

ENTRY_REF_SUFFIX = "-entry"
STOP_REF_SUFFIX = "-stop"


class IncubationConversionError(ValueError):
    """A ledger row cannot be converted without inventing something."""


@dataclass
class ConversionReport:
    """What the conversion used and, just as importantly, what it dropped."""

    sessions_used: int = 0
    rows_used: int = 0
    entry_orders: int = 0
    entry_fills: int = 0
    exit_fills: int = 0
    sessions_skipped_unreconciled: int = 0
    rows_skipped_unreconciled: int = 0
    rows_skipped_never_submitted: int = 0
    skipped_session_dates: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessions_used": self.sessions_used,
            "rows_used": self.rows_used,
            "entry_orders": self.entry_orders,
            "entry_fills": self.entry_fills,
            "exit_fills": self.exit_fills,
            "sessions_skipped_unreconciled": self.sessions_skipped_unreconciled,
            "rows_skipped_unreconciled": self.rows_skipped_unreconciled,
            "rows_skipped_never_submitted": self.rows_skipped_never_submitted,
            "skipped_session_dates": list(self.skipped_session_dates),
        }


def load_incubation_rows(paths: list[Path] | list[str]) -> list[dict[str, Any]]:
    """Read the ledger lines from *paths* in the order given."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IncubationConversionError(f"{path}:{lineno}: malformed JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise IncubationConversionError(f"{path}:{lineno}: expected a JSON object")
            rows.append(row)
    return rows


def _session_date(row: dict[str, Any]) -> str:
    ts = str(row.get("ts") or "")
    if len(ts) < 10:
        raise IncubationConversionError(f"row without a usable ts: {row.get('intent_id')!r}")
    return ts[:10]


def _require_long(row: dict[str, Any]) -> None:
    entry = row.get("entry_price")
    stop = row.get("stop_loss")
    target = row.get("take_profit")
    if entry is None or stop is None or target is None:
        raise IncubationConversionError(
            f"{row.get('intent_id')!r}: incomplete bracket, direction undetermined"
        )
    if not (float(stop) < float(entry) < float(target)):
        raise IncubationConversionError(
            f"{row.get('intent_id')!r}: bracket does not describe a long; "
            "direction is not derivable and is never guessed"
        )


def _fill_time(row: dict[str, Any]) -> tuple[Any, str]:
    """The fill's timestamp and which ledger field it came from.

    ``reconciled_at`` is when the reconciler observed the fill; ``ts`` is when
    the intent was submitted. They are different events, so the source is
    disclosed rather than collapsed into one anonymous value.
    """
    reconciled = row.get("reconciled_at")
    if reconciled is not None:
        return reconciled, "reconciled_at"
    return row.get("ts"), "submitted_ts"


def _positive(value: Any, *, field_name: str, intent: Any) -> float:
    if value is None:
        raise IncubationConversionError(f"{intent!r}: missing {field_name}")
    number = float(value)
    if number <= 0:
        raise IncubationConversionError(f"{intent!r}: {field_name} must be positive, got {number}")
    return number


def build_sessions(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], ConversionReport]:
    """Group *rows* into one execution session per trading day.

    Returns ``(sessions, report)``. Sessions are ordered by session date and
    carry the ``{"submission": ..., "supervisor": ...}`` shape consumed by
    :func:`governance.execution_costs.calibrate_costs`.
    """
    report = ConversionReport()
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[_session_date(row)].append(row)

    sessions: list[dict[str, Any]] = []
    skipped_dates: list[str] = []

    for session_date in sorted(by_day):
        day_rows = by_day[session_date]
        market_rows = [r for r in day_rows if r.get("action") in _SUBMITTED_ACTIONS]
        report.rows_skipped_never_submitted += sum(
            1 for r in day_rows if r.get("action") in _NEVER_SUBMITTED_ACTIONS
        )
        if not market_rows:
            continue
        # Reconciliation evidence is per DAY, because the reconciler stamps
        # only the rows it resolved: a day with no stamp at all was never
        # reconciled, so its submissions have an UNKNOWN outcome — not a
        # missed fill. Dropping them keeps the fill rate honest.
        if not any(r.get("reconciled_at") for r in market_rows):
            report.sessions_skipped_unreconciled += 1
            report.rows_skipped_unreconciled += len(market_rows)
            skipped_dates.append(session_date)
            continue

        placements: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        for row in market_rows:
            _require_long(row)
            intent = str(row.get("intent_id") or "")
            if not intent:
                raise IncubationConversionError(f"{session_date}: row without an intent_id")
            symbol = str(row.get("symbol") or "")
            entry_ref = f"{intent}{ENTRY_REF_SUFFIX}"
            limit = _positive(row.get("entry_price"), field_name="entry_price", intent=intent)
            orders: list[dict[str, Any]] = [
                {"order_ref": entry_ref, "action": "BUY", "lmt_price": limit}
            ]
            report.entry_orders += 1

            if row.get("action") in _FILLED_ACTIONS:
                price = _positive(row.get("fill_price"), field_name="fill_price", intent=intent)
                shares = _positive(
                    row.get("filled_shares"), field_name="filled_shares", intent=intent
                )
                fill_time, fill_time_source = _fill_time(row)
                fills.append(
                    {
                        "order_ref": entry_ref,
                        "perm_id": entry_ref,
                        "symbol": symbol,
                        "side": "BOT",
                        "shares": shares,
                        "price": price,
                        "time": fill_time,
                        "time_source": fill_time_source,
                    }
                )
                report.entry_fills += 1

                if row.get("action") == "stop_hit":
                    # A stop exit fills at the market, with no limit level to
                    # measure against: fee-only by the estimator's contract
                    # (no lmt_price, and the ref is not one of its limit-
                    # bearing suffixes).
                    stop_ref = f"{intent}{STOP_REF_SUFFIX}"
                    close = _positive(
                        row.get("close_price"), field_name="close_price", intent=intent
                    )
                    orders.append({"order_ref": stop_ref, "action": "SELL"})
                    fills.append(
                        {
                            "order_ref": stop_ref,
                            "perm_id": stop_ref,
                            "symbol": symbol,
                            "side": "SLD",
                            "shares": shares,
                            "price": close,
                            "time": fill_time,
                            "time_source": fill_time_source,
                        }
                    )
                    report.exit_fills += 1

            placements.append({"symbol": symbol, "orders": orders})
            report.rows_used += 1

        sessions.append(
            {
                "session_date": session_date,
                "source": "cache/live/incubation",
                "submission": {"placements": placements},
                "supervisor": {"snapshots": [], "final": {"fills": fills}},
            }
        )
        report.sessions_used += 1

    report.skipped_session_dates = tuple(skipped_dates)
    return sessions, report

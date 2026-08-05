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
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

# Ledger actions that mean an order really went to the broker. `tp_hit` and
# `stop_hit` are what reconcile_incubation_fills writes when the take-profit
# or the stop/trail leg fills (_EXIT_LEG_ACTIONS there).
_SUBMITTED_ACTIONS = frozenset({"paper_submitted", "filled", "stop_hit", "tp_hit"})
# Ledger actions the reconciler writes only after it has seen an entry fill.
_FILLED_ACTIONS = frozenset({"filled", "stop_hit", "tp_hit"})
# Ledger actions where no order ever reached the market.
_NEVER_SUBMITTED_ACTIONS = frozenset({"submit_failed", "audit_only"})

# Order-ref suffixes as scripts/execute_ibkr_watchlist.py assigns them; the
# estimator reads `-entry` and `-tp` as limit-bearing and everything else as
# fee-only.
ENTRY_REF_SUFFIX = "-entry"
# Exit action -> (ref suffix, whether the exit order carried a limit level).
_EXIT_LEGS: Final = {
    "tp_hit": ("-tp", "take_profit"),
    "stop_hit": ("-sl", None),
}

_SESSION_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    rows_without_fill_evidence: int = 0
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
            "rows_without_fill_evidence": self.rows_without_fill_evidence,
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
    """The trading day this row belongs to, validated.

    It becomes a filename in the CLI, so anything that is not a plain ISO date
    is refused rather than written somewhere unexpected.
    """
    ts = str(row.get("ts") or "")
    candidate = ts[:10]
    if not _SESSION_DATE_RE.fullmatch(candidate):
        raise IncubationConversionError(
            f"{row.get('intent_id')!r}: session date not derivable from ts {ts!r}"
        )
    return candidate


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
    *,
    unreconciled_days: str = "count",
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
        for row in day_rows:
            action = row.get("action")
            if action not in _SUBMITTED_ACTIONS and action not in _NEVER_SUBMITTED_ACTIONS:
                raise IncubationConversionError(
                    f"{row.get('intent_id')!r}: unknown action {action!r}; "
                    "teach the adapter rather than letting the row vanish"
                )
        market_rows = [r for r in day_rows if r.get("action") in _SUBMITTED_ACTIONS]
        report.rows_skipped_never_submitted += sum(
            1 for r in day_rows if r.get("action") in _NEVER_SUBMITTED_ACTIONS
        )
        if not market_rows:
            continue
        report.rows_without_fill_evidence += sum(
            1 for r in market_rows if not r.get("reconciled_at")
        )
        # A day with no `reconciled_at` anywhere is NOT provably unreconciled:
        # reconcile_incubation_fills stamps the field only inside its entry-fill
        # branch, so a day it processed with zero fills looks exactly the same
        # as a day it never saw. Dropping such days would remove misses only —
        # and the fill rate is the bar the real data has to clear — so the
        # default counts them and skipping is the operator's explicit call.
        if unreconciled_days == "skip" and not any(r.get("reconciled_at") for r in market_rows):
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

                exit_leg = _EXIT_LEGS.get(str(row.get("action")))
                if exit_leg is not None:
                    # A stop fills at the market with no level to measure
                    # against (fee-only by the estimator's contract); a
                    # take-profit is a limit order, and `-tp` is the one exit
                    # suffix the estimator measures slippage on.
                    suffix, limit_field = exit_leg
                    exit_ref = f"{intent}{suffix}"
                    close = _positive(
                        row.get("close_price"), field_name="close_price", intent=intent
                    )
                    exit_order: dict[str, Any] = {"order_ref": exit_ref, "action": "SELL"}
                    if limit_field is not None:
                        exit_order["lmt_price"] = _positive(
                            row.get(limit_field), field_name=limit_field, intent=intent
                        )
                    orders.append(exit_order)
                    fills.append(
                        {
                            "order_ref": exit_ref,
                            "perm_id": exit_ref,
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

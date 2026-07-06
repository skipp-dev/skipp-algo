"""C13 reconcile-fills stage — stamp realized paper fills onto the audit JSONL.

The Phase-A cron (``run-c13-phase-a.sh``) submits bracket sets to the IBKR
*paper* TWS via ``run_smc_live_incubation --place-paper-orders`` and records
one ``action="paper_submitted"`` line per intent in
``cache/live/incubation_<DATE>.jsonl``. Nothing in that path knows the fills:
``fill_price`` stays ``null`` and ``scripts/backfill_live_outcomes.py`` (which
needs ``close_price``/``close_action``/``size_usd`` "from the executor's
reconcile-fills stage") never had a producer — the stage this module adds.

Run AFTER the US close (the ``com.skippalgo.c13.reconcile`` LaunchAgent fires
Mon-Fri 23:05 local): it queries the day's executions from the paper TWS,
matches them to intents via the bracket legs' ``orderRef`` scheme
(``<intent_id>-entry`` / ``-tp`` / ``-sl`` / ``-trail`` as assigned by
``scripts.execute_ibkr_watchlist``), and rewrites the audit JSONL:

* entry leg filled              -> ``action="filled"``, ``fill_price``,
                                   ``size_usd`` (= entry avg x quantity)
* take-profit leg filled        -> ``action="tp_hit"``, ``close_price``
* stop / trail leg filled       -> ``action="stop_hit"``, ``close_price``

It then calls :func:`scripts.backfill_live_outcomes.backfill_live_outcomes`
so closed records carry ``outcome_pnl_usd`` / ``outcome_r_multiple``. These
records are the **measurable paper fills** the ADR-0023 §5 E[PnL]-after-cost
gate is blocked on (>= 20 fills).

Safety: connects **read-only** and refuses non-paper ports (7497 TWS paper /
4002 Gateway paper) — same posture as the submit path's paper-port guard.
No IBKR client import at module load time (mirrors run_smc_live_incubation).

Exit codes
----------
* ``0`` — reconciled (including a day with zero submitted intents or zero
  fills: an empty-entry day is a normal outcome, not an error).
* ``1`` — usage/config error (bad path, malformed JSONL, non-paper port,
  TWS unreachable).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

# TWS paper (7497) and IB Gateway paper (4002). Everything else is refused.
PAPER_PORTS = frozenset({7497, 4002})

# Bracket-leg suffix -> close_action for the exit legs (entry is special-
# cased). Values must stay inside backfill_live_outcomes._CLOSED_ACTIONS.
_EXIT_LEG_ACTIONS = {
    "tp": "tp_hit",
    "sl": "stop_hit",
    "trail": "stop_hit",
}

# Records in these states are still awaiting (more) fills; everything else
# (audit_only, submit_failed, tp_hit, ...) is never touched.
_RECONCILABLE_ACTIONS = frozenset({"paper_submitted", "filled"})


def summarize_fills(fills: list[Any]) -> dict[str, dict[str, float]]:
    """Volume-weighted average fill per ``orderRef``.

    ``fills`` are ib_async ``Fill`` objects (only ``execution.orderRef``,
    ``execution.shares`` and ``execution.price`` are read, so tests can pass
    plain stand-ins). Partial fills of the same order aggregate into one
    weighted average.
    """
    agg: dict[str, dict[str, float]] = {}
    for fill in fills:
        execution = getattr(fill, "execution", None)
        if execution is None:
            continue
        order_ref = str(getattr(execution, "orderRef", "") or "").strip()
        if not order_ref:
            continue
        try:
            shares = float(getattr(execution, "shares", 0) or 0)
            price = float(getattr(execution, "price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if shares <= 0 or price <= 0:
            continue
        slot = agg.setdefault(order_ref, {"shares": 0.0, "notional": 0.0})
        slot["shares"] += shares
        slot["notional"] += shares * price
    return {
        ref: {"shares": v["shares"], "avg_price": v["notional"] / v["shares"]}
        for ref, v in agg.items()
        if v["shares"] > 0
    }


def legs_by_intent(by_ref: dict[str, dict[str, float]]) -> dict[str, dict[str, dict[str, float]]]:
    """Regroup per-orderRef fills into ``{intent_id: {leg_suffix: fill}}``."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for order_ref, fill in by_ref.items():
        intent_id, sep, suffix = order_ref.rpartition("-")
        if not sep or suffix not in ({"entry"} | set(_EXIT_LEG_ACTIONS)):
            continue
        out.setdefault(intent_id, {})[suffix] = fill
    return out


def reconcile_records(
    records: list[dict[str, Any]],
    intent_legs: dict[str, dict[str, dict[str, float]]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Stamp fills onto reconcilable records; pure + idempotent.

    Re-running with the same executions is a no-op on already-closed
    records (their action left ``_RECONCILABLE_ACTIONS``); a record that
    only reached ``filled`` earlier upgrades to closed when the exit leg
    has filled by the later run.
    """
    counts = {"reconcilable": 0, "entry_filled": 0, "closed": 0}
    for record in records:
        if record.get("action") not in _RECONCILABLE_ACTIONS:
            continue
        counts["reconcilable"] += 1
        legs = intent_legs.get(str(record.get("intent_id") or ""))
        if not legs:
            continue
        entry = legs.get("entry")
        if entry is None:
            # Exit fills without an entry fill would be an inconsistent
            # bracket state — leave the record for manual inspection.
            continue
        record["fill_price"] = round(entry["avg_price"], 6)
        quantity = record.get("quantity") or entry["shares"]
        record["size_usd"] = round(entry["avg_price"] * float(quantity), 2)
        record["action"] = "filled"
        counts["entry_filled"] += 1
        for suffix, close_action in _EXIT_LEG_ACTIONS.items():
            exit_fill = legs.get(suffix)
            if exit_fill is not None:
                record["close_price"] = round(exit_fill["avg_price"], 6)
                record["action"] = close_action
                counts["closed"] += 1
                break
        record["reconciled_at"] = datetime.now(UTC).isoformat()
    return records, counts


def _load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            # Fail CLOSED: rewriting an audit file we cannot fully parse
            # would silently drop history.
            raise ValueError(f"{path}:{lineno}: malformed JSONL line: {exc}") from exc
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        default=None,
        help="incubation audit JSONL (default: cache/live/incubation_<today-UTC>.jsonl)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=7497,
        help=f"IBKR API port; must be a PAPER port {sorted(PAPER_PORTS)}",
    )
    parser.add_argument("--client-id", type=int, default=87)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="skip the backfill_live_outcomes PnL/R stamping pass",
    )
    args = parser.parse_args(argv)

    if args.port not in PAPER_PORTS:
        print(
            f"error: port {args.port} is not a paper port {sorted(PAPER_PORTS)}; "
            "this reconciler is Phase-A paper-only by design",
            file=sys.stderr,
        )
        return 1

    audit_path = Path(
        args.audit
        or f"cache/live/incubation_{datetime.now(UTC).date().isoformat()}.jsonl"
    )
    if not audit_path.is_file():
        print(f"error: audit file not found: {audit_path}", file=sys.stderr)
        return 1

    try:
        records = _load_records(audit_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    n_reconcilable = sum(
        1 for r in records if r.get("action") in _RECONCILABLE_ACTIONS
    )
    if n_reconcilable == 0:
        print(
            f"reconcile: {audit_path} has no paper_submitted/filled records — "
            "nothing to reconcile (normal on a no-entry or audit-only day)"
        )
        return 0

    # Deferred import: no IBKR client at module load time.
    from ib_async import IB, ExecutionFilter

    ib = IB()
    try:
        ib.connect(
            args.host,
            args.port,
            clientId=args.client_id,
            timeout=args.timeout,
            readonly=True,
        )
        fills = ib.reqExecutions(ExecutionFilter())
    except Exception as exc:  # connect/API errors: fail loud, launchd shows red
        print(f"error: IBKR executions query failed: {exc}", file=sys.stderr)
        return 1
    finally:
        ib.disconnect()

    records, counts = reconcile_records(records, legs_by_intent(summarize_fills(fills)))
    rendered = "\n".join(json.dumps(r, sort_keys=True) for r in records)
    atomic_write_text(rendered + "\n", str(audit_path))

    outcome_stats: dict[str, int] = {}
    if not args.skip_backfill:
        from scripts.backfill_live_outcomes import backfill_live_outcomes

        outcome_stats = backfill_live_outcomes(audit_path)

    print(
        f"reconcile: {audit_path} — reconcilable={counts['reconcilable']} "
        f"entry_filled={counts['entry_filled']} closed={counts['closed']} "
        f"outcomes={outcome_stats or 'skipped'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

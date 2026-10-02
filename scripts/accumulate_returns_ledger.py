"""Grow a per-plane ledger of closed trades (ADR-0031, Nachtrag 2026-10-01 and 2026-10-02 II).

Why this exists
---------------
``scripts/build_returns_series.py`` grades the accumulated FamilyEvent pool —
and the pool is a ROLLING 30-day window (``accumulate_family_events.py
--max-age-days 30``). The daily series is therefore a window too: a trade that
ages out of the pool is gone, and the sample can never grow past what 30 days
hold. Measured 2026-10-01 on the governed 1D plane: 29-34 trades across the
twelve committed reports of 2026-08-14..28, against pre-registered minimum samples of
120-200 per family (``governance/edge_hypotheses.json``) and the track-record
gate's own floor of 100.

This script is the memory the window lacks. Each run takes the same
plane-filtered pool the series is built from, computes the same return
(``governance.family_returns.realized_return``), and APPENDS every
trade it has not recorded yet to a committed JSONL ledger. Nothing is ever
rewritten: a trade's return is final the moment it exists (entry at the open
after the decision bar, exit a fixed horizon later — a longer forward window
cannot change either), so the first observation is the record.

Identity
--------
A ledger row is keyed by the event's ``event_id``. Events without one are
counted and skipped: a key that cannot tell two events apart is exactly the
defect measured in the pool on 2026-10-01 (``(family, anchor_ts)`` collapsed
86 % of a day's events), and a ledger is the wrong place to repeat it.

One rule per ledger
-------------------
Every row records ``return_rule`` and ``cost_bps``. A run whose rule or cost
differs from the rows already present REFUSES to append (rc 2): switching the
trade definition is an explicit, reviewed change (ADR-0031), and a ledger that
silently pooled two definitions would be a third one nobody chose. Start a new
ledger file instead. That is what happened on 2026-10-02: the Variant-A ledgers
are frozen under ``docs/calibration/gates/variant_a_frozen/`` and these files
began empty under ``next_open_then_horizon_close``. The bar grid is part of
the definition too (``bar_grid`` on every row): the rows written in the few
hours before the one-minute offset of the intraday bars was corrected are
frozen under ``docs/calibration/gates/offset_grid_frozen/``.

A re-observed trade whose return differs from its recorded one (same rule) is
NOT overwritten. It is counted and reported, because it means the pool
revised history — which is worth knowing and not worth hiding.

Evidence start
--------------
The cumulative series counts only trades anchored on or after the evidence
start. Earlier trades stay in the ledger (they are facts) but are left out, so
the verdict rests only on what arrived after the measurement was fixed. Two
dates bound it and the LATER one applies:

* ``governance.family_returns.RETURN_RULE_EVIDENCE_START`` — the first trading
  day after the return rule was fixed. It holds for every plane and cannot be
  moved earlier from the command line.
* ``--evidence-start YYYY-MM-DD`` — the day a plane was pre-registered (15m:
  2026-10-01).

Outputs
-------
* ``--ledger``: the JSONL file, existing lines verbatim plus the new rows
  (sorted by anchor, then key), written atomically.
* ``--series-output`` (optional): the cumulative series in exactly the Shape-B
  contract ``scripts/build_track_record_gate.py`` and
  ``scripts/build_regime_stratified_report.py`` read — same keys as
  ``build_returns_series``, plus a ``ledger`` block saying what it is.

Usage::

    python -m scripts.accumulate_returns_ledger \\
        --events artifacts/ci/scored_family_events_accumulated/accumulated_family_events.json \\
        --plane 15m \\
        --date 2026-10-01 \\
        --ledger docs/calibration/gates/ledger/returns_ledger_15m.jsonl \\
        --series-output artifacts/ledger/returns_series_cumulative_15m.json \\
        --evidence-start 2026-10-01
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from governance.family_returns import (
    BAR_GRID,
    DEFAULT_COST_BPS,
    RETURN_RULE,
    RETURN_RULE_EVIDENCE_START,
    event_bar_grid,
    realized_return,
)
from scripts.build_returns_series import (
    SCHEMA_VERSION,
    _load_pool_events,
    _trades_per_year,
)
from scripts.run_magnitude_shadow_ledger import event_measurement_plane
from scripts.smc_atomic_write import atomic_write_json, atomic_write_text

# A recorded return and its re-observation are "the same" within this bound;
# the arithmetic is deterministic, so anything larger is a revised pool.
_PNL_TOLERANCE = 1e-12

RC_OK = 0
RC_RULE_MISMATCH = 2


def _event_key(event: dict[str, Any]) -> str | None:
    """The event's identity, or ``None`` when it has none worth trusting."""
    event_id = event.get("event_id")
    if isinstance(event_id, str) and event_id.strip():
        return event_id.strip()
    return None


def load_ledger(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return ``(raw_lines, rows_by_key)``; both empty for a missing file.

    A missing ledger is the first run. A present but unreadable one is an
    error: appending to a ledger we could not read would duplicate every trade
    in it, and truncating it would lose them.
    """
    if not path.exists():
        return [], {}
    raw_lines: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        key = row.get("key") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key:
            raise ValueError(f"{path}:{lineno}: ledger row without a string 'key'")
        if key in rows:
            raise ValueError(f"{path}:{lineno}: duplicate key {key!r}")
        raw_lines.append(line)
        rows[key] = row
    return raw_lines, rows


def pool_trades(
    events: list[dict[str, Any]], *, plane: str, cost_bps: float
) -> tuple[dict[str, dict[str, Any]], int]:
    """Closed trades of the plane-filtered pool, keyed by event id.

    Returns ``(trades_by_key, n_without_id)``. The return is computed by the
    one function the daily series uses, so ledger and series cannot disagree
    about what a trade earned. Events measured on another bar grid are not
    trades of this ledger and are skipped (ADR-0031, Nachtrag 2026-10-02 III).
    """
    trades: dict[str, dict[str, Any]] = {}
    n_without_id = 0
    for event in events:
        if event_bar_grid(event) != BAR_GRID:
            continue
        ret = realized_return(event, cost_bps=cost_bps)
        if ret is None:
            continue
        key = _event_key(event)
        if key is None:
            n_without_id += 1
            continue
        regime = event.get("regime")
        trades[key] = {
            "key": key,
            "family": str(event["family"]),
            "plane": plane,
            "anchor_ts": float(event["anchor_ts"]),
            "direction": str(event.get("direction", "")),
            "pnl": ret,
            "regime_at_entry": str(regime) if regime else None,
            "return_rule": RETURN_RULE,
            "cost_bps": cost_bps,
            "bar_grid": BAR_GRID,
        }
    return trades, n_without_id


def _existing_rules(rows: dict[str, dict[str, Any]]) -> set[tuple[Any, Any, Any]]:
    """The trade definitions present in a ledger: rule, cost and bar grid.

    A row without ``bar_grid`` was written before 2026-10-02 III and sits on
    the previous grid.
    """
    return {(row.get("return_rule"), row.get("cost_bps"), event_bar_grid(row)) for row in rows.values()}


def merge(
    existing: dict[str, dict[str, Any]],
    observed: dict[str, dict[str, Any]],
    *,
    run_date: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """New rows to append, and the keys whose recorded return was contradicted."""
    new_rows: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for key, trade in observed.items():
        recorded = existing.get(key)
        if recorded is None:
            new_rows.append({**trade, "first_recorded": run_date})
            continue
        if abs(float(recorded["pnl"]) - float(trade["pnl"])) > _PNL_TOLERANCE:
            conflicts.append(key)
    new_rows.sort(key=lambda row: (row["anchor_ts"], row["key"]))
    return new_rows, sorted(conflicts)


def _epoch_at_utc_midnight(day: str) -> float:
    parsed = date.fromisoformat(day)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def build_cumulative_series(
    rows: list[dict[str, Any]],
    *,
    run_date: str,
    plane: str,
    cost_bps: float,
    evidence_start: str | None,
) -> dict[str, Any]:
    """The whole ledger as a Shape-B returns series (see module docstring)."""
    ordered = sorted(rows, key=lambda row: (float(row["anchor_ts"]), str(row["key"])))
    floor = _epoch_at_utc_midnight(evidence_start) if evidence_start else None
    counted = [row for row in ordered if floor is None or float(row["anchor_ts"]) >= floor]

    returns_by_variant: dict[str, list[float]] = {}
    anchor_ts_by_variant: dict[str, list[float]] = {}
    for row in counted:
        returns_by_variant.setdefault(str(row["family"]), []).append(float(row["pnl"]))
        anchor_ts_by_variant.setdefault(str(row["family"]), []).append(float(row["anchor_ts"]))
    trades = [
        {
            "pnl": float(row["pnl"]),
            "regime_at_entry": row["regime_at_entry"],
            "family": str(row["family"]),
            "anchor_ts": float(row["anchor_ts"]),
        }
        for row in counted
        if row.get("regime_at_entry")
    ]
    anchors = [float(row["anchor_ts"]) for row in counted]
    return {
        "schema_version": SCHEMA_VERSION,
        "date": run_date,
        "measurement": {
            "return_rule": RETURN_RULE,
            "bar_grid": BAR_GRID,
            "cost_bps": cost_bps,
            "regime_taxonomy": "point_in_time (TRENDING/RANGING/NEUTRAL)",
            "note": (
                "CUMULATIVE ledger of net returns GIVEN a triggered setup "
                "(untriggered events are not trades); same rule as the daily "
                "window series (entry at the open after the decision bar), every "
                "trade recorded once — see ADR-0031 (Nachtrag 2026-10-01 and "
                "2026-10-02 II) and scripts/accumulate_returns_ledger.py"
            ),
        },
        "ledger": {
            "window": "cumulative",
            "evidence_start": evidence_start,
            "n_trades_ledger": len(ordered),
            "n_trades_before_evidence_start": len(ordered) - len(counted),
            "first_anchor": _iso(min(anchors)) if anchors else None,
            "last_anchor": _iso(max(anchors)) if anchors else None,
        },
        "plane": plane,
        "n_trades": len(counted),
        "n_trades_with_regime": len(trades),
        "returns_by_variant": dict(sorted(returns_by_variant.items())),
        # Parallel to returns_by_variant: the gate's day checks read it
        # (ADR-0031, Nachtrag 2026-10-02).
        "anchor_ts_by_variant": dict(sorted(anchor_ts_by_variant.items())),
        "trades": trades,
        "trades_per_year": _trades_per_year(anchors),
        # The rule has no target/stop (see build_returns_series).
        "rr_target": 1.0,
    }


def effective_evidence_start(requested: str | None) -> str:
    """The later of the plane's own start and the return rule's start.

    A caller can postpone the start of a plane's evidence, never advance it
    before the day the rule was fixed: trades anchored earlier were on the
    table when the rule was chosen.
    """
    if requested is None:
        return RETURN_RULE_EVIDENCE_START
    date.fromisoformat(requested)
    return max(requested, RETURN_RULE_EVIDENCE_START)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Append newly closed trades to a per-plane ledger (ADR-0031)."
    )
    p.add_argument("--events", type=Path, required=True, help="accumulated_family_events.json")
    p.add_argument("--plane", required=True, help="Measurement plane of this ledger (e.g. 1D, 15m)")
    p.add_argument("--date", required=True, help="Run date (YYYY-MM-DD), stamped on new rows")
    p.add_argument("--ledger", type=Path, required=True, help="JSONL ledger to grow")
    p.add_argument("--series-output", type=Path, default=None, help="Cumulative Shape-B series")
    p.add_argument(
        "--evidence-start",
        default=None,
        help="YYYY-MM-DD the plane was pre-registered; earlier trades stay in "
        "the ledger but are left out of the cumulative series. Never earlier "
        f"than the return rule's own start ({RETURN_RULE_EVIDENCE_START}).",
    )
    p.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = p.parse_args(argv)

    date.fromisoformat(args.date)  # a malformed run date must not reach the ledger
    evidence_start = effective_evidence_start(args.evidence_start or None)

    pool = _load_pool_events(args.events)
    on_plane = [e for e in pool if event_measurement_plane(e) == args.plane]
    observed, n_without_id = pool_trades(on_plane, plane=args.plane, cost_bps=args.cost_bps)

    raw_lines, existing = load_ledger(args.ledger)
    foreign = _existing_rules(existing) - {(RETURN_RULE, args.cost_bps, BAR_GRID)}
    if foreign:
        print(
            f"error: {args.ledger} holds rows under {sorted(map(str, foreign))}, this run "
            f"uses ({RETURN_RULE!r}, {args.cost_bps}, {BAR_GRID!r}). A ledger carries ONE trade "
            "definition; start a new file for a new rule, cost or bar grid.",
            file=sys.stderr,
        )
        return RC_RULE_MISMATCH

    new_rows, conflicts = merge(existing, observed, run_date=args.date)
    if new_rows or not args.ledger.exists():
        lines = raw_lines + [json.dumps(row, sort_keys=True) for row in new_rows]
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text("".join(f"{line}\n" for line in lines), args.ledger)

    all_rows = list(existing.values()) + new_rows
    if args.series_output is not None:
        payload = build_cumulative_series(
            all_rows,
            run_date=args.date,
            plane=args.plane,
            cost_bps=args.cost_bps,
            evidence_start=evidence_start,
        )
        atomic_write_json(payload, args.series_output)

    for key in conflicts:
        print(
            f"::warning title=returns-ledger::{args.plane}: pool re-observed {key} with a "
            "different return than recorded — the recorded value stays",
            file=sys.stderr,
        )
    if n_without_id:
        print(
            f"::warning title=returns-ledger::{args.plane}: {n_without_id} closed trade(s) "
            "without event_id were not recorded (no trustworthy identity)",
            file=sys.stderr,
        )
    per_family: dict[str, int] = {}
    for row in all_rows:
        per_family[str(row["family"])] = per_family.get(str(row["family"]), 0) + 1
    print(
        f"returns ledger {args.plane}: pool {len(on_plane)}/{len(pool)} events on plane, "
        f"{len(observed)} closed trades observed, {len(new_rows)} new, "
        f"{len(conflicts)} contradicted, ledger now {len(all_rows)} "
        f"({', '.join(f'{f}:{n}' for f, n in sorted(per_family.items())) or 'empty'})"
    )
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())

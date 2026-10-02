"""Persist the per-trade returns series for the C6/C7 gate + C5 stratification.

ADR-0031: this is the missing "persisted returns source" edge the C6/C7
track-record gate and the C5 regime stratification were blocked on. The
returns definition is deliberately NOT its own: it is the repo-wide rule in
``governance/family_returns.py`` (``next_open_then_horizon_close`` + fixed
round-turn cost since 2026-10-02; Variant A before) that the daily promotion
gate grades direction edge with — one trade definition, no second scale to
drift against.

Input: the accumulated FamilyEvent pool
(``accumulated_family_events.json``, a CI-artifact chain maintained by
``smc-measurement-benchmark-rolling.yml``), plane-filtered exactly like
``scripts/build_promotion_gate_bundle.py`` (#3874).

Output (one JSON, atomic):

* ``returns_by_variant`` — per-family net-return lists in exactly the
  Shape-B contract ``scripts/build_track_record_gate.py`` reads.
* ``anchor_ts_by_variant`` — the anchor of every return, parallel to
  ``returns_by_variant``; the gate counts trading days from it and
  resamples whole days (ADR-0031, Nachtrag 2026-10-02).
* ``trades`` — per-trade records ``{"pnl", "regime_at_entry", "family",
  "anchor_ts"}`` for :mod:`scripts.regime_stratification` /
  :mod:`scripts.regime_stratified_inference` (only events that both
  triggered AND carry a point-in-time regime label; regimes are never
  invented). The event's regime taxonomy is TRENDING/RANGING/NEUTRAL
  (``governance.family_event_score.point_in_time_regime``).
* ``trades_per_year`` — observed trade frequency over the pool's anchor
  span, so the gate's Sharpe annualisation uses the trade clock
  (stat-review S4 #2674); ``null`` when the span is degenerate.
* a ``measurement`` disclosure block (rule, cost, "returns given a
  triggered setup") so no consumer can mistake this for portfolio P&L.

Honest-by-default: an empty/missing pool yields an empty series file
(``n_trades: 0``) — downstream the gate then reports insufficient data
instead of a fabricated posture.

Usage::

    python -m scripts.build_returns_series \\
        --events artifacts/ci/scored_family_events_accumulated/accumulated_family_events.json \\
        --plane 1D \\
        --date 2026-07-29 \\
        --output docs/calibration/gates/returns_series_2026-07-29.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from governance.family_returns import (
    DEFAULT_COST_BPS,
    RETURN_RULE,
    extract_family_regime_samples,
    extract_family_returns,
)
from scripts.run_magnitude_shadow_ledger import (
    derive_measurement_plane,
    event_measurement_plane,
)
from scripts.smc_atomic_write import atomic_write_json

SCHEMA_VERSION = 1
_SECONDS_PER_YEAR = 365.25 * 86400.0


def _load_pool_events(path: Path) -> list[dict[str, Any]]:
    """Load the accumulated FamilyEvent pool; [] on missing file.

    A *missing* pool is a normal early-lifecycle state (the CI artifact
    chain may have expired) and yields an honest empty series. A present
    but unreadable/malformed pool is an error — silently grading zero
    trades from a corrupt file would look identical to "no data yet".
    """
    if not path.exists():
        print(f"WARNING: events pool {path} missing — emitting empty series", file=sys.stderr)
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list of FamilyEvent dicts")
    return [e for e in raw if isinstance(e, dict)]


def _trades_per_year(all_timestamps: list[float]) -> float | None:
    """Observed trade frequency from the anchor-ts span; None if degenerate."""
    if len(all_timestamps) < 2:
        return None
    span = max(all_timestamps) - min(all_timestamps)
    if span <= 0.0:
        return None
    return round(len(all_timestamps) / (span / _SECONDS_PER_YEAR), 4)


def build_series_payload(
    events: list[dict[str, Any]],
    *,
    date: str,
    plane: str | None,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    """Assemble the series payload from an (already plane-filtered) pool."""
    grouped = extract_family_returns(events, cost_bps=cost_bps)
    returns_by_variant = {
        family: list(bundle["returns"]) for family, bundle in sorted(grouped.items())
    }
    anchor_ts_by_variant = {
        family: [float(ts) for ts in bundle["timestamps"]]
        for family, bundle in sorted(grouped.items())
    }
    all_ts = [t for bundle in grouped.values() for t in bundle["timestamps"]]

    regime_samples = extract_family_regime_samples(events, cost_bps=cost_bps)
    trades: list[dict[str, Any]] = []
    for family in sorted(regime_samples):
        bundle = regime_samples[family]
        for ret, regime, ts in zip(
            bundle["returns"], bundle["regimes"], bundle["anchor_ts"]
        ):
            trades.append(
                {
                    "pnl": ret,
                    "regime_at_entry": regime,
                    "family": family,
                    "anchor_ts": ts,
                }
            )

    n_trades = sum(len(rs) for rs in returns_by_variant.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        "measurement": {
            "return_rule": RETURN_RULE,
            "cost_bps": cost_bps,
            "regime_taxonomy": "point_in_time (TRENDING/RANGING/NEUTRAL)",
            "note": (
                "net returns GIVEN a triggered setup (untriggered events are "
                "not trades); entry at the open of the bar after the decision "
                "bar, exit at the family-horizon close, fixed round-turn cost — "
                "see ADR-0031 (Nachtrag 2026-10-02 II) and "
                "governance/family_returns.py"
            ),
        },
        "plane": plane,
        "n_trades": n_trades,
        "n_trades_with_regime": len(trades),
        "returns_by_variant": returns_by_variant,
        "anchor_ts_by_variant": anchor_ts_by_variant,
        "trades": trades,
        "trades_per_year": _trades_per_year(all_ts),
        # The rule has no target/stop, so no realized-RR concept applies;
        # rr_target=1.0 keeps the gate on its stricter 0.55 win-rate branch.
        "rr_target": 1.0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Persist the per-trade returns series (ADR-0031)."
    )
    p.add_argument("--events", type=Path, required=True, help="accumulated_family_events.json")
    p.add_argument("--date", required=True, help="Run date (YYYY-MM-DD), recorded in the payload")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--plane",
        default=None,
        help="Governed measurement plane (e.g. 1D); filters pool events by "
        "their own modal bar cadence, mirroring build_promotion_gate_bundle.",
    )
    p.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = p.parse_args(argv)

    events = _load_pool_events(args.events)
    plane_total = len(events)
    plane = args.plane
    if plane:
        events = [e for e in events if event_measurement_plane(e) == plane]
        print(
            f"plane filter: kept {len(events)}/{plane_total} pool events on plane {plane}",
            file=sys.stderr,
        )
    else:
        plane = derive_measurement_plane(events)

    payload = build_series_payload(events, date=args.date, plane=plane, cost_bps=args.cost_bps)
    atomic_write_json(payload, args.output)
    print(
        f"wrote {args.output} (n_trades={payload['n_trades']}, "
        f"with_regime={payload['n_trades_with_regime']}, plane={plane})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

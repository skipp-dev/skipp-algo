"""Build a ``FamilyMetrics`` bundle from rolling-benchmark artifacts.

Sprint W1.b — producer-side glue between the daily rolling-benchmark
output (``artifacts/ci/measurement_benchmark_rolling/<DATE>/``) and
``scripts/run_promotion_gate.py``.

The bundle is intentionally honest-by-default: today the rolling-bench
does not yet measure Brier/ECE/PSI/conformal coverage per family, so
those gate fields stay ``None`` and the strict-mode gate will surface
``info`` blockers for them. That is the correct first-cut signal — the
Decision-First panel will show "metric not measured" cards instead of
a fabricated green posture. Later sprints fill the values in.

What we *can* derive today:

* per-family event counts (from ``plan_2_8_tf_family_rollup.json``),
  attached to ``extras.n_events_total`` so consumers can sort/triage
  even before real gate metrics land;
* ADR-0023 Stage-1 move-size verdicts: the latest shadow-ledger row per
  *candidate* family (BOS/SWEEP) is folded into
  ``magnitude_resolution_pass`` / ``magnitude_auc`` via
  ``scripts.magnitude_snapshot_wiring.gate_snapshots`` (handover §5 item 2
  — previously these fields were always ``None`` ⇒ the gate's
  ``ok_magnitude`` branch stayed dormant). Control families (FVG/OB) are
  never fed — they FAIL by construction. Fail-soft: a missing/empty
  ledger leaves the fields absent (dormant), never blocks the bundle;
* Tier-1 direction metrics from the accumulated FamilyEvent pool
  (``--events``, 2026-07-06): realized per-family returns via
  ``governance.family_returns.extract_family_returns`` (same
  touch-then-horizon rule as ADR-0023 §5) feed
  ``scripts.build_family_metrics.build_family_metrics_from_returns``
  (PSR / MinTRL / BH-FDR). This closes the gap that the EV-20 Tier-1
  verdicts exist only for the 15m plane while the daily gate consumes
  the 1D pool: the gate now measures direction edge on the SAME event
  population its magnitude axis uses. The events' bar interval is
  derived from the data (never asserted) and recorded as
  ``provenance.measurement_plane`` (e.g. ``"1D"``). Fail-soft: a
  missing/unreadable pool leaves the fields ``None`` ("not measured"),
  never blocks the bundle;
* a ``provenance`` dict naming the source artifact + run date so the
  gate report stays traceable.

Usage::

    python scripts/build_promotion_gate_bundle.py \\
        --scoring-root artifacts/ci/measurement_benchmark_rolling/2026-05-17 \\
        --output       artifacts/promotion_gate_bundle.json \\
        --date         2026-05-17
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, get_args

from governance.family_returns import DEFAULT_COST_BPS, RETURN_RULE, extract_family_returns
from governance.family_significance import family_fdr_qvalues
from governance.types import EventFamily
from scripts.build_family_metrics import build_family_metrics_from_returns
from scripts.magnitude_snapshot_wiring import MagnitudeSnapshot, gate_snapshots
from scripts.run_magnitude_shadow_ledger import DEFAULT_LEDGER, derive_measurement_plane
from scripts.smc_atomic_write import atomic_write_json

ALL_FAMILIES: tuple[str, ...] = get_args(EventFamily)
ROLLUP_FILENAME = "plan_2_8_tf_family_rollup.json"


def _read_rollup(scoring_root: Path) -> dict[str, Any] | None:
    path = scoring_root / ROLLUP_FILENAME
    if not path.is_file():
        # Legitimate state (no benchmark run yet) — silently no rollup.
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # An EXISTING but unreadable rollup is a broken handoff, not a
        # missing one — surface it so n_events=0 bundles are explainable.
        print(
            f"WARNING: failed to read rollup {path}: {exc} "
            "(emitting bundle with n_events=0 for all families)",
            file=sys.stderr,
        )
        return None


def _aggregate_family_events(rollup: dict[str, Any] | None) -> dict[str, int]:
    """Sum per-family ``n_events`` across all timeframes in the rollup."""
    totals: dict[str, int] = {fam: 0 for fam in ALL_FAMILIES}
    if not rollup:
        return totals
    per_tf = rollup.get("per_tf") or {}
    if not isinstance(per_tf, dict):
        return totals
    for _tf, slot in per_tf.items():
        if not isinstance(slot, dict):
            continue
        families = slot.get("families") or {}
        if not isinstance(families, dict):
            continue
        for fam, metrics in families.items():
            if fam not in totals or not isinstance(metrics, dict):
                continue
            try:
                totals[fam] += int(metrics.get("n_events") or 0)
            except (TypeError, ValueError):
                continue
    return totals


def _load_magnitude_snapshots(
    magnitude_ledger: str | None,
) -> dict[str, MagnitudeSnapshot]:
    """Latest gate-ready move-size snapshot per candidate family.

    Fail-soft by design (ADR-0023 Stage-1 is measure-only): a missing,
    empty or unreadable ledger yields ``{}`` — the bundle then simply omits
    the magnitude fields and the gate stays dormant for those families, the
    exact pre-wiring behaviour. A broken ledger must never block the daily
    promotion-gate report.
    """
    if not magnitude_ledger:
        return {}
    try:
        return gate_snapshots(magnitude_ledger)
    except (OSError, ValueError, TypeError) as exc:  # pragma: no cover - defensive
        print(
            f"WARNING: failed to read magnitude ledger {magnitude_ledger}: {exc} "
            "(emitting bundle without move-size fields)",
            file=sys.stderr,
        )
        return {}


def _load_pool_events(events_path: str | None) -> list[dict[str, Any]]:
    """Load the accumulated FamilyEvent pool; [] on any problem (fail-soft)."""
    if not events_path:
        return []
    try:
        data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"WARNING: failed to read events pool {events_path}: {exc} "
            "(emitting bundle without Tier-1 direction metrics)",
            file=sys.stderr,
        )
        return []
    if not isinstance(data, list):
        print(
            f"WARNING: events pool {events_path} is not a JSON list "
            "(emitting bundle without Tier-1 direction metrics)",
            file=sys.stderr,
        )
        return []
    return [e for e in data if isinstance(e, dict)]


def _tier1_metrics_from_events(
    events: list[dict[str, Any]],
    *,
    families: tuple[str, ...],
    date: str | None,
) -> dict[str, dict[str, Any]]:
    """Per-family Tier-1 direction metrics from realized pool returns.

    Returns ``{family: family_metrics_dict}`` for every requested family
    with at least one triggered return; families without a triggered
    trade are simply absent (their gate fields stay ``None`` — "not
    measured", never fabricated). BH-FDR is controlled across exactly
    the families measured here. Fail-soft: any per-family computation
    error drops that family with a warning instead of failing the daily
    bundle.
    """
    if not events:
        return {}
    series = extract_family_returns(events)
    # The EV-04 guard accepts datetime/date/str, not raw epoch floats —
    # convert both sides to tz-aware UTC datetimes (same convention).
    if date:
        as_of: _dt.datetime | None = _dt.datetime.strptime(date, "%Y-%m-%d").replace(
            tzinfo=_dt.UTC, hour=23, minute=59, second=59
        )
    else:
        stamps = [t for bundle in series.values() for t in bundle["timestamps"]]
        as_of = (
            _dt.datetime.fromtimestamp(max(stamps), _dt.UTC) if stamps else None
        )

    measured: dict[str, dict[str, Any]] = {}
    for family in families:
        bundle = series.get(family)
        if not bundle or not bundle["returns"]:
            continue
        try:
            measured[family] = build_family_metrics_from_returns(
                family,
                bundle["returns"],
                periods_per_year=252,
                timestamps=(
                    [
                        _dt.datetime.fromtimestamp(t, _dt.UTC)
                        for t in bundle["timestamps"]
                    ]
                    if as_of is not None
                    else None
                ),
                as_of=as_of,
            )
        except (ValueError, TypeError) as exc:
            print(
                f"WARNING: Tier-1 metrics failed for {family}: {exc} "
                "(family stays unmeasured in this bundle)",
                file=sys.stderr,
            )
    if measured:
        qvalues = family_fdr_qvalues(
            {fam: m["extras"]["raw_pvalue"] for fam, m in measured.items()}
        )
        for fam, metrics in measured.items():
            metrics["fdr_pvalue"] = qvalues[fam]
    return measured


def build_bundle(
    *,
    scoring_root: Path,
    date: str | None = None,
    families: tuple[str, ...] = ALL_FAMILIES,
    magnitude_ledger: str | None = DEFAULT_LEDGER,
    events_path: str | None = None,
) -> list[dict[str, Any]]:
    rollup = _read_rollup(scoring_root)
    n_events_per_family = _aggregate_family_events(rollup)
    magnitude_snapshots = _load_magnitude_snapshots(magnitude_ledger)
    pool_events = _load_pool_events(events_path)
    measurement_plane = derive_measurement_plane(pool_events)
    tier1_metrics = _tier1_metrics_from_events(
        pool_events, families=families, date=date
    )

    provenance_common: dict[str, Any] = {
        "source": "smc-measurement-benchmark-rolling",
        "scoring_root": scoring_root.as_posix(),
    }
    if date:
        provenance_common["run_date"] = date
    if rollup is not None:
        provenance_common["rollup_files_scanned"] = int(rollup.get("files_scanned") or 0)

    bundle: list[dict[str, Any]] = []
    for fam in families:
        entry: dict[str, Any] = {
            "family": fam,
            # Real W1 gate metrics are not measured per-family by the
            # rolling-bench yet. Pass-through as None so the strict
            # gate emits honest ``info`` blockers instead of a
            # fabricated value.
            "brier": None,
            "ece": None,
            "fdr_pvalue": None,
            "psr": None,
            "mintrl_years": None,
            "psi": None,
            "live_brier": None,
            "walkforward_brier": None,
            "regime_degraded": None,
            "psi_slope": None,
            "conformal_coverage": None,
            "conformal_target": None,
            "provenance": dict(provenance_common),
            "extras": {
                "n_events_total": float(n_events_per_family.get(fam, 0)),
            },
        }
        tier1 = tier1_metrics.get(fam)
        if tier1 is not None:
            # Tier-1 direction metrics measured on the SAME event pool the
            # magnitude axis consumes. Only fields this path actually
            # measures are copied; everything else stays None ("not
            # measured"). The gate loader coerces extras values to float,
            # so tier-1 extras are flattened, never nested.
            entry["psr"] = tier1["psr"]
            entry["mintrl_years"] = tier1["mintrl_years"]
            entry["fdr_pvalue"] = tier1["fdr_pvalue"]
            t1_extras = tier1.get("extras") or {}
            for src_key, dst_key in (
                ("n_returns", "n_triggered_returns"),
                ("raw_pvalue", "tier1_raw_pvalue"),
                ("sharpe_hat", "tier1_sharpe_hat"),
                ("observed_periods_per_year", "tier1_observed_periods_per_year"),
            ):
                value = t1_extras.get(src_key)
                if value is not None:
                    entry["extras"][dst_key] = float(value)
            entry["provenance"]["tier1"] = dict(tier1.get("provenance") or {})
            entry["provenance"]["tier1_source_events"] = str(events_path)
            entry["provenance"]["tier1_cost_bps"] = DEFAULT_COST_BPS
            entry["provenance"]["tier1_return_rule"] = RETURN_RULE
        if measurement_plane is not None:
            # Derived from the pool's forward timestamps — labels the
            # measurement plane (e.g. BOS@1D vs the 15m EV-20 verdicts) so
            # cross-plane conflation is visible in every gate report.
            entry["provenance"]["measurement_plane"] = measurement_plane
        snap = magnitude_snapshots.get(fam)
        if snap is not None:
            # ADR-0023 Stage-1 → gate snapshot wiring (handover §5 item 2).
            # ``gate_snapshots`` already restricts to candidate families
            # (BOS/SWEEP) — a control family's by-design FAIL can never
            # reach the gate as a hard blocker.
            entry["magnitude_resolution_pass"] = snap.magnitude_resolution_pass
            entry["magnitude_auc"] = snap.magnitude_auc
            entry["provenance"]["magnitude_ledger"] = str(magnitude_ledger)
            entry["provenance"]["magnitude_ledger_date"] = snap.date
            entry["provenance"]["magnitude_status"] = snap.status
        bundle.append(entry)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sprint W1.b: build a FamilyMetrics bundle for "
            "scripts/run_promotion_gate.py from rolling-benchmark artifacts."
        )
    )
    parser.add_argument(
        "--scoring-root",
        type=Path,
        required=True,
        help="Path to artifacts/ci/measurement_benchmark_rolling/<DATE>/.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the FamilyMetrics bundle JSON list.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Run date (YYYY-MM-DD) for provenance; optional.",
    )
    parser.add_argument(
        "--families",
        type=str,
        default=",".join(ALL_FAMILIES),
        help="Comma-separated family allow-list (default: all event families).",
    )
    parser.add_argument(
        "--magnitude-ledger",
        type=str,
        default=DEFAULT_LEDGER,
        help=(
            "ADR-0023 move-size shadow-ledger JSONL whose latest per-family "
            "rows feed magnitude_resolution_pass/magnitude_auc for the gate "
            f"candidates (default: {DEFAULT_LEDGER}). Pass '' to disable "
            "(fields stay absent => gate dormant)."
        ),
    )
    parser.add_argument(
        "--events",
        type=str,
        default=None,
        help=(
            "Accumulated FamilyEvent pool JSON (ADR-0023 Option B artifact). "
            "When given, per-family Tier-1 direction metrics (PSR / MinTRL / "
            "BH-FDR) are computed from realized pool returns and the pool's "
            "measurement plane is recorded in provenance. Omitted or "
            "unreadable => fields stay None (honest 'not measured')."
        ),
    )
    args = parser.parse_args(argv)

    requested = tuple(f.strip() for f in args.families.split(",") if f.strip())
    unknown = [f for f in requested if f not in ALL_FAMILIES]
    if unknown:
        print(
            f"ERROR: unknown families {unknown!r}; allowed: {ALL_FAMILIES}",
            file=sys.stderr,
        )
        return 1

    if not args.scoring_root.exists():
        print(
            f"WARNING: scoring root does not exist: {args.scoring_root} "
            "(emitting bundle with zero event counts)",
            file=sys.stderr,
        )

    bundle = build_bundle(
        scoring_root=args.scoring_root,
        date=args.date,
        families=requested,
        magnitude_ledger=args.magnitude_ledger or None,
        events_path=args.events,
    )
    atomic_write_json(bundle, args.output, indent=2, sort_keys=False)
    n_magnitude = sum(1 for entry in bundle if "magnitude_resolution_pass" in entry)
    n_tier1 = sum(1 for entry in bundle if entry.get("psr") is not None)
    plane = next(
        (
            entry["provenance"]["measurement_plane"]
            for entry in bundle
            if "measurement_plane" in entry.get("provenance", {})
        ),
        "unmeasured",
    )
    print(
        f"wrote {len(bundle)} family entries to {args.output} "
        f"(source: {args.scoring_root}; magnitude snapshots: {n_magnitude}; "
        f"tier1-measured families: {n_tier1}; measurement plane: {plane})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

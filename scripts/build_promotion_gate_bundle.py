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
import json
import sys
from pathlib import Path
from typing import Any, get_args

from governance.types import EventFamily
from scripts.magnitude_snapshot_wiring import MagnitudeSnapshot, gate_snapshots
from scripts.run_magnitude_shadow_ledger import DEFAULT_LEDGER
from scripts.smc_atomic_write import atomic_write_json

ALL_FAMILIES: tuple[str, ...] = get_args(EventFamily)
ROLLUP_FILENAME = "plan_2_8_tf_family_rollup.json"


def _read_rollup(scoring_root: Path) -> dict[str, Any] | None:
    path = scoring_root / ROLLUP_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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


def build_bundle(
    *,
    scoring_root: Path,
    date: str | None = None,
    families: tuple[str, ...] = ALL_FAMILIES,
    magnitude_ledger: str | None = DEFAULT_LEDGER,
) -> list[dict[str, Any]]:
    rollup = _read_rollup(scoring_root)
    n_events_per_family = _aggregate_family_events(rollup)
    magnitude_snapshots = _load_magnitude_snapshots(magnitude_ledger)

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
    )
    atomic_write_json(bundle, args.output, indent=2, sort_keys=False)
    n_magnitude = sum(1 for entry in bundle if "magnitude_resolution_pass" in entry)
    print(
        f"wrote {len(bundle)} family entries to {args.output} "
        f"(source: {args.scoring_root}; magnitude snapshots: {n_magnitude})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

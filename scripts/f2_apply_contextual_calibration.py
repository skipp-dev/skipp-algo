"""F2 dual-arm post-processor — re-score per-event ledger with contextual weights.

Plan reference:
    smc_improvement_plan_q3_q4_2026-04-20.md §2.3 F2 + §2.4 G3
Spec:
    artifacts/experiments/f2_contextual_promotion.json
Decision memo:
    docs/f2_contextual_promotion_decision_2026-04-21.md

Why this script exists
----------------------
The rolling-benchmark workflow (``smc-measurement-benchmark-rolling.yml``)
emits a single-arm artifact set: per-pair ``measurement_summary_*.json``
and ``events_*.jsonl`` ledgers under ``artifacts/ci/measurement_benchmark_rolling/<DATE>/``.

The F2 promotion-gate workflow (``f2-promotion-gate-daily.yml``) however
expects two parallel artifact dirs:

    artifacts/ci/f2/static_global_weights/<DATE>/
    artifacts/ci/f2/contextual_weights/<DATE>/

each containing ``benchmark_run_manifest.json`` + per-pair
``measurement_summary_*.json``. Without the second dir the gate exits
``status=skipped`` indefinitely and the 30-day SPRT countdown never
starts.

This script bridges the two by:

1. Reading the per-event JSONL ledger from the rolling-bench output dir.
2. Re-scoring each event twice in-place (no second harness pass):
     * **Control arm**  — ``predicted_prob`` blended with the family's
       *global* calibrated weight (``zone_priority_calibration.json``).
     * **Treatment arm** — ``predicted_prob`` blended with the family's
       *contextual* weight resolved through the
       ``resolve_contextual_weight`` fallback cascade
       (session → vol_regime → global → default).
3. Running ``smc_core.scoring.score_events`` on each rescored set so the
   resulting ``measurement_summary_*.json`` has fresh ``calibrated_brier``,
   ``calibrated_ece`` and ``family_metrics`` numbers for both arms.
4. Writing two parallel artifact trees (``benchmark_run_manifest.json``
   + per-pair summaries) to the configured output dirs.

Both arms run through the exact same blending transform — only the
weight source differs. This keeps the SPRT delta a measurement of the
*context dimension*, not of the blending function.

Blending formula (default ``--blend-mode anchor``)
--------------------------------------------------
.. code:: text

    p_blended = clip(0.5 + (base - 0.5) + alpha * (w - 0.5), 0.05, 0.95)

with ``alpha=1.0``. This is an additive Bayesian-prior shift that
preserves the directional signal coming out of
``measurement_evidence._directional_probability`` while folding in the
family hit-rate prior (cf. Dawid 1982 / Platt 1999).

The outcome label is *never* rewritten — only ``predicted_prob`` is
mutated, so the harness cannot leak look-ahead through this path.

CLI
---

.. code:: bash

    python scripts/f2_apply_contextual_calibration.py \\
        --control-dir          artifacts/ci/measurement_benchmark_rolling/<DATE> \\
        --contextual-cal       artifacts/ci/measurement_benchmark_rolling/<DATE>/zone_priority_contextual_calibration.json \\
        --global-cal           artifacts/ci/measurement_benchmark_rolling/<DATE>/zone_priority_calibration.json \\
        --output-dir-control   artifacts/ci/f2/static_global_weights/<DATE> \\
        --output-dir-treatment artifacts/ci/f2/contextual_weights/<DATE>

Exit codes
----------
* ``0`` — both arms written, at least one event rescored.
* ``1`` — configuration error (missing input dir, malformed calibration JSON).
* ``2`` — no eligible events found (empty input ledgers); both output dirs
  are still created with empty manifests so the promotion-gate can map the
  condition to ``status=skipped`` next morning.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_zone_priority_calibration import (
    ContextualCalibrationResult,
    resolve_contextual_weight,
)
from scripts.strict_json import dumps_strict_json
from smc_core.event_ledger import read_event_ledger
from smc_core.scoring import (
    ScoredEvent,
    score_events,
    serialize_calibration_summary,
    serialize_contextual_calibration,
    serialize_stratified_calibration,
    summarize_contextual_calibration,
    summarize_stratified_calibration,
)

BlendMode = Literal["anchor"]
SCHEMA_VERSION = "1.0"
DEFAULT_BLEND_ALPHA = 1.0
PROB_LO = 0.05
PROB_HI = 0.95
DEFAULT_FAMILY_WEIGHT = 0.50  # mirrors smc_zone_priority_calibration default


# ── Calibration loading ────────────────────────────────────────────────────


def _load_global_weights(path: Path) -> dict[str, float]:
    """Read ``family_weights`` from a ``zone_priority_calibration.json``.

    Falls back to an empty dict if the file is absent (the post-processor
    will then degrade to the hand-tuned defaults via
    ``DEFAULT_FAMILY_WEIGHT``).
    """
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    fw = raw.get("family_weights") or {}
    return {str(k): float(v) for k, v in fw.items()}


def _load_contextual_calibration(path: Path) -> ContextualCalibrationResult | None:
    """Re-hydrate a ``ContextualCalibrationResult`` from its on-disk form.

    Returns ``None`` if the file does not exist, in which case
    ``resolve_contextual_weight`` will degrade to the hand-tuned
    defaults — and the treatment arm becomes equivalent to the control
    arm. The promotion-gate will then quite correctly converge to
    ``insufficient_data``/``hold``.
    """
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ContextualCalibrationResult(
        contextual_weights=raw.get("contextual_weights") or {},
        promoted_buckets=list(raw.get("promoted_buckets") or []),
        global_weights={str(k): float(v) for k, v in (raw.get("global_weights") or {}).items()},
        bucket_stats=raw.get("bucket_stats") or {},
        min_bucket_events=int(raw.get("min_bucket_events") or 30),
    )


# ── Blending ───────────────────────────────────────────────────────────────


def blend_prob(base: float, weight: float, *, alpha: float = DEFAULT_BLEND_ALPHA) -> float:
    """Anchor-shift blend of a directional probability with a family prior.

    See module docstring for derivation and references.
    """
    blended = 0.5 + (base - 0.5) + alpha * (weight - 0.5)
    if blended < PROB_LO:
        return PROB_LO
    if blended > PROB_HI:
        return PROB_HI
    return blended


# ── Event rescoring ────────────────────────────────────────────────────────


@dataclass(slots=True)
class _RescoredArm:
    events: list[ScoredEvent]
    n_rewritten: int


def _record_to_event(record: dict[str, Any], predicted_prob: float) -> ScoredEvent:
    """Build a ``ScoredEvent`` from a ledger row + an externally supplied prob.

    ``raw_score`` is deliberately NOT forwarded from the ledger row:
    ``smc_core.scoring._resolve_calibration_input`` prefers ``raw_score``
    over ``predicted_prob`` whenever *every* event carries one, which
    would silently discard the blended arm probability — the only thing
    that distinguishes control from treatment. Forwarding it made both
    arms score identically on the production ledgers (which always
    populate ``raw_score``), so every SPRT run before 2026-06-10 compared
    control vs control. See docs/DECISIONS.md
    §2026-06-10 f2-dual-arm-raw-score-shadowing.
    """
    context = record.get("context") or {}
    if not isinstance(context, dict):
        context = {}
    return ScoredEvent(
        event_id=str(record.get("event_id", "")),
        family=record.get("family", "BOS"),  # type: ignore[arg-type]
        predicted_prob=float(predicted_prob),
        outcome=bool(record.get("outcome", False)),
        timestamp=float(record.get("timestamp", 0.0) or 0.0),
        context={str(k): str(v) for k, v in context.items()},
        raw_score=None,
        raw_score_name=None,
        features=dict(record.get("features") or {}),
    )


def rescore_pair(
    ledger_path: Path,
    *,
    global_weights: dict[str, float],
    contextual_cal: ContextualCalibrationResult | None,
    blend_alpha: float = DEFAULT_BLEND_ALPHA,
    force_global: bool = False,
) -> tuple[_RescoredArm, _RescoredArm]:
    """Read one pair's JSONL ledger and produce control + treatment events.

    The two arms differ only in the *weight source*; the blending
    transform is identical so the SPRT delta isolates the context
    dimension.
    """
    control: list[ScoredEvent] = []
    treatment: list[ScoredEvent] = []
    n_control_rewritten = 0
    n_treatment_rewritten = 0

    for record in read_event_ledger(ledger_path):
        family = str(record.get("family", ""))
        base_prob = float(record.get("predicted_prob", 0.5) or 0.5)
        ctx = record.get("context") or {}
        session_ctx = ctx.get("session") if isinstance(ctx, dict) else None
        vol_regime = ctx.get("vol_regime") if isinstance(ctx, dict) else None

        # Control arm: blend with the global calibrated weight.
        w_control = global_weights.get(family, DEFAULT_FAMILY_WEIGHT)
        p_control = blend_prob(base_prob, w_control, alpha=blend_alpha)
        if p_control != base_prob:
            n_control_rewritten += 1
        control.append(_record_to_event(record, p_control))

        # Treatment arm: blend with the contextual cascade unless forced.
        if force_global or contextual_cal is None:
            w_treatment = w_control
        else:
            w_treatment = resolve_contextual_weight(
                contextual_cal,
                family,
                session_context=session_ctx,
                vol_regime=vol_regime,
            )
        p_treatment = blend_prob(base_prob, w_treatment, alpha=blend_alpha)
        if p_treatment != base_prob:
            n_treatment_rewritten += 1
        treatment.append(_record_to_event(record, p_treatment))

    return (
        _RescoredArm(events=control, n_rewritten=n_control_rewritten),
        _RescoredArm(events=treatment, n_rewritten=n_treatment_rewritten),
    )


# ── Output emission ────────────────────────────────────────────────────────


def _build_pair_summary(
    *,
    symbol: str,
    timeframe: str,
    pair_dir: Path,
    scoring_result: Any,
) -> dict[str, Any]:
    """Subset of ``run_smc_measurement_benchmark._build_pair_summary``.

    Only the fields ``generate_performance_report.load_benchmark`` reads
    are populated. Everything else is intentionally absent so it cannot
    drift away from the harness output schema if the harness adds
    fields later.
    """

    calibration = serialize_calibration_summary(scoring_result.calibration)
    stratified = serialize_stratified_calibration(
        getattr(scoring_result, "stratified_calibration", {}) or {}
    )
    contextual = serialize_contextual_calibration(
        getattr(scoring_result, "contextual_calibration", {}) or {}
    )
    family_metrics: dict[str, dict[str, Any]] = {}
    for fam, item in (scoring_result.family_metrics or {}).items():
        family_metrics[str(fam)] = {
            "family": str(fam),
            "n_events": int(getattr(item, "n_events", 0) or 0),
            "brier_score": float(getattr(item, "brier_score", float("nan"))),
            "log_score": float(getattr(item, "log_score", float("nan"))),
            "hit_rate": float(getattr(item, "hit_rate", float("nan"))),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": 0.0,  # deterministic for byte-stable reruns
        "generator": "scripts/f2_apply_contextual_calibration.py",
        "symbol": symbol,
        "timeframe": timeframe,
        "artifact_dir": "",  # set by _write_arm to the rel-path within the arm
        "scoring": {
            "n_events": int(getattr(scoring_result, "n_events", 0) or 0),
            "brier_score": float(getattr(scoring_result, "brier_score", float("nan"))),
            "log_score": float(getattr(scoring_result, "log_score", float("nan"))),
            "hit_rate": float(getattr(scoring_result, "hit_rate", float("nan"))),
            "families_present": sorted(family_metrics.keys()),
            "family_metrics": family_metrics,
            "calibration": calibration,
            "stratified_calibration": stratified,
            "stratified_calibration_summary": summarize_stratified_calibration(
                getattr(scoring_result, "stratified_calibration", {}) or {}
            ),
            "contextual_calibration": contextual,
            "contextual_calibration_summary": summarize_contextual_calibration(
                getattr(scoring_result, "contextual_calibration", {}) or {}
            ),
        },
        "ensemble_quality": {},
        "stratification_coverage": {
            "dimensions_present": [],
            "populated_bucket_count": 0,
        },
        "warnings": [],
    }


def _write_arm(
    out_dir: Path,
    *,
    pair_summaries: list[tuple[str, str, dict[str, Any]]],
    blend_alpha: float,
    arm_name: str,
) -> dict[str, Any]:
    """Write one arm's manifest + per-pair summaries to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pair_runs: list[dict[str, Any]] = []
    for symbol, timeframe, summary in pair_summaries:
        rel_dir = f"{symbol}/{timeframe}"
        pair_dir = out_dir / rel_dir
        pair_dir.mkdir(parents=True, exist_ok=True)
        summary_path = pair_dir / f"measurement_summary_{symbol}_{timeframe}.json"
        # Relative to ``out_dir`` so the on-disk JSON is byte-stable across
        # runs from different working directories (CI vs local vs tmp).
        summary["artifact_dir"] = rel_dir
        atomic_write_text(dumps_strict_json(summary, indent=2, sort_keys=True), summary_path)
        pair_runs.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "artifact_dir": rel_dir,
            "summary_path": f"{rel_dir}/{summary_path.name}",
        })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": 0.0,
        "generator": "scripts/f2_apply_contextual_calibration.py",
        "arm": arm_name,
        "blend_mode": "anchor",
        "blend_alpha": blend_alpha,
        "pair_runs": pair_runs,
    }
    manifest_path = out_dir / "benchmark_run_manifest.json"
    atomic_write_text(dumps_strict_json(manifest, indent=2, sort_keys=True), manifest_path)
    return manifest


# ── Top-level orchestration ────────────────────────────────────────────────


def _iter_pair_ledgers(control_dir: Path) -> Iterable[tuple[str, str, Path]]:
    """Yield (symbol, timeframe, ledger_path) tuples by parsing filenames.

    The control dir layout matches ``run_smc_measurement_benchmark``:
    ``<control_dir>/<SYMBOL>/<TIMEFRAME>/events_<SYMBOL>_<TIMEFRAME>.jsonl``.
    Directory walk is deterministic via ``sorted``.
    """
    for ledger in sorted(control_dir.rglob("events_*.jsonl")):
        stem = ledger.stem  # events_<SYMBOL>_<TIMEFRAME>
        parts = stem.split("_")
        if len(parts) < 3 or parts[0] != "events":
            continue
        symbol = parts[1]
        timeframe = "_".join(parts[2:])
        yield symbol, timeframe, ledger


def apply_contextual_calibration(
    *,
    control_dir: Path,
    contextual_cal_path: Path,
    global_cal_path: Path,
    output_dir_control: Path,
    output_dir_treatment: Path,
    blend_alpha: float = DEFAULT_BLEND_ALPHA,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the dual-arm rescoring + emission pipeline.

    Returns a small summary dict for stdout / step-summary annotation.
    """
    if not control_dir.is_dir():
        raise FileNotFoundError(f"control-dir does not exist: {control_dir}")

    global_weights = _load_global_weights(global_cal_path)
    contextual_cal = _load_contextual_calibration(contextual_cal_path)

    control_summaries: list[tuple[str, str, dict[str, Any]]] = []
    treatment_summaries: list[tuple[str, str, dict[str, Any]]] = []
    total_events = 0
    total_rewritten_treatment = 0

    for symbol, timeframe, ledger in _iter_pair_ledgers(control_dir):
        control_arm, treatment_arm = rescore_pair(
            ledger,
            global_weights=global_weights,
            contextual_cal=contextual_cal,
            blend_alpha=blend_alpha,
        )
        if not control_arm.events:
            continue
        total_events += len(control_arm.events)
        total_rewritten_treatment += treatment_arm.n_rewritten

        control_result = score_events(control_arm.events)
        treatment_result = score_events(treatment_arm.events)
        control_summaries.append((
            symbol,
            timeframe,
            _build_pair_summary(
                symbol=symbol,
                timeframe=timeframe,
                pair_dir=output_dir_control / f"{symbol}/{timeframe}",
                scoring_result=control_result,
            ),
        ))
        treatment_summaries.append((
            symbol,
            timeframe,
            _build_pair_summary(
                symbol=symbol,
                timeframe=timeframe,
                pair_dir=output_dir_treatment / f"{symbol}/{timeframe}",
                scoring_result=treatment_result,
            ),
        ))

    if not dry_run:
        _write_arm(
            output_dir_control,
            pair_summaries=control_summaries,
            blend_alpha=blend_alpha,
            arm_name="static_global_weights",
        )
        _write_arm(
            output_dir_treatment,
            pair_summaries=treatment_summaries,
            blend_alpha=blend_alpha,
            arm_name="contextual_weights",
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "control_dir": str(control_dir),
        "output_dir_control": str(output_dir_control),
        "output_dir_treatment": str(output_dir_treatment),
        "n_pairs": len(control_summaries),
        "n_events": total_events,
        "n_treatment_rewritten": total_rewritten_treatment,
        "blend_alpha": blend_alpha,
        "contextual_cal_loaded": contextual_cal is not None,
        "global_weights_loaded": bool(global_weights),
        "promoted_buckets": list(contextual_cal.promoted_buckets) if contextual_cal else [],
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="F2 dual-arm contextual-calibration post-processor (plan §2.3 F2 / §2.4 G3)"
    )
    parser.add_argument("--control-dir", type=Path, required=True,
                        help="Rolling-benchmark output dir (the source of truth).")
    parser.add_argument("--contextual-cal", type=Path, required=True,
                        help="Path to zone_priority_contextual_calibration.json.")
    parser.add_argument("--global-cal", type=Path, required=True,
                        help="Path to zone_priority_calibration.json (for control arm).")
    parser.add_argument("--output-dir-control", type=Path, required=True,
                        help="Where to write the control-arm benchmark tree.")
    parser.add_argument("--output-dir-treatment", type=Path, required=True,
                        help="Where to write the treatment-arm benchmark tree.")
    parser.add_argument("--blend-alpha", type=float, default=DEFAULT_BLEND_ALPHA,
                        help="Anchor-shift blend coefficient (default: 1.0).")
    parser.add_argument("--blend-mode", choices=("anchor",), default="anchor",
                        help="Blending mode (currently only 'anchor' is implemented).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute but do not write output files.")
    args = parser.parse_args(argv)

    try:
        result = apply_contextual_calibration(
            control_dir=args.control_dir,
            contextual_cal_path=args.contextual_cal,
            global_cal_path=args.global_cal,
            output_dir_control=args.output_dir_control,
            output_dir_treatment=args.output_dir_treatment,
            blend_alpha=args.blend_alpha,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: malformed calibration input: {exc}", file=sys.stderr)
        return 1

    print(dumps_strict_json(result, indent=2, sort_keys=True))
    if result["n_events"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

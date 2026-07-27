"""G3 A/B arm routing for scorer weight sets — run-granular and paired.

`docs/STRATEGY_2026_Q3.md` §G3 defines an A/B between the static scorer weights
(Arm A) and the auto-tuned ones (Arm B, produced by
:mod:`open_prep.candidate_weights`). The building blocks existed but were never
connected to the pipeline, so the decision gate waited on a sample that could
not accumulate.

Why not ``smc_ab_experiment.Experiment.resolve_weight_set``
----------------------------------------------------------
That helper assigns a weight-set label **per symbol**. Scoring symbols with
different weight vectors and then ranking them against each other is not a
valid experiment: the composite score is only comparable under a *fixed* weight
vector, so a per-symbol split yields a top-N blended from two incomparable
scales. Ranking is relative, so the treatment leaks into the control's result.

This module therefore routes arms **per run**: the whole universe is scored
twice, once per arm, and the two rankings are compared. Both arms see the same
day, the same universe and the same regime tilt, so the comparison is *paired* —
methodologically sound and far more powerful than randomising whole days.

Arm B is **shadow-only**: it never changes what the pipeline serves. Only the
comparison record is written — the sample the SPRT stop-rule
(`scripts/smc_sprt_stop_rule.py`) consumes.

Arm parity
----------
Arm A is the live weight set: ``DEFAULT_WEIGHTS`` plus the market regime tilt,
persisted under ``_regime_adjusted``. Arm B applies **the same regime tilt** to
the learned base, so the only difference between the arms is the base weight
vector — not the regime handling.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from open_prep.candidate_weights import CANDIDATE_LABEL, _atomic_write_json
from open_prep.scorer import (
    OUTCOMES_DIR,
    load_weight_set,
    rank_candidates_v2,
    save_weight_set,
)

logger = logging.getLogger("open_prep.ab_arms")

#: Live arm — the label `run_open_prep` scores with.
ARM_A_LABEL = "_regime_adjusted"

#: Shadow arm — learned base + the same regime tilt as Arm A.
ARM_B_LABEL = "_candidate_regime_adjusted"

AB_ARMS_DIR = Path("artifacts/open_prep/ab_arms")


def arm_b_base_available() -> bool:
    """True when :mod:`open_prep.candidate_weights` has produced a candidate set.

    ``load_weight_set`` falls back to ``DEFAULT_WEIGHTS`` for a missing label,
    which would silently make Arm B identical to Arm A and pollute the sample
    with zero-difference rows. So the file is checked explicitly instead.
    """
    return (OUTCOMES_DIR / f"weights_{CANDIDATE_LABEL}.json").exists()


def _spearman_rho(rank_a: dict[str, int], rank_b: dict[str, int]) -> float | None:
    """Spearman's rho over the symbols ranked by both arms.

    Positions are unique within an arm, so there are no ties to correct for and
    the exact form ``1 - 6*sum(d^2) / (n*(n^2-1))`` applies.
    """
    common = sorted(set(rank_a) & set(rank_b))
    n = len(common)
    if n < 2:
        return None
    d_squared = sum((rank_a[s] - rank_b[s]) ** 2 for s in common)
    return round(1.0 - (6.0 * d_squared) / (n * (n * n - 1)), 6)


def _symbols(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        symbol = row.get("symbol")
        if isinstance(symbol, str) and symbol:
            out.append(symbol)
    return out


def compare_arms(
    arm_a_rows: list[dict[str, Any]],
    arm_b_rows: list[dict[str, Any]],
    *,
    top_n: int,
) -> dict[str, Any]:
    """Compare two rankings of the same universe scored under different weights."""
    a_symbols = _symbols(arm_a_rows)
    b_symbols = _symbols(arm_b_rows)
    rank_a = {s: i for i, s in enumerate(a_symbols)}
    rank_b = {s: i for i, s in enumerate(b_symbols)}

    head = max(int(top_n), 1)
    a_head = set(a_symbols[:head])
    b_head = set(b_symbols[:head])
    overlap = a_head & b_head

    common = sorted(set(rank_a) & set(rank_b))
    rank_delta = {s: rank_b[s] - rank_a[s] for s in common}
    abs_deltas = [abs(v) for v in rank_delta.values()]

    return {
        "arm_a_label": ARM_A_LABEL,
        "arm_b_label": ARM_B_LABEL,
        "arm_a_n": len(a_symbols),
        "arm_b_n": len(b_symbols),
        "n_common": len(common),
        "top_n": head,
        "top_n_overlap": len(overlap),
        "top_n_overlap_pct": round(len(overlap) / head, 4),
        "top1_changed": a_symbols[:1] != b_symbols[:1],
        "arm_a_top": a_symbols[:head],
        "arm_b_top": b_symbols[:head],
        "entered_top_n": sorted(b_head - a_head),
        "left_top_n": sorted(a_head - b_head),
        "rank_delta": dict(sorted(rank_delta.items())),
        "max_abs_rank_delta": max(abs_deltas) if abs_deltas else 0,
        "mean_abs_rank_delta": (
            round(sum(abs_deltas) / len(abs_deltas), 4) if abs_deltas else 0.0
        ),
        "spearman_rho": _spearman_rho(rank_a, rank_b),
        "identical_ranking": a_symbols == b_symbols,
    }


def write_ab_record(record: dict[str, Any], *, day: Any, out_dir: Path | None = None) -> Path:
    """Persist one paired observation plus a ``latest.json`` pointer."""
    target = out_dir if out_dir is not None else AB_ARMS_DIR
    target.mkdir(parents=True, exist_ok=True)
    day_iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
    path = target / f"ab_arms_{day_iso}.json"
    _atomic_write_json(path, record)
    _atomic_write_json(target / "latest.json", record)
    return path


def run_arm_b_shadow(
    *,
    quotes: list[dict[str, Any]],
    bias: float,
    top_n: int,
    news_scores: dict[str, float] | None,
    news_metrics: dict[str, dict[str, Any]] | None,
    sector_changes: dict[str, float] | None,
    symbol_sectors: dict[str, str] | None,
    vix_level: float | None,
    apply_regime: Any,
    regime_snapshot: Any,
    arm_a_rows: list[dict[str, Any]],
    day: Any,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Score the run a second time under Arm B and record the paired result.

    ``status`` is ``"ok"`` when a comparison was produced, or
    ``"arm_b_unavailable"`` when :mod:`open_prep.candidate_weights` has not
    produced a candidate set yet — the honest state, rather than a
    zero-difference row that would dilute the sample.

    Never raises: this is a shadow measurement and must not be able to fail a
    production run.
    """
    record: dict[str, Any] = {
        "schema_version": 1,
        "day": day.isoformat() if hasattr(day, "isoformat") else str(day),
        "regime": getattr(regime_snapshot, "regime", None),
        "status": "error",
    }
    try:
        if not arm_b_base_available():
            record["status"] = "arm_b_unavailable"
            record["reason"] = (
                f"weights_{CANDIDATE_LABEL}.json not present — run "
                f"`python -m open_prep.candidate_weights` (see STRATEGY_2026_Q3 §G2)"
            )
        else:
            # Same regime tilt as Arm A, so the base weights are the only difference.
            arm_b_base = load_weight_set(CANDIDATE_LABEL)
            save_weight_set(ARM_B_LABEL, apply_regime(arm_b_base, regime_snapshot))

            arm_b_rows, _ = rank_candidates_v2(
                quotes=quotes,
                bias=bias,
                top_n=max(int(top_n), 1),
                news_scores=news_scores,
                news_metrics=news_metrics,
                sector_changes=sector_changes,
                symbol_sectors=symbol_sectors,
                weight_label=ARM_B_LABEL,
                vix_level=vix_level,
            )
            record["status"] = "ok"
            record.update(compare_arms(arm_a_rows, arm_b_rows, top_n=top_n))
        write_ab_record(record, day=day, out_dir=out_dir)
    except Exception as exc:  # shadow path must never fail the production run
        logger.warning("G3 arm-B shadow failed: %s", exc, exc_info=True)
        record["status"] = "error"
        record["reason"] = str(exc)
    return record

"""Pooled OUT-OF-SAMPLE calibration summary for the measurement release gate.

Stage #5, PR 4. The release gate's ``calibrated_*`` metrics come from
``smc_core.scoring`` and are IN-SAMPLE (fit == eval on the same events), so its
absolute ceilings are a lenient one-sided guard (see the
``MeasurementShadowThresholds`` docstring in ``smc_integration.release_policy``).
This module produces the honest OOS counterpart from the SAME evidence run:

    MeasurementEvidence.family_events            (raw FamilyEvent dicts,
      -> extract_family_calibration_samples       real forward_timestamps)
      -> walk_forward_calibration                 (purged + embargoed folds)
      -> pool the measured families' OOS pairs
      -> pooled Brier / ECE                       (smc_core.scoring helpers)

Leak-safety is inherited, not re-implemented: the guard windows come from the
events' REAL forward bar timestamps (label end + embargo, ``family_returns``),
so session/overnight/weekend gaps can never shorten a purge window — this module
deliberately adds NO time arithmetic of its own.

Coverage is partial by construction: a family only contributes once its pooled
OOS count clears ``MIN_OOS_SAMPLES`` (40) on THIS corpus, so per-pair summaries
frequently stay honestly "not measured" (``measured=False``) — the advisory gate
checks in ``release_policy`` simply do not fire then.

Semantic caveat (same as the family calibrator): the OOS probability targets
``sign(return)`` — a WIN-RATE, not edge/PnL — and the pooled Brier/ECE grade
that win-rate calibration.
"""
from __future__ import annotations

from typing import Any

from governance.family_calibration import walk_forward_calibration
from governance.family_returns import extract_family_calibration_samples
from smc_core.scoring import brier_score, expected_calibration_error

#: Provenance tag stamped into the summary so gate reports can audit the source.
OOS_CALIBRATION_SOURCE_TAG = "walkforward_purged_embargo_time_pooled_v1"


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "measured": False,
        "reason": reason,
        "oos_calibrated_brier_score": None,
        "oos_calibrated_ece": None,
        "oos_calibration_n": 0,
        "families_measured": [],
        "source": OOS_CALIBRATION_SOURCE_TAG,
    }


def build_oos_calibration_summary(family_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled OOS calibration Brier/ECE over the measured families of one corpus.

    Runs the leak-free walk-forward family calibrator per family and pools the
    out-of-sample ``(probability, outcome)`` pairs of every family that cleared
    its OOS floor into ONE pooled Brier/ECE — the out-of-sample counterpart of
    the pooled in-sample ``calibrated_brier_score`` / ``calibrated_ece`` the
    release gate already reads. Families below the floor (or unfittable) simply
    do not contribute; when nothing is measured the summary says so
    (``measured=False``) instead of inventing a number.
    """
    if not family_events:
        return _unmeasured("no family events")
    samples = extract_family_calibration_samples(family_events)
    if not samples:
        return _unmeasured("no calibratable events (score + forward timestamps + realized return required)")

    pooled: list[tuple[float, bool]] = []
    families_measured: list[str] = []
    for family in sorted(samples):
        bucket = samples[family]
        block = walk_forward_calibration(
            bucket["scores"],
            bucket["returns"],
            bucket["anchor_ts"],
            bucket["guard_end_ts"],
        )
        if block is None:
            continue
        wf = block["walkforward"]
        pooled.extend(
            (float(p), bool(y)) for p, y in zip(wf["probabilities"], wf["outcomes"])
        )
        families_measured.append(family)

    if not pooled:
        return _unmeasured("no family cleared the OOS sample floor")

    return {
        "measured": True,
        "reason": None,
        "oos_calibrated_brier_score": round(brier_score(pooled), 6),
        "oos_calibrated_ece": round(expected_calibration_error(pooled), 6),
        "oos_calibration_n": len(pooled),
        "families_measured": families_measured,
        "source": OOS_CALIBRATION_SOURCE_TAG,
    }

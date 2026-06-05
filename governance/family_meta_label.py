"""ADR-0022 — meta-label A/B: does a JOINT multi-feature model lift resolution?

This is the slice the ADR-0019 harness explicitly deferred. ``family_feature_ab``
compares feature-ALONE vs score-ALONE; its own module docstring records that the
*incremental* question -- does a feature add resolution ON TOP of the score,
i.e. a multivariate / meta-label model -- "is deliberately out of scope here and
is the next slice." That next slice was never built, so every "saturated /
exhausted / axis-closed" verdict to date rests on single-feature-alone tests.

That is a strictly weaker claim than "no signal". The entire point of
meta-labeling (Lopez de Prado, AFML ch. 3 -- named as architecturally correct in
``docs/governance/resolution_feature_gap_analysis.md``) is that individually
weak, mutually orthogonal features can lift discrimination IN COMBINATION even
when none beats the geometry score alone. A single feature that is weaker than
the score can still correct the score's errors if its errors are uncorrelated.

This module answers the joint question, in shadow mode only, under the SAME
purged walk-forward, the SAME pairing guard, the SAME proper-scoring
no-regression guards, and the SAME pre-registered thresholds as ADR-0019:

- BASELINE arm: the v1 ``score`` alone, Platt-calibrated (identical to the
  ADR-0019 baseline, so deltas are directly comparable).
- CANDIDATE arm: a multivariate logistic over ``[score] + feature_keys`` jointly,
  fit with the exact same gradient-descent hyper-parameters and per-feature
  train-fold standardisation as :func:`governance.family_calibration._fit_logistic`.
  The score is column 0 of the joint matrix, so the joint model's information set
  is a strict superset of the baseline's: it can only help if the extra features
  carry orthogonal resolution.
- PAIRED on the same events over the same folds (a resolution delta reflects the
  added features, not a differing event sample).
- COMPLETE-CASE: an event enters a family's joint sample only if it carries the
  ``score`` AND ALL requested ``feature_keys`` (honest-missing is never
  zero-filled). The dropped count is reported so a thin joint sample is visible.

CAVEAT (documented honestly): this joint model is still LINEAR/additive. It
captures the orthogonal-error-combination core of meta-labeling but NOT
interaction effects (e.g. "OFI matters only inside the killzone AND at an
extreme premium/discount"). If the linear joint model still nulls, the next
slice is a non-linear learner (gradient boosting) or explicit interaction terms.
Nothing here calibrates, scores, or gates production.
"""
from __future__ import annotations

import math
from typing import Any, Literal, Mapping, TypedDict

from governance.family_calibration import (
    MIN_OOS_SAMPLES,
    MIN_TRAIN_SAMPLES,
    _quantile,
)
from governance.family_feature_ab import (
    ABS_ECE_CEILING,
    BRIER_REGRESSION_TOLERANCE,
    MIN_RESOLUTION_LIFT,
    resolution,
)
from governance.family_returns import (
    DEFAULT_COST_BPS,
    FamilyEvent,
    _event_bar_interval,
    get_family_config,
    realized_return,
)
from ml.metrics import brier_score, expected_calibration_error, roc_auc

# Mirror the ADR-0019 single-feature calibrator hyper-parameters EXACTLY
# (governance.family_calibration._fit_logistic) so the baseline arm here is
# bit-for-bit the ADR-0019 baseline and the multivariate fit differs only in
# dimensionality, never in optimisation.
_GD_ITERS = 500
_GD_LR = 0.1
_L2 = 0.01

META_SOURCE_TAG = "adr0022_meta_label_joint_purged_walkforward_resolution_ab_v1"


class _MultiLogisticModel:
    """Standardised multivariate logistic: ``sigmoid(sum_j w_j * z_j + b)``.

    ``z_j = (x_j - mean_j) / std_j`` with per-column train-fold statistics. A
    degenerate column (``std_j <= 0``) is neutralised (``z_j = 0``) rather than
    rejecting the whole fit, so one constant feature never kills the joint model.
    """

    __slots__ = ("weights", "bias", "means", "stds")

    def __init__(
        self,
        weights: list[float],
        bias: float,
        means: list[float],
        stds: list[float],
    ) -> None:
        self.weights = weights
        self.bias = bias
        self.means = means
        self.stds = stds


def _sigmoid(z: float) -> float:
    """Numerically stable logistic sigmoid (mirrors family_calibration)."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _standardise_columns(
    rows: list[list[float]],
) -> tuple[list[float], list[float]]:
    """Return per-column ``(means, stds)``; ``std = 0.0`` marks a dead column."""
    n = len(rows)
    n_cols = len(rows[0])
    means: list[float] = []
    stds: list[float] = []
    for j in range(n_cols):
        col = [rows[i][j] for i in range(n)]
        mean = sum(col) / n
        var = sum((c - mean) ** 2 for c in col) / n
        means.append(mean)
        stds.append(math.sqrt(var))
    return means, stds


def _z_row(row: list[float], means: list[float], stds: list[float]) -> list[float]:
    """Standardise one feature row; dead columns contribute 0."""
    return [
        (row[j] - means[j]) / stds[j] if stds[j] > 0.0 else 0.0
        for j in range(len(row))
    ]


def _fit_multi_logistic(
    rows: list[list[float]], y: list[float]
) -> _MultiLogisticModel | None:
    """Multivariate analogue of ``family_calibration._fit_logistic``.

    ``None`` when the sample is too thin, the labels are single-class, or every
    column is degenerate. Otherwise a full-batch L2-regularised gradient-descent
    fit with the SAME iters/lr/lambda as the single-feature calibrator.
    """
    n = len(rows)
    if n < MIN_TRAIN_SAMPLES:
        return None
    if min(y) == max(y):
        return None
    means, stds = _standardise_columns(rows)
    if all(s <= 0.0 for s in stds):
        return None
    z = [_z_row(row, means, stds) for row in rows]
    n_cols = len(means)
    weights = [0.0] * n_cols
    bias = 0.0
    for _ in range(_GD_ITERS):
        grad_w = [0.0] * n_cols
        grad_b = 0.0
        for zi, yi in zip(z, y, strict=True):
            dot = bias
            for j in range(n_cols):
                dot += weights[j] * zi[j]
            err = _sigmoid(dot) - yi
            for j in range(n_cols):
                grad_w[j] += err * zi[j]
            grad_b += err
        for j in range(n_cols):
            grad_w[j] = grad_w[j] / n + 2.0 * _L2 * weights[j]
            weights[j] -= _GD_LR * grad_w[j]
        bias -= _GD_LR * (grad_b / n)
    return _MultiLogisticModel(weights, bias, means, stds)


def _predict_multi(model: _MultiLogisticModel, rows: list[list[float]]) -> list[float]:
    """Calibrated probabilities for a feature matrix under ``model``."""
    out: list[float] = []
    for row in rows:
        zr = _z_row(row, model.means, model.stds)
        dot = model.bias
        for j in range(len(zr)):
            dot += model.weights[j] * zr[j]
        out.append(_sigmoid(dot))
    return out


def _fit_logistic_1d(x: list[float], y: list[float]) -> _MultiLogisticModel | None:
    """Score-alone baseline as a 1-column multivariate fit.

    Reuses the multivariate path with a single column so the baseline and
    candidate arms share identical optimisation; with one feature this is
    numerically the ADR-0019 single-feature Platt baseline.
    """
    return _fit_multi_logistic([[xi] for xi in x], y)


class MetaSamples(TypedDict):
    """Per-family PAIRED inputs for the joint meta-label A/B (parallel lists)."""

    scores: list[float]
    feature_matrix: list[list[float]]
    returns: list[float]
    anchor_ts: list[float]
    guard_end_ts: list[float]


class FamilyMetaResult(TypedDict):
    """Per-family joint meta-label measurement (shadow). All metrics are OOS."""

    n_oos: int
    n_features: int
    feature_keys: list[str]
    baseline_brier: float
    candidate_brier: float
    brier_delta: float
    baseline_resolution: float
    candidate_resolution: float
    resolution_delta: float
    baseline_ece: float
    candidate_ece: float
    baseline_auc: float
    candidate_auc: float
    resolution_improved: bool
    no_regression: bool
    verdict: str
    source: str


def walk_forward_meta_ab(
    scores: list[float],
    feature_matrix: list[list[float]],
    returns: list[float],
    anchor_ts: list[float],
    guard_end_ts: list[float],
    *,
    n_folds: int = 5,
    min_oos: int = MIN_OOS_SAMPLES,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, dict[str, list[float]]] | None:
    """Paired purged walk-forward: score-alone vs JOINT ``[score]+features``.

    Mirrors :func:`governance.family_calibration.walk_forward_ab` fold-for-fold
    (expanding folds, GAP-1 time-purge of any train event whose label window
    has not closed before the test fold opens, pairing guard so a fold is used
    only if BOTH arms fit). The only difference is the candidate arm: a
    multivariate logistic over ``[score] + feature columns`` instead of a single
    feature. Returns the pooled OOS ``{"baseline", "candidate"}`` arms, or
    ``None`` when fewer than ``min_oos`` shared OOS points can be assembled.

    ``label`` selects the graded outcome axis, mirroring
    :func:`governance.family_calibration.walk_forward_ab`:

    * ``"direction"`` (default): ``y = 1`` iff the net forward return is
      positive (sign / win-rate axis).
    * ``"magnitude"``: ``y = 1`` iff ``|return|`` is at or above the ``mag_q``
      quantile of ``|return|`` over the PURGED TRAINING events of that fold
      (move-size / volatility axis). The threshold is computed on train only and
      reused on the validation fold, so no future information leaks.
    """
    n = len(scores)
    if not (
        n
        == len(feature_matrix)
        == len(returns)
        == len(anchor_ts)
        == len(guard_end_ts)
    ):
        raise ValueError("walk_forward_meta_ab: input lists length mismatch")
    if n < min_oos or n < n_folds + 1:
        return None

    order = sorted(range(n), key=lambda i: anchor_ts[i])
    s = [scores[i] for i in order]
    fm = [feature_matrix[i] for i in order]
    a = [anchor_ts[i] for i in order]
    g = [guard_end_ts[i] for i in order]
    r = [returns[i] for i in order]
    # Direction labels are global (sign is leak-free); magnitude labels are
    # computed per fold from the train quantile inside the loop below.
    y = [1.0 if r[i] > 0.0 else 0.0 for i in range(n)]

    base_probs: list[float] = []
    cand_probs: list[float] = []
    oos_outcomes: list[float] = []

    val_size = max(1, n // (n_folds + 1))
    for k in range(n_folds):
        val_start = n - (n_folds - k) * val_size
        val_end = val_start + val_size
        if val_start <= 0:
            continue
        test_start_time = a[val_start]
        train_idx = [i for i in range(val_start) if g[i] < test_start_time]
        if len(train_idx) < MIN_TRAIN_SAMPLES:
            continue

        val_idx = list(range(val_start, min(val_end, n)))
        if not val_idx:
            continue

        if label == "magnitude":
            tau = _quantile([abs(r[i]) for i in train_idx], mag_q)
            train_y = [1.0 if abs(r[i]) >= tau else 0.0 for i in train_idx]
            val_y = [1.0 if abs(r[i]) >= tau else 0.0 for i in val_idx]
        else:
            train_y = [y[i] for i in train_idx]
            val_y = [y[i] for i in val_idx]

        base_model = _fit_logistic_1d([s[i] for i in train_idx], train_y)
        cand_model = _fit_multi_logistic(
            [[s[i]] + list(fm[i]) for i in train_idx], train_y
        )
        # Pairing guard: a fold contributes only if BOTH arms fit, so deltas are
        # never confounded by a differing fold sample between arms.
        if base_model is None or cand_model is None:
            continue

        base_probs.extend(_predict_multi(base_model, [[s[i]] for i in val_idx]))
        cand_probs.extend(
            _predict_multi(cand_model, [[s[i]] + list(fm[i]) for i in val_idx])
        )
        oos_outcomes.extend(val_y)

    if len(oos_outcomes) < min_oos:
        return None
    return {
        "baseline": {"probabilities": base_probs, "outcomes": oos_outcomes},
        "candidate": {"probabilities": cand_probs, "outcomes": oos_outcomes},
    }


def _arm_metrics(arm: dict[str, list[float]]) -> tuple[float, float, float, float]:
    """Return ``(brier, resolution, ece, auc)`` for one OOS arm."""
    probs = arm["probabilities"]
    outcomes = arm["outcomes"]
    return (
        brier_score(outcomes, probs),
        resolution(outcomes, probs),
        expected_calibration_error(outcomes, probs),
        roc_auc(outcomes, probs),
    )


def family_meta_ab(
    samples: MetaSamples,
    feature_keys: list[str],
    *,
    min_oos: int = MIN_OOS_SAMPLES,
    min_resolution_lift: float = MIN_RESOLUTION_LIFT,
    ece_ceiling: float = ABS_ECE_CEILING,
    brier_tolerance: float = BRIER_REGRESSION_TOLERANCE,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> FamilyMetaResult | None:
    """Run the paired joint meta-label A/B for one family.

    ``None`` when the joint sample is too thin to assemble ``min_oos`` shared
    OOS points. Verdict semantics match ADR-0019 exactly:
    ``candidate_lifts_resolution`` / ``no_lift`` / ``regresses_calibration``.
    ``label`` selects the graded axis (``"direction"`` sign vs ``"magnitude"``
    move-size at the ``mag_q`` train quantile); see :func:`walk_forward_meta_ab`.
    """
    ab = walk_forward_meta_ab(
        samples["scores"],
        samples["feature_matrix"],
        samples["returns"],
        samples["anchor_ts"],
        samples["guard_end_ts"],
        min_oos=min_oos,
        label=label,
        mag_q=mag_q,
    )
    if ab is None:
        return None

    base_brier, base_res, base_ece, base_auc = _arm_metrics(ab["baseline"])
    cand_brier, cand_res, cand_ece, cand_auc = _arm_metrics(ab["candidate"])

    resolution_delta = cand_res - base_res
    resolution_improved = resolution_delta >= min_resolution_lift
    no_regression = (
        cand_brier <= base_brier + brier_tolerance and cand_ece <= ece_ceiling
    )

    if not no_regression:
        verdict = "regresses_calibration"
    elif resolution_improved:
        verdict = "candidate_lifts_resolution"
    else:
        verdict = "no_lift"

    return FamilyMetaResult(
        n_oos=len(ab["baseline"]["outcomes"]),
        n_features=len(feature_keys),
        feature_keys=list(feature_keys),
        baseline_brier=base_brier,
        candidate_brier=cand_brier,
        brier_delta=cand_brier - base_brier,
        baseline_resolution=base_res,
        candidate_resolution=cand_res,
        resolution_delta=resolution_delta,
        baseline_ece=base_ece,
        candidate_ece=cand_ece,
        baseline_auc=base_auc,
        candidate_auc=cand_auc,
        resolution_improved=resolution_improved,
        no_regression=no_regression,
        verdict=verdict,
        source=META_SOURCE_TAG,
    )


def extract_family_meta_samples(
    events: list[FamilyEvent],
    *,
    feature_keys: list[str],
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, MetaSamples]:
    """Per family, collect PAIRED complete-case inputs for the joint A/B.

    Mirrors :func:`governance.family_returns.extract_family_ab_samples` but
    requires the ``score`` AND EVERY key in ``feature_keys`` to be present on an
    event (complete-case): honest-missing features are never zero-filled, so an
    event missing any requested feature is excluded rather than invented. The
    purge guard (``guard_end_ts``) is identical to the single-feature harness.
    """
    if not feature_keys:
        raise ValueError("extract_family_meta_samples: feature_keys is empty")
    out: dict[str, MetaSamples] = {}
    for event in events:
        if "score" not in event:
            continue
        if any(key not in event for key in feature_keys):
            continue
        forward_ts = event.get("forward_timestamps")
        if not forward_ts:
            continue
        ret = realized_return(event, cost_bps=cost_bps)
        if ret is None:
            continue
        family = event["family"]
        fts = [float(t) for t in forward_ts]
        embargo_bars = get_family_config(family).embargo_bars
        guard_end = fts[-1] + embargo_bars * _event_bar_interval(fts)
        event_view: Mapping[str, Any] = event
        bucket = out.setdefault(
            family,
            {
                "scores": [],
                "feature_matrix": [],
                "returns": [],
                "anchor_ts": [],
                "guard_end_ts": [],
            },
        )
        bucket["scores"].append(float(event_view["score"]))
        bucket["feature_matrix"].append(
            [float(event_view[key]) for key in feature_keys]
        )
        bucket["returns"].append(ret)
        bucket["anchor_ts"].append(float(event["anchor_ts"]))
        bucket["guard_end_ts"].append(guard_end)
    return out


def family_meta_ab_report(
    meta_samples: dict[str, MetaSamples],
    feature_keys: list[str],
    *,
    min_oos: int = MIN_OOS_SAMPLES,
    min_resolution_lift: float = MIN_RESOLUTION_LIFT,
    ece_ceiling: float = ABS_ECE_CEILING,
    brier_tolerance: float = BRIER_REGRESSION_TOLERANCE,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, FamilyMetaResult]:
    """Run the joint meta-label A/B for every measurable family.

    Families whose paired complete-case sample is too thin are omitted (their
    ``family_meta_ab`` returns ``None``), so the report only carries families
    that produced a real out-of-sample verdict. ``label``/``mag_q`` select the
    graded axis and are threaded to every family unchanged.
    """
    out: dict[str, FamilyMetaResult] = {}
    for family, samples in meta_samples.items():
        result = family_meta_ab(
            samples,
            feature_keys,
            min_oos=min_oos,
            min_resolution_lift=min_resolution_lift,
            ece_ceiling=ece_ceiling,
            brier_tolerance=brier_tolerance,
            label=label,
            mag_q=mag_q,
        )
        if result is not None:
            out[family] = result
    return out


__all__ = [
    "META_SOURCE_TAG",
    "FamilyMetaResult",
    "MetaSamples",
    "extract_family_meta_samples",
    "family_meta_ab",
    "family_meta_ab_report",
    "walk_forward_meta_ab",
]

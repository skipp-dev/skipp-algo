"""EV-24 walk-forward calibration: raw per-family score -> probability.

This is the modelling core that turns the raw, uncalibrated geometry-strength
score (``governance.family_event_score``) into out-of-sample probabilities the
promotion gate can score with Brier / ECE. It is built to satisfy the four
gaps the senior-quant review (2026-06-01) flagged, so the resulting metric is a
*measurement*, not optimistically biased (i.e. fabricated) evidence:

GAP 1 (overlapping-label leakage, BLOCKER). ``touch_then_horizon_close`` labels
    span a forward horizon H. Neighbouring events whose forward windows cross
    the train/test boundary share bars -> leakage that a plain time split does
    not stop. We purge any training event whose *guard window* (label-window end
    PLUS the family embargo, both in wall-clock time) reaches into the test
    fold. The embargo is folded into ``guard_end_ts`` by the caller
    (``family_returns.extract_family_calibration_samples``) using each event's
    own bar spacing, so this module only checks ``guard_end_ts < test_start``.
    Ref: Lopez de Prado, Advances in Financial Machine Learning (2018), ch. 7.

GAP 2 (win-rate != edge). The calibration target is ``sign(return)`` -- the
    probability of a *profitable* outcome. That is a WIN-RATE, not an expected
    value: E[R] = p*mu_win - (1-p)*mu_loss, so a well-calibrated sign model says
    nothing about PnL. Brier/ECE here are therefore a SECONDARY DIAGNOSTIC; the
    magnitude-aware gates (PSR, MinTRL, FDR) remain the primary edge test. This
    is asserted in the provenance tag and the gate docs, not just here.
    Ref: Lopez de Prado (2018), ch. 3 (meta-labeling: accuracy != PnL).

GAP 3 / GAP 4 (small-sample instability). ECE is biased and binning-dependent,
    and the Brier sampling distribution under serial dependence is wide at the
    few-hundred-sample scale typical here. We therefore enforce a MIN-SAMPLE
    GUARD: below ``MIN_OOS_SAMPLES`` pooled out-of-sample points we emit NO
    calibration block at all, leaving the family honestly "not yet measured"
    rather than shipping a noisy Brier/ECE. The rigorous block-bootstrap CI on
    the Brier (gate on the CI upper bound) is a documented follow-up in the gate
    layer; this module supplies the clean measurement and the sample count.
    Ref: Wilks (2010), QJRMS; Kumar/Liang/Ma (2019), NeurIPS; Bailey & Lopez de
    Prado (2012).

Calibrator. A 2-parameter logistic (Platt) on the standardised raw score,
    fit by gradient descent with a small L2 term. Platt (vs isotonic) is the
    robust choice at small n (Niculescu-Mizil & Caruana 2005; Guo et al. 2017).
    The slope sign is NOT hard-coded: the fit absorbs the score's direction; a
    non-informative score simply yields a flat, high-Brier mapping -- which is
    the honest outcome, never patched to look better.
"""

from __future__ import annotations

import math
from typing import Any

# Pooled out-of-sample sample-count guard (GAP 3/4). Below this we refuse to
# emit a Brier/ECE and the family stays "not yet measured". Conservative but
# adjustable; the block-bootstrap CI gate is the stricter deferred follow-up.
MIN_OOS_SAMPLES = 40

# Minimum purged-train events required to fit the 2-parameter Platt model on a
# fold. Folds below this are skipped (their test points get no probability).
MIN_TRAIN_SAMPLES = 20

# Provenance tags recorded so the audit trail explains the OOS guarantee.
CALIBRATOR_TAG = "platt_logistic_standardised_v1"
FOLD_SCHEME_TAG = "walkforward_purged_embargo_time"
TARGET_TAG = "sign_return_secondary_diagnostic"  # GAP 2: win-rate, not edge.

# EV-25 / C8 live-incubation surrogate (ADR-0017). In an offline backtest there
# is no real live trading feed, so the most recent chronological slice of the
# pooled walk-forward OOS pairs is DECLARED as a "live" proxy and the older
# remainder is the walk-forward reference. This makes ``live_vs_wf_ratio`` an
# honest recent-vs-historical OOS calibration-drift measure (a coarse 1.5x
# alarm, NOT a precise threshold -- the tail is small, so the live Brier has
# wide sampling error). A true live feed supersedes the surrogate when one
# exists. The split is emitted only when both partitions stay adequately
# powered; otherwise the family keeps the full pooled block and ``live_brier``
# stays honestly "not yet measured".
LIVE_TAIL_MIN_SAMPLES = 20
LIVE_SOURCE_TAG = "ev25_walkforward_oos_recent_tail_v1"

# EV-26 / C10.1 split-conformal coverage (ADR-0018). The pooled walk-forward
# OOS pairs are an independent view of the SAME chronological pool used for the
# live surrogate: the earlier half calibrates the split-conformal conformity
# quantile (Vovk) and the held-out later half measures the empirical marginal
# coverage against the 1-alpha guarantee. ``CONFORMAL_ALPHA = 0.1`` targets 90%
# coverage (matches the producer/ml.calibration.conformal default); a 50/50
# chronological split keeps both sides adequately powered. Honest by design:
# a low-resolution score yields WIDE prediction sets, so high coverage is the
# expected, non-flattering outcome -- coverage measures calibration of the set,
# NOT discrimination. Emitted only when both sides clear ``CONFORMAL_MIN_SIDE``;
# otherwise no block and ``conformal_coverage`` stays "not yet measured".
CONFORMAL_ALPHA = 0.1
CONFORMAL_CALIBRATION_FRACTION = 0.5
CONFORMAL_MIN_SIDE = MIN_OOS_SAMPLES
CONFORMAL_SOURCE_TAG = "ev26_walkforward_oos_split_conformal_v1"

# C9 PSI-trend window construction (EV#6). The reference distribution is a
# FIXED calibrator fit on the earliest chronological block; the monitoring
# windows are successive chronological slices scored through that SAME fixed
# lens, so the resulting PSI series isolates SCORE-POPULATION drift from
# per-fold calibrator-refit drift. Below these guards we emit no block and the
# family stays honestly "not yet measured".
PSI_TREND_MIN_WINDOWS = 2
PSI_TREND_MAX_WINDOWS = 4
PSI_TREND_MIN_WINDOW_SAMPLES = 10
PSI_TREND_SOURCE_TAG = "ev24_fixed_reference_calibrator_chronological_windows_v1"

_GD_ITERS = 500
_GD_LR = 0.1
_L2 = 0.01


class _LogisticModel:
    """Fitted ``sigmoid(a * (x - mean) / std + b)``."""

    __slots__ = ("a", "b", "mean", "std")

    def __init__(self, a: float, b: float, mean: float, std: float) -> None:
        self.a = a
        self.b = b
        self.mean = mean
        self.std = std


def _sigmoid(z: float) -> float:
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _fit_logistic(x: list[float], y: list[float]) -> _LogisticModel | None:
    """Fit a standardised 2-parameter logistic. ``None`` if unfittable.

    Returns ``None`` when there are too few points, a single outcome class, or
    a degenerate (zero-variance) feature -- in every such case there is no
    signal to calibrate and emitting a model would be fabrication.
    """
    n = len(x)
    if n < MIN_TRAIN_SAMPLES:
        return None
    if min(y) == max(y):  # single class -> nothing to separate
        return None
    mean = sum(x) / n
    var = sum((xi - mean) ** 2 for xi in x) / n
    std = math.sqrt(var)
    if std <= 0.0:  # degenerate feature
        return None

    z = [(xi - mean) / std for xi in x]
    a = 0.0
    b = 0.0
    for _ in range(_GD_ITERS):
        grad_a = 0.0
        grad_b = 0.0
        for zi, yi in zip(z, y, strict=True):
            p = _sigmoid(a * zi + b)
            grad_a += (p - yi) * zi
            grad_b += p - yi
        grad_a = grad_a / n + 2.0 * _L2 * a
        grad_b = grad_b / n
        a -= _GD_LR * grad_a
        b -= _GD_LR * grad_b
    return _LogisticModel(a=a, b=b, mean=mean, std=std)


def _predict(model: _LogisticModel, x: list[float]) -> list[float]:
    return [_sigmoid(model.a * ((xi - model.mean) / model.std) + model.b) for xi in x]


def walk_forward_calibration(
    scores: list[float],
    returns: list[float],
    anchor_ts: list[float],
    guard_end_ts: list[float],
    *,
    n_folds: int = 5,
    min_oos: int = MIN_OOS_SAMPLES,
) -> dict[str, dict[str, list[float]]] | None:
    """Walk-forward Platt calibration -> a ``{"walkforward": {...}}`` block.

    Sorts the per-family samples by ``anchor_ts``, builds ``n_folds`` expanding
    walk-forward folds, and for each fold fits the Platt calibrator on the
    PURGED training events (those whose ``guard_end_ts`` resolves strictly
    before the test fold begins -- GAP 1) and predicts the test events. The
    pooled out-of-sample ``(probability, outcome)`` pairs are returned in the
    exact shape ``build_family_metrics._binary_calibration_pairs`` validates:
    ``{"walkforward": {"probabilities": [...], "outcomes": [...]}}`` where
    ``outcome = 1.0`` iff the realized return is positive.

    Returns ``None`` (no block -> family stays "not yet measured") when the
    pooled out-of-sample count is below ``min_oos`` (GAP 3/4), when no fold
    could be fit, or when inputs are too short.
    """
    n = len(scores)
    if not (n == len(returns) == len(anchor_ts) == len(guard_end_ts)):
        raise ValueError("walk_forward_calibration: input lists length mismatch")
    if n < min_oos or n < n_folds + 1:
        return None

    order = sorted(range(n), key=lambda i: anchor_ts[i])
    s = [scores[i] for i in order]
    a = [anchor_ts[i] for i in order]
    g = [guard_end_ts[i] for i in order]
    y = [1.0 if returns[i] > 0.0 else 0.0 for i in order]

    val_size = max(1, n // (n_folds + 1))
    oos_probs: list[float] = []
    oos_outcomes: list[float] = []
    for k in range(n_folds):
        val_start = n - (n_folds - k) * val_size
        val_end = val_start + val_size
        if val_start <= 0:
            continue
        test_start_time = a[val_start]
        # GAP 1 purge: keep only training events whose guard window (label end
        # + embargo, in time) resolves strictly before the test fold starts.
        train_idx = [i for i in range(val_start) if g[i] < test_start_time]
        if len(train_idx) < MIN_TRAIN_SAMPLES:
            continue
        model = _fit_logistic([s[i] for i in train_idx], [y[i] for i in train_idx])
        if model is None:
            continue
        val_x = [s[i] for i in range(val_start, val_end)]
        oos_probs.extend(_predict(model, val_x))
        oos_outcomes.extend(y[i] for i in range(val_start, val_end))

    if len(oos_probs) < min_oos:
        return None
    return {"walkforward": {"probabilities": oos_probs, "outcomes": oos_outcomes}}


def walk_forward_ab(
    baseline: list[float],
    candidate: list[float],
    returns: list[float],
    anchor_ts: list[float],
    guard_end_ts: list[float],
    *,
    n_folds: int = 5,
    min_oos: int = MIN_OOS_SAMPLES,
) -> dict[str, dict[str, list[float]]] | None:
    """PAIRED purged walk-forward A/B: two arms over an identical fold set.

    Mirrors :func:`walk_forward_calibration` exactly -- same chronological sort,
    same expanding folds, same GAP-1 purge (train events whose ``guard_end_ts``
    resolves strictly before the test fold starts) -- but Platt-calibrates BOTH
    a ``baseline`` series (the v1 score) and a ``candidate`` series (the v2
    feature) on the SAME purged training events and predicts the SAME test
    events. A fold contributes its out-of-sample points only when BOTH arms fit
    on that fold, so the two arms share an identical OOS index set and their
    Brier / resolution are directly comparable (an unpaired comparison would
    confound the feature's effect with a differing event sample).

    Returns ``{"baseline": {"probabilities", "outcomes"}, "candidate": {...}}``
    with identical ``outcomes`` in both arms, or ``None`` (family stays "not yet
    measured") when the shared out-of-sample count is below ``min_oos``, no fold
    admits both arms, or inputs are too short. This is a SHADOW measurement: it
    calibrates nothing into the gate and changes no score.
    """
    n = len(baseline)
    if not (
        n
        == len(candidate)
        == len(returns)
        == len(anchor_ts)
        == len(guard_end_ts)
    ):
        raise ValueError("walk_forward_ab: input lists length mismatch")
    if n < min_oos or n < n_folds + 1:
        return None

    order = sorted(range(n), key=lambda i: anchor_ts[i])
    base = [baseline[i] for i in order]
    cand = [candidate[i] for i in order]
    a = [anchor_ts[i] for i in order]
    g = [guard_end_ts[i] for i in order]
    y = [1.0 if returns[i] > 0.0 else 0.0 for i in order]

    val_size = max(1, n // (n_folds + 1))
    base_probs: list[float] = []
    cand_probs: list[float] = []
    oos_outcomes: list[float] = []
    for k in range(n_folds):
        val_start = n - (n_folds - k) * val_size
        val_end = val_start + val_size
        if val_start <= 0:
            continue
        test_start_time = a[val_start]
        train_idx = [i for i in range(val_start) if g[i] < test_start_time]
        if len(train_idx) < MIN_TRAIN_SAMPLES:
            continue
        train_y = [y[i] for i in train_idx]
        base_model = _fit_logistic([base[i] for i in train_idx], train_y)
        cand_model = _fit_logistic([cand[i] for i in train_idx], train_y)
        # Pairing guard: only emit the fold when BOTH arms calibrate, so the
        # two OOS index sets stay identical and the delta is unconfounded.
        if base_model is None or cand_model is None:
            continue
        val_range = range(val_start, val_end)
        base_probs.extend(_predict(base_model, [base[i] for i in val_range]))
        cand_probs.extend(_predict(cand_model, [cand[i] for i in val_range]))
        oos_outcomes.extend(y[i] for i in val_range)

    if len(oos_outcomes) < min_oos:
        return None
    return {
        "baseline": {"probabilities": base_probs, "outcomes": oos_outcomes},
        "candidate": {"probabilities": cand_probs, "outcomes": oos_outcomes},
    }


def partition_live_tail(
    block: dict[str, dict[str, list[float]]],
    *,
    live_min: int = LIVE_TAIL_MIN_SAMPLES,
    wf_min: int = MIN_OOS_SAMPLES,
) -> dict[str, dict[str, list[float]]] | None:
    """Split a pooled walk-forward block into ``{walkforward, live}`` (ADR-0017).

    The pooled OOS pairs produced by :func:`walk_forward_calibration` are in
    CHRONOLOGICAL order (earliest fold first, latest fold last), so the last
    ``live_min`` pairs are the most recent out-of-sample window. They are
    DECLARED as the live-incubation surrogate (there is no real live feed in an
    offline backtest); the older remainder is the walk-forward reference.

    Returns the two-block dict only when the pool is large enough to leave BOTH
    partitions adequately powered (``len >= live_min + wf_min``). Otherwise
    returns ``None`` -- the caller then keeps the full pooled block and
    ``live_brier`` stays honestly "not yet measured" rather than splitting a
    small sample into two noisy halves. The live tail is intentionally small,
    so the resulting ``live_vs_wf_ratio`` is a coarse drift alarm, not a precise
    threshold (see module-level ``LIVE_SOURCE_TAG`` note).
    """
    wf = block.get("walkforward")
    if wf is None:
        return None
    probs = wf["probabilities"]
    outcomes = wf["outcomes"]
    n = len(probs)
    if n < live_min + wf_min:
        return None
    cut = n - live_min
    return {
        "walkforward": {
            "probabilities": probs[:cut],
            "outcomes": outcomes[:cut],
        },
        "live": {
            "probabilities": probs[cut:],
            "outcomes": outcomes[cut:],
        },
    }


def partition_conformal(
    block: dict[str, dict[str, list[float]]],
    *,
    alpha: float = CONFORMAL_ALPHA,
    cal_fraction: float = CONFORMAL_CALIBRATION_FRACTION,
    min_side: int = CONFORMAL_MIN_SIDE,
) -> dict[str, Any] | None:
    """Split a pooled walk-forward block into a split-conformal block (ADR-0018).

    The pooled OOS pairs from :func:`walk_forward_calibration` are chronological,
    so the earlier ``cal_fraction`` slice calibrates the split-conformal (Vovk)
    conformity quantile and the held-out later slice measures empirical marginal
    coverage against the ``1 - alpha`` guarantee. This is an INDEPENDENT view of
    the same OOS pool used by :func:`partition_live_tail` -- coverage and live
    Brier-drift are different diagnostics on the same evidence.

    Returns the producer-shaped block
    ``{"alpha", "calibration": {...}, "test": {...}}`` only when BOTH sides
    clear ``min_side`` (adequately powered calibration quantile and coverage
    estimate). Otherwise returns ``None`` so the caller omits the block and the
    family's ``conformal_coverage`` stays honestly "not yet measured".
    """
    wf = block.get("walkforward")
    if wf is None:
        return None
    probs = wf["probabilities"]
    outcomes = wf["outcomes"]
    n = len(probs)
    cut = int(n * cal_fraction)
    if cut < min_side or (n - cut) < min_side:
        return None
    return {
        "alpha": alpha,
        "calibration": {
            "probabilities": probs[:cut],
            "outcomes": outcomes[:cut],
        },
        "test": {
            "probabilities": probs[cut:],
            "outcomes": outcomes[cut:],
        },
    }


def walk_forward_psi_trend(
    scores: list[float],
    returns: list[float],
    anchor_ts: list[float],
    *,
    max_windows: int = PSI_TREND_MAX_WINDOWS,
    min_window: int = PSI_TREND_MIN_WINDOW_SAMPLES,
    min_train: int = MIN_TRAIN_SAMPLES,
) -> dict[str, Any] | None:
    """Build a C9 ``psi_trend`` block from the EV-24 score series (EV#6).

    Population-stability-over-time measured through a FIXED reference lens: a
    single Platt calibrator is fit on the earliest chronological block and
    applied BOTH to that block (the reference probability distribution) and to
    each successive chronological monitoring window of later scores. Because
    every window is scored through the *same* fixed model, the resulting PSI
    series reflects drift in the SCORE POPULATION, not per-fold calibrator
    refitting -- the honest decomposition for a drift watchdog.

    The series is partitioned into ``k + 1`` equal chronological segments (one
    reference + ``k`` monitoring windows) sorted by ``anchor_ts``; ``k`` is the
    largest value in ``[PSI_TREND_MIN_WINDOWS, max_windows]`` for which every
    segment still holds at least ``max(min_train, min_window,
    MIN_TRAIN_SAMPLES)`` events. The reference fit itself always enforces
    ``MIN_TRAIN_SAMPLES`` (in :func:`_fit_logistic`), so the guard includes that
    floor to avoid accepting segments the fitter would then reject. The last
    window absorbs any integer-division remainder.

    Returns the ``{"reference_probabilities", "windows"}`` shape that
    :func:`build_family_metrics._psi_trend_slice` validates, or ``None`` (family
    stays "not yet measured") when there are too few events to fit the reference
    lens or to form ``PSI_TREND_MIN_WINDOWS`` non-trivial windows, or when the
    reference block carries a single outcome class / degenerate score (the
    calibrator refuses to fabricate a mapping). The reference lens is fit on
    ``sign(return)`` -- the same WIN-RATE target as EV-24 calibration (GAP 2: a
    diagnostic, not an edge proof).
    """
    n = len(scores)
    if not (n == len(returns) == len(anchor_ts)):
        raise ValueError("walk_forward_psi_trend: input lists length mismatch")

    # Honour the fitter's own floor: _fit_logistic always rejects < MIN_TRAIN_SAMPLES,
    # so a smaller min_train must not let window-selection accept doomed segments.
    min_segment = max(min_train, min_window, MIN_TRAIN_SAMPLES)
    k = 0
    for cand in range(max_windows, PSI_TREND_MIN_WINDOWS - 1, -1):
        if n // (cand + 1) >= min_segment:
            k = cand
            break
    if k < PSI_TREND_MIN_WINDOWS:
        return None

    order = sorted(range(n), key=lambda i: anchor_ts[i])
    s = [scores[i] for i in order]
    y = [1.0 if returns[i] > 0.0 else 0.0 for i in order]

    seg = n // (k + 1)
    model = _fit_logistic(s[:seg], y[:seg])
    if model is None:
        return None

    reference_probabilities = _predict(model, s[:seg])
    windows: list[list[float]] = []
    for w in range(k):
        start = seg * (w + 1)
        end = seg * (w + 2) if w < k - 1 else n  # last window absorbs remainder
        windows.append(_predict(model, s[start:end]))

    return {"reference_probabilities": reference_probabilities, "windows": windows}


__all__ = [
    "CALIBRATOR_TAG",
    "CONFORMAL_ALPHA",
    "CONFORMAL_CALIBRATION_FRACTION",
    "CONFORMAL_MIN_SIDE",
    "CONFORMAL_SOURCE_TAG",
    "FOLD_SCHEME_TAG",
    "LIVE_SOURCE_TAG",
    "LIVE_TAIL_MIN_SAMPLES",
    "MIN_OOS_SAMPLES",
    "MIN_TRAIN_SAMPLES",
    "PSI_TREND_MAX_WINDOWS",
    "PSI_TREND_MIN_WINDOWS",
    "PSI_TREND_MIN_WINDOW_SAMPLES",
    "PSI_TREND_SOURCE_TAG",
    "TARGET_TAG",
    "partition_conformal",
    "partition_live_tail",
    "walk_forward_ab",
    "walk_forward_calibration",
    "walk_forward_psi_trend",
]

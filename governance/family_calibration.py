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


__all__ = [
    "CALIBRATOR_TAG",
    "FOLD_SCHEME_TAG",
    "MIN_OOS_SAMPLES",
    "MIN_TRAIN_SAMPLES",
    "TARGET_TAG",
    "walk_forward_calibration",
]

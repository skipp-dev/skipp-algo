"""Sample-uniqueness & effective-sample-size primitives (Lopez de Prado ch.4).

The EV-24 calibrator (:mod:`governance.family_calibration`) fits its 2-parameter
Platt model by gradient descent that treats every event as an INDEPENDENT
observation. That assumption is false here: the ``touch_then_horizon_close``
label of an event spans a forward horizon H, so neighbouring events whose label
windows overlap *share forward bars* and therefore share information. Counting
them as independent overstates the evidence -- the same bias the senior-quant
review flagged as GAP 3/4 (small-sample instability), seen from the *redundancy*
side rather than the *count* side.

There are two distinct overlap problems, and they need two distinct fixes:

  * CROSS-fold leakage (GAP 1) -- an event whose label window crosses the
    train/test boundary leaks the test outcome into training. That is already
    handled by the time-based purge+embargo in
    :func:`governance.family_calibration.walk_forward_calibration`.

  * WITHIN-fold redundancy (this module) -- two training events whose label
    windows overlap are not two independent data points. The purge does NOT
    address this; it only stops boundary crossing. The correct treatment is to
    *down-weight* overlapping labels by their average uniqueness so the fit and
    the sample-count guard reflect the real, smaller information content.

This module supplies the measurement primitives for that second fix:

  * :func:`average_uniqueness` -- per Lopez de Prado, Advances in Financial
    Machine Learning (2018), ch. 4: the average over a label's lifespan of the
    reciprocal concurrency ``1 / c(t)``, where ``c(t)`` is the number of label
    spans covering time ``t``. An isolated label scores 1.0; two fully
    overlapping labels score 0.5 each. Computed exactly with a pure-stdlib
    sweep over the label-boundary breakpoints (no bar grid, no numpy -- ADR-0005
    pure-stdlib measurement runtime).

  * :func:`time_decay` -- ch. 4 piecewise-linear time decay applied to the
    cumulative uniqueness, so older, less-unique observations fade smoothly to a
    configurable floor weight while the most recent observation keeps weight 1.

  * :func:`effective_sample_size` -- the Kish effective sample size
    ``(sum w)^2 / sum(w^2)``, the honest n the weighted evidence is worth. This
    is the number a future ESS-based guard should compare against
    ``MIN_OOS_SAMPLES`` instead of the raw count, which silently overcounts
    redundant overlapping events.

MEASUREMENT GROUNDWORK ONLY. Like
:func:`governance.family_returns.extract_family_feature_samples`, this module
calibrates, scores and gates NOTHING. It only computes weights from label
spans. Wiring these weights into the Platt fit (a weighted gradient descent) and
swapping the raw-count guard for an ESS guard each CHANGE a gate-relevant
measurement and are therefore deferred to a pre-registered A/B (does
uniqueness-weighting lift resolution / tighten Brier?), in the ADR-0019 style --
never bolted on silently. The primitives here are deterministic arithmetic on
the spans the caller supplies; they invent no data and refuse degenerate input
rather than fabricating a weight.
"""

from __future__ import annotations

from collections.abc import Sequence

# Provenance tag recorded by any downstream consumer so the audit trail names
# the exact weighting scheme (average uniqueness x linear time decay, graded by
# Kish ESS). Bump the suffix on any change to the weight definition.
WEIGHTS_TAG = "avg_uniqueness_timedecay_kish_v1"


def average_uniqueness(
    starts: Sequence[float], ends: Sequence[float]
) -> list[float]:
    """Average uniqueness per label from overlapping ``[start, end]`` spans.

    For each label ``i`` with span ``[starts[i], ends[i]]`` returns

        ``avg_uniqueness_i = (1 / len_i) * integral over [start_i, end_i] of
        1 / c(t) dt``

    where ``c(t)`` is the number of spans covering time ``t`` and
    ``len_i = ends[i] - starts[i]``. This is the exact continuous-interval form
    of Lopez de Prado (2018), ch. 4: an isolated label scores ``1.0``; ``m``
    labels sharing the same span each score ``1 / m``.

    Computed by a sweep over the sorted set of all span boundaries: on each
    elementary sub-interval the concurrency is constant, so the integral is a
    finite sum of ``dt / c`` shares. Pure stdlib, no bar grid, no numpy.

    Raises ``ValueError`` on length mismatch or any non-positive lifespan
    (``ends[i] <= starts[i]``) -- a degenerate span is a data bug, not something
    to silently assign a weight to.
    """
    n = len(starts)
    if n != len(ends):
        raise ValueError("average_uniqueness: starts/ends length mismatch")
    if n == 0:
        return []
    for i in range(n):
        if not ends[i] > starts[i]:
            raise ValueError(
                "average_uniqueness: non-positive label lifespan at index "
                f"{i} (start={starts[i]}, end={ends[i]})"
            )

    breakpoints = sorted(set(starts) | set(ends))
    integral = [0.0] * n
    for k in range(len(breakpoints) - 1):
        t_lo = breakpoints[k]
        t_hi = breakpoints[k + 1]
        dt = t_hi - t_lo
        if dt <= 0.0:
            continue
        covering = [
            i for i in range(n) if starts[i] <= t_lo and ends[i] >= t_hi
        ]
        concurrency = len(covering)
        if concurrency == 0:
            continue
        share = dt / concurrency
        for i in covering:
            integral[i] += share

    return [integral[i] / (ends[i] - starts[i]) for i in range(n)]


def time_decay(
    anchor_ts: Sequence[float],
    uniqueness: Sequence[float],
    *,
    last_weight: float = 1.0,
) -> list[float]:
    """Piecewise-linear time-decay factors on cumulative uniqueness (ch. 4).

    Orders observations oldest-first by ``anchor_ts``, accumulates their
    uniqueness, and maps each to a decay factor that is ``1.0`` for the most
    recent observation and tends to ``last_weight`` for the oldest:

        ``factor_i = last_weight + (1 - last_weight) * cum_i / total``

    where ``cum_i`` is the cumulative uniqueness up to and including ``i`` and
    ``total`` is the full sum. Decaying on cumulative *uniqueness* (not raw
    index) is the Lopez de Prado (2018), ch. 4 form: time is measured in units
    of new information, so a burst of redundant events does not age the series
    as fast as a run of unique ones. ``last_weight = 1.0`` disables decay (all
    factors ``1.0``).

    Raises ``ValueError`` on length mismatch, ``last_weight`` outside
    ``[0, 1]``, or a non-positive total uniqueness.
    """
    n = len(anchor_ts)
    if n != len(uniqueness):
        raise ValueError("time_decay: anchor_ts/uniqueness length mismatch")
    if not 0.0 <= last_weight <= 1.0:
        raise ValueError("time_decay: last_weight must be in [0, 1]")
    if n == 0:
        return []

    order = sorted(range(n), key=lambda i: anchor_ts[i])
    cumulative = [0.0] * n
    running = 0.0
    for i in order:
        running += uniqueness[i]
        cumulative[i] = running
    total = running
    if total <= 0.0:
        raise ValueError("time_decay: non-positive total uniqueness")

    return [
        last_weight + (1.0 - last_weight) * (cumulative[i] / total)
        for i in range(n)
    ]


def sample_weights(
    starts: Sequence[float],
    ends: Sequence[float],
    anchor_ts: Sequence[float],
    *,
    time_decay_last: float = 1.0,
    normalise: bool = True,
) -> list[float]:
    """Combined per-event weights: average uniqueness x time decay.

    Multiplies each event's :func:`average_uniqueness` by its
    :func:`time_decay` factor. When ``normalise`` is true the weights are
    rescaled to mean ``1.0`` so that dropping them into an otherwise-unchanged
    gradient descent leaves the learning-rate / L2 scale untouched (only the
    relative emphasis across events changes, not the overall step size).

    Raises ``ValueError`` on length mismatch or a non-positive weight sum.
    """
    n = len(starts)
    if not (n == len(ends) == len(anchor_ts)):
        raise ValueError("sample_weights: input lists length mismatch")
    uniqueness = average_uniqueness(starts, ends)
    decay = time_decay(anchor_ts, uniqueness, last_weight=time_decay_last)
    weights = [u * d for u, d in zip(uniqueness, decay, strict=True)]
    if normalise:
        total = sum(weights)
        if total <= 0.0:
            raise ValueError("sample_weights: non-positive weight sum")
        scale = n / total
        weights = [w * scale for w in weights]
    return weights


def effective_sample_size(weights: Sequence[float]) -> float:
    """Kish effective sample size ``(sum w)^2 / sum(w^2)``.

    The honest n a weighted sample is worth: equal weights give ``ESS = n``;
    concentrating weight on a few observations drives it below ``n``. This is
    the count a future guard should compare against ``MIN_OOS_SAMPLES`` instead
    of the raw event count, which overstates the evidence when overlapping
    labels are down-weighted by uniqueness.

    Returns ``0.0`` for an empty sample or all-zero weights. Raises
    ``ValueError`` on any negative weight.
    """
    if not weights:
        return 0.0
    total = 0.0
    total_sq = 0.0
    for w in weights:
        if w < 0.0:
            raise ValueError("effective_sample_size: negative weight")
        total += w
        total_sq += w * w
    if total_sq <= 0.0:
        return 0.0
    return (total * total) / total_sq

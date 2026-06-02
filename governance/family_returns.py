"""EV-06b — per-family realized-return extractor.

The X2 ``PromotionGate`` PSR/MinTRL metrics need a real-valued *return
series* per :class:`~governance.types.EventFamily`. The existing SMC
event pipeline, however, only produces **binary mitigation labels**
(``label_orderblock_mitigation`` / ``label_fvg_mitigation``: was the
zone touched before invalidation?) — a hit-rate, not a Sharpe. This
module is the missing bridge: it turns detected family events plus their
forward bars into a realized per-event return, grouped by family, in the
exact spec shape :func:`scripts.build_family_metrics.build_bundle`
consumes.

LOAD-BEARING ASSUMPTION — the trade definition (chosen autonomously,
pending review). Variant **A** (``touch_then_horizon_close``):

1. Entry at the zone midpoint on the first forward bar that *touches*
   the zone (long zones: a forward low enters ``[zone_low, zone_high]``;
   short zones: a forward high enters it — mirrors the label semantics).
2. Exit at the close ``family_outcome_horizon(family)`` bars after that
   touch (clamped to the last available bar), signed by direction.
3. Subtract a fixed round-turn cost (``DEFAULT_COST_BPS``).

This is the most conservative, fewest-degrees-of-freedom rule: no
target/stop optimisation, no best-fill, fixed costs — hard to flatter.
Untriggered setups (no touch) are **not trades** and are excluded, not
counted as zero (so the series is "returns *given* a triggered setup").
Variants B (triple-barrier) and C (signed next-bar) are intentionally
NOT implemented here; switching the rule must be an explicit, reviewed
code change, never a silent default.

It does NOT fabricate data: events and forward bars are injected by the
caller (from the real databento + SMC scoring pipeline). It only does
arithmetic on what it is given, and refuses lookahead.

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / story EV-06b.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from governance.family_calibration import (
    CALIBRATOR_TAG,
    FOLD_SCHEME_TAG,
    PSI_TREND_SOURCE_TAG,
    TARGET_TAG,
    walk_forward_calibration,
    walk_forward_psi_trend,
)
from governance.family_event_score import REGIME_SOURCE, SCORE_SOURCE
from governance.family_walkforward import family_outcome_horizon, get_family_config
from governance.types import EventFamily

# Fixed round-turn transaction cost (bps) subtracted from every realized
# return. 5 bps is a conservative large-cap incl.-slippage default; tune
# only with measured fill data. Configurable per call.
DEFAULT_COST_BPS = 5.0

# Tag recorded so downstream provenance can audit which trade definition
# produced a return series.
RETURN_RULE = "touch_then_horizon_close"

# Entry conventions. Two SMC event geometries need two rules:
#   - "retest_touch" (zone families OB/FVG): wait for price to retest the
#     zone, enter at the zone midpoint on first touch. This is variant A.
#   - "immediate" (level families BOS/SWEEP): the signal IS the anchor bar
#     (a break / a sweep already happened); enter at the event level price
#     at the anchor, no retest wait. Second load-bearing assumption.
EntryMode = Literal["retest_touch", "immediate"]

_BULLISH = {"UP", "BULL", "BULLISH", "LONG"}
_BEARISH = {"DOWN", "BEAR", "BEARISH", "SHORT"}


class FamilyEvent(TypedDict, total=False):
    """A detected SMC family event plus its forward bars.

    ``forward_*`` are the bars strictly AFTER the anchor (as produced by
    ``smc_integration.measurement_evidence._future_price_lists``).
    ``forward_timestamps`` is optional; when present it is leak-checked
    against ``anchor_ts``.

    Zone families (OB/FVG) supply ``zone_low``/``zone_high`` and use the
    default ``entry_mode="retest_touch"``. Level families (BOS/SWEEP)
    supply ``entry_price`` and ``entry_mode="immediate"``.
    """

    family: EventFamily
    direction: str
    entry_mode: EntryMode
    zone_low: float
    zone_high: float
    entry_price: float
    anchor_ts: float
    forward_highs: list[float]
    forward_lows: list[float]
    forward_closes: list[float]
    forward_timestamps: list[float]
    # Optional point-in-time RAW score (EV-24): a single ATR-normalised
    # geometry-strength feature attached by ``family_event_adapter`` (see
    # ``governance.family_event_score``). Uncalibrated and unsquashed -- the
    # walk-forward Platt calibrator maps it to a probability downstream. Absent
    # when trailing ATR could not be computed (event keeps no score, stays
    # "not yet measured"). Never invented.
    score: float
    # Optional point-in-time market regime label (EV#7): TRENDING / RANGING /
    # NEUTRAL, derived from the trailing closes ending at the anchor bar (see
    # ``governance.family_event_score.point_in_time_regime``). Absent when the
    # trailing window is too short or perfectly flat. Used to stratify realized
    # returns for the C5.1 ``regime_degraded`` gate check. Never invented.
    regime: str
    # Optional point-in-time order-flow feature (ADR-0019 v2 candidate): the
    # formation-bar volume over its trailing mean (see
    # ``governance.family_score_features_v2.relative_volume_at``). RECORDED
    # ONLY -- it is NOT a calibration input and does NOT feed the gate; it is
    # captured alongside outcomes so the pre-registered purged walk-forward A/B
    # (ADR-0019) can evaluate whether it lifts resolution before any wiring.
    # Absent when volume is missing or the trailing baseline is degenerate.
    # Never invented.
    relative_volume: float


def _direction_sign(direction: str) -> int:
    norm = (direction or "").upper()
    if norm in _BULLISH:
        return 1
    if norm in _BEARISH:
        return -1
    return 0


def _first_touch_index(
    direction_sign: int,
    zone_low: float,
    zone_high: float,
    forward_highs: list[float],
    forward_lows: list[float],
) -> int | None:
    """First forward-bar index whose price enters the zone.

    Long zone: a bar low dips into ``[zone_low, zone_high]``.
    Short zone: a bar high rises into ``[zone_low, zone_high]``.
    Mirrors the touch semantics of the mitigation label functions.
    """
    if direction_sign > 0:
        series = forward_lows
    elif direction_sign < 0:
        series = forward_highs
    else:
        return None
    for idx, price in enumerate(series):
        if zone_low <= price <= zone_high:
            return idx
    return None


def _first_invalidation_index(
    direction_sign: int,
    zone_low: float,
    zone_high: float,
    forward_closes: list[float],
    *,
    consecutive: int,
) -> int | None:
    """First forward-bar index at which the zone is invalidated by a close breach.

    Long zone: a close below ``zone_low`` breaches the setup; short zone: a
    close above ``zone_high``. ``consecutive`` breaching closes are required to
    invalidate (1 for order blocks, 2 for FVGs) — mirroring
    :func:`smc_core.scoring._zone_touch_before_invalidation` and
    :func:`smc_core.scoring.label_fvg_mitigation` exactly. For the two-close
    rule the returned index is the *first* of the two consecutive breaches,
    matching the label functions' ``invalid_idx = idx - 1`` convention.
    """
    if direction_sign == 0:
        return None
    streak = 0
    for idx, close in enumerate(forward_closes):
        breached = close < zone_low if direction_sign > 0 else close > zone_high
        if breached:
            streak += 1
            if streak >= consecutive:
                return idx - (consecutive - 1)
        else:
            streak = 0
    return None


def _assert_forward_after_anchor(event: FamilyEvent) -> None:
    """Reject forward bars timestamped at or before the anchor.

    Feeding pre-anchor bars as "future" would leak — fail loudly.
    """
    ts = event.get("forward_timestamps")
    if not ts:
        return
    anchor = float(event["anchor_ts"])
    bad = [t for t in ts if float(t) <= anchor]
    if bad:
        raise ValueError(
            f"forward_timestamps contains {len(bad)} value(s) at or before "
            f"anchor_ts {anchor!r}: lookahead leak refused"
        )


def realized_return(event: FamilyEvent, *, cost_bps: float = DEFAULT_COST_BPS) -> float | None:
    """Realized return for a single event.

    Dispatches on ``entry_mode`` (default ``"retest_touch"`` for zone
    families). Returns ``None`` when the setup did not trigger (no touch),
    or is degenerate (non-positive entry / no exit bar) — those are not
    trades and must not be counted as zero.
    """
    sign = _direction_sign(str(event.get("direction", "")))
    if sign == 0:
        return None

    _assert_forward_after_anchor(event)

    family = event["family"]
    closes = [float(x) for x in event.get("forward_closes", [])]
    horizon = family_outcome_horizon(family)
    mode: EntryMode = event.get("entry_mode", "retest_touch")

    if mode == "immediate":
        entry_price = float(event.get("entry_price", 0.0))
        if entry_price <= 0.0:
            return None
        # The break/sweep is the anchor bar; the first forward close is one
        # bar after the anchor, so the exit ``horizon`` bars later sits at
        # index ``horizon - 1`` (clamped to the last available close).
        if not closes:
            return None
        exit_idx = min(horizon - 1, len(closes) - 1)
        exit_price = closes[exit_idx]
        gross = sign * (exit_price - entry_price) / entry_price
        return gross - cost_bps / 1e4

    # Default: zone retest-touch (variant A).
    zone_low = float(event["zone_low"])
    zone_high = float(event["zone_high"])
    if zone_low <= 0.0 or zone_high <= 0.0 or zone_high < zone_low:
        return None

    highs = [float(x) for x in event.get("forward_highs", [])]
    lows = [float(x) for x in event.get("forward_lows", [])]

    touch_idx = _first_touch_index(sign, zone_low, zone_high, highs, lows)
    if touch_idx is None:
        return None

    # Variant-A fix: a retest touch that lands *after* the setup has already
    # been invalidated is not a tradable mitigation. Mirror the SMC label
    # semantics exactly — order blocks invalidate on a single close breach,
    # FVGs on two consecutive close breaches.
    invalidation_consecutive = 2 if family == "FVG" else 1
    invalid_idx = _first_invalidation_index(
        sign, zone_low, zone_high, closes, consecutive=invalidation_consecutive
    )
    if invalid_idx is not None and touch_idx > invalid_idx:
        return None

    exit_idx = min(touch_idx + horizon, len(closes) - 1)
    if exit_idx <= touch_idx or exit_idx >= len(closes):
        # No close available after the touch -> trade cannot be marked out.
        return None

    entry_price = (zone_low + zone_high) / 2.0
    if entry_price <= 0.0:
        return None
    exit_price = closes[exit_idx]

    gross = sign * (exit_price - entry_price) / entry_price
    return gross - cost_bps / 1e4


def extract_family_returns(
    events: list[FamilyEvent], *, cost_bps: float = DEFAULT_COST_BPS
) -> dict[str, dict[str, list[float]]]:
    """Group realized returns (and entry timestamps) by family.

    Untriggered / degenerate events are excluded. The returned mapping is
    ``{family: {"returns": [...], "timestamps": [...]}}`` where each
    timestamp is the event's ``anchor_ts`` (the decision time), suitable
    for the ``build_family_metrics`` point-in-time guard.
    """
    out: dict[str, dict[str, list[float]]] = {}
    for event in events:
        ret = realized_return(event, cost_bps=cost_bps)
        if ret is None:
            continue
        family = event["family"]
        bucket = out.setdefault(family, {"returns": [], "timestamps": []})
        bucket["returns"].append(ret)
        bucket["timestamps"].append(float(event["anchor_ts"]))
    return out


def _event_bar_interval(forward_timestamps: list[float]) -> float:
    """Median positive spacing between an event's forward bars (seconds).

    Used to translate the family embargo (in bars) into wall-clock time so the
    walk-forward purge can guard the label window. ``0.0`` when the window has
    fewer than two timestamps (embargo then collapses to the label end only).
    """
    diffs = sorted(
        d for first, second in zip(forward_timestamps, forward_timestamps[1:])
        if (d := float(second) - float(first)) > 0.0
    )
    if not diffs:
        return 0.0
    return diffs[len(diffs) // 2]


def extract_family_calibration_samples(
    events: list[FamilyEvent], *, cost_bps: float = DEFAULT_COST_BPS
) -> dict[str, dict[str, list[float]]]:
    """Per family, collect the inputs the walk-forward calibrator needs.

    For every event that BOTH triggered (a realized return exists) AND carries
    a raw ``score`` AND forward timestamps, emit a parallel-list bundle
    ``{family: {"scores", "returns", "anchor_ts", "guard_end_ts"}}``.

    ``guard_end_ts`` is the event's label-window end (the last forward
    timestamp) PLUS the family embargo expressed in time (``embargo_bars`` *
    the event's own median bar spacing). The downstream purge keeps a training
    event only when its ``guard_end_ts`` resolves strictly before a test fold
    begins, which prevents overlapping-label leakage across the train/test
    boundary (senior-quant review GAP 1; Lopez de Prado 2018, ch. 7). Events
    without a score or forward timestamps are excluded -- they cannot be
    calibrated leak-safely and are never invented into the sample.
    """
    out: dict[str, dict[str, list[float]]] = {}
    for event in events:
        if "score" not in event:
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
        bucket = out.setdefault(
            family,
            {"scores": [], "returns": [], "anchor_ts": [], "guard_end_ts": []},
        )
        bucket["scores"].append(float(event["score"]))
        bucket["returns"].append(ret)
        bucket["anchor_ts"].append(float(event["anchor_ts"]))
        bucket["guard_end_ts"].append(guard_end)
    return out


# Minimum realized events the prevailing regime must carry before its mean
# return is trustworthy enough to flag degradation. Below this the current
# regime stays "not yet measured" (None) and the strict gate keeps blocking.
REGIME_MIN_SAMPLES = 20


class RegimeSamples(TypedDict):
    """Per-family parallel lists the regime-degradation verdict consumes."""

    returns: list[float]
    regimes: list[str]
    anchor_ts: list[float]


def extract_family_regime_samples(
    events: list[FamilyEvent], *, cost_bps: float = DEFAULT_COST_BPS
) -> dict[str, RegimeSamples]:
    """Per family, collect the inputs the regime-degradation verdict needs.

    For every event that BOTH triggered (a realized return exists) AND carries
    a point-in-time ``regime`` label, emit a parallel-list bundle
    ``{family: {"returns", "regimes", "anchor_ts"}}``. Unlike the calibration
    samples this does NOT require a ``score`` -- the regime stratification is
    independent of the calibration feature. Events without a regime label are
    excluded (never invented into a regime).
    """
    out: dict[str, RegimeSamples] = {}
    for event in events:
        regime = event.get("regime")
        if not regime:
            continue
        ret = realized_return(event, cost_bps=cost_bps)
        if ret is None:
            continue
        family = event["family"]
        bucket = out.setdefault(
            family, {"returns": [], "regimes": [], "anchor_ts": []}
        )
        bucket["returns"].append(ret)
        bucket["regimes"].append(str(regime))
        bucket["anchor_ts"].append(float(event["anchor_ts"]))
    return out


class FeatureSamples(TypedDict):
    """Per-family parallel lists the ADR-0019 A/B harness consumes.

    ``outcomes`` is the binary sign-of-return label (1.0 iff the realized net
    return is positive), matching ``family_calibration``'s target so the A/B
    measures resolution against the same label the v1 score is graded on.
    """

    feature: list[float]
    outcomes: list[float]
    anchor_ts: list[float]


def extract_family_feature_samples(
    events: list[FamilyEvent],
    *,
    feature_key: str = "relative_volume",
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, FeatureSamples]:
    """Per family, collect a recorded v2 candidate feature paired with outcomes.

    For every event that BOTH triggered (a realized return exists) AND carries
    the recorded ``feature_key`` (e.g. the ADR-0019 ``relative_volume``), emit
    a parallel-list bundle ``{family: {"feature", "outcomes", "anchor_ts"}}``.
    ``outcomes`` is the binary sign-of-return label (1.0 iff the net return is
    positive), the same target ``family_calibration`` grades the v1 score on.

    This is **measurement groundwork only**: it does not calibrate, score, or
    gate anything. It hands the pre-registered purged walk-forward A/B
    (ADR-0019) the per-event ``(feature, outcome, anchor_ts)`` it needs to test
    whether the candidate feature lifts resolution. Events without the feature
    are excluded -- the feature is recorded omitted-not-zero-filled upstream and
    is never invented into the sample here.
    """
    out: dict[str, FeatureSamples] = {}
    for event in events:
        if feature_key not in event:
            continue
        ret = realized_return(event, cost_bps=cost_bps)
        if ret is None:
            continue
        family = event["family"]
        bucket = out.setdefault(
            family, {"feature": [], "outcomes": [], "anchor_ts": []}
        )
        event_view: Mapping[str, Any] = event
        bucket["feature"].append(float(event_view[feature_key]))
        bucket["outcomes"].append(1.0 if ret > 0.0 else 0.0)
        bucket["anchor_ts"].append(float(event["anchor_ts"]))
    return out


def regime_degradation(
    returns: list[float],
    regimes: list[str],
    anchor_ts: list[float],
    *,
    min_regime_samples: int = REGIME_MIN_SAMPLES,
) -> bool | None:
    """C5.1 verdict: is the family's edge absent in the regime it would trade?

    Stratifies realized net ``returns`` by the regime label that prevailed
    when each event formed, then asks a single, monotone question: *if the
    pooled edge is positive, does it survive in the regime we would actually
    deploy into?* The "current" regime is the one that prevailed at the
    chronologically most-recent event (``max(anchor_ts)``) -- the honest,
    lookahead-free proxy for the regime promotion would trade next.

    Returns:

    * ``True``  -- the pooled mean net return is > 0 (an edge the gate is being
      asked to promote) BUT the mean net return *within the current regime* is
      <= 0: the pooled edge is carried by other regimes and the family has no
      demonstrated edge in the one it would trade -> degraded, block.
    * ``False`` -- measured and not degraded: either there is no pooled edge to
      protect (<= 0; PSR/MinTRL handle that globally, not a regime problem), or
      the current regime itself shows a positive mean.
    * ``None``  -- not yet measurable: no labelled events, or the current
      regime carries fewer than ``min_regime_samples`` events. The strict gate
      keeps blocking on "regime_degraded not yet measured" rather than guessing.

    The verdict can only ADD a blocker (``True``); it never relaxes the gate.
    """
    if not (len(returns) == len(regimes) == len(anchor_ts)):
        raise ValueError("regime_degradation: input lists length mismatch")
    n = len(returns)
    if n == 0:
        return None

    pooled_mean = sum(returns) / n
    if pooled_mean <= 0.0:
        # No pooled edge to protect -- a global failure the PSR/MinTRL checks
        # already own. Not a regime-conditional degradation. Measured: False.
        return False

    # The regime prevailing at the most recent event = what we would trade next.
    current_regime = regimes[max(range(n), key=lambda i: anchor_ts[i])]
    current = [r for r, g in zip(returns, regimes) if g == current_regime]
    if len(current) < min_regime_samples:
        return None  # current regime not yet sufficiently observed

    current_mean = sum(current) / len(current)
    return current_mean <= 0.0


def to_build_spec(
    events: list[FamilyEvent],
    *,
    periods_per_year: int = 252,
    cost_bps: float = DEFAULT_COST_BPS,
    as_of: float | None = None,
) -> dict[str, Any]:
    """Build a ``build_family_metrics.build_bundle`` spec from events.

    When ``as_of`` is given it is attached to every family so the
    downstream PSR producer runs its point-in-time guard against the
    event entry timestamps. Epoch-second floats (``anchor_ts`` / ``as_of``)
    are emitted as ISO-8601 UTC strings, the form the EV-04 guard accepts.

    When events carry raw scores (EV-24), a per-family ``calibration`` block
    with walk-forward out-of-sample ``(probabilities, outcomes)`` is also
    emitted so the gate can measure Brier/ECE. Families with too few
    out-of-sample points emit no block and stay honestly "not yet measured".
    The calibration target is ``sign(return)`` -- a WIN-RATE diagnostic, NOT an
    edge proof; PSR/MinTRL/FDR remain the primary edge gate (review GAP 2).
    """
    grouped = extract_family_returns(events, cost_bps=cost_bps)
    calibration_samples = extract_family_calibration_samples(events, cost_bps=cost_bps)
    regime_samples = extract_family_regime_samples(events, cost_bps=cost_bps)
    families: dict[str, Any] = {}
    for family, bucket in grouped.items():
        entry: dict[str, Any] = {"returns": bucket["returns"]}
        if as_of is not None:
            entry["timestamps"] = [_epoch_to_iso(t) for t in bucket["timestamps"]]
            entry["as_of"] = _epoch_to_iso(as_of)
        provenance: dict[str, Any] = {}
        samples = calibration_samples.get(family)
        if samples is not None:
            block = walk_forward_calibration(
                samples["scores"],
                samples["returns"],
                samples["anchor_ts"],
                samples["guard_end_ts"],
            )
            if block is not None:
                entry["calibration"] = block
                # EV-24 audit-only provenance (the gate ignores unknown keys;
                # the producer copies these through verbatim). Records exactly
                # how the calibration probabilities were produced so the OOS
                # guarantee and the win-rate-not-edge caveat are auditable.
                provenance.update(
                    {
                        "ev24_score_source": SCORE_SOURCE,
                        "ev24_calibrator": CALIBRATOR_TAG,
                        "ev24_fold_scheme": FOLD_SCHEME_TAG,
                        "ev24_calibration_target": TARGET_TAG,
                    }
                )
            # EV#6 C9 PSI-trend: drift-over-time of the score population scored
            # through a fixed reference lens. Absent (too few events / single
            # outcome class) -> no block, family stays "not yet measured".
            psi_trend_block = walk_forward_psi_trend(
                samples["scores"],
                samples["returns"],
                samples["anchor_ts"],
            )
            if psi_trend_block is not None:
                entry["psi_trend"] = psi_trend_block
                provenance["ev24_psi_trend_source"] = PSI_TREND_SOURCE_TAG
        # EV#7 C5.1 regime degradation: stratify realized returns by the
        # point-in-time regime label. Independent of the calibration feature,
        # so it runs even when no score was attached. None (no labels / current
        # regime under-sampled) -> not attached, family stays "not yet measured".
        rsamples = regime_samples.get(family)
        if rsamples is not None:
            verdict = regime_degradation(
                rsamples["returns"], rsamples["regimes"], rsamples["anchor_ts"]
            )
            if verdict is not None:
                entry["regime_degraded"] = verdict
                provenance["ev24_regime_source"] = REGIME_SOURCE
        if provenance:
            entry["provenance"] = provenance
        families[family] = entry
    return {"periods_per_year": periods_per_year, "families": families}


def _epoch_to_iso(epoch_seconds: float) -> str:
    """Render an epoch-second timestamp as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(float(epoch_seconds), tz=UTC).isoformat()


__all__ = [
    "DEFAULT_COST_BPS",
    "REGIME_MIN_SAMPLES",
    "RETURN_RULE",
    "EntryMode",
    "FamilyEvent",
    "RegimeSamples",
    "extract_family_regime_samples",
    "extract_family_returns",
    "realized_return",
    "regime_degradation",
    "to_build_spec",
]

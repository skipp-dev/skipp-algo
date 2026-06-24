"""Phase A — Uniform freshness / invalidation state across all SMC event families.

This module provides a single canonical representation of "how fresh is this event"
that works identically for BOS, OB, FVG, and SWEEP events.  It replaces the
fragmented per-family freshness fields that existed before Phase A
(``STRUCTURE_EVENT_AGE_BARS``, ``OB_FRESH``, ``FVG_FRESH``, etc.) with a unified
:class:`FreshnessState` and two helpers:

* :func:`classify_freshness` — produce a :class:`FreshnessState` from raw inputs.
* :func:`freshness_decay_multiplier` — 0.0–1.0 score multiplier for the OB / FVG /
  Liquidity buckets in ``build_signal_quality_v2``.

The multiplier is *not* applied in v1 scoring; it is ignored unless
``SIGNAL_QUALITY_MODEL`` is set to ``"v2"`` or later.

Design notes
------------
* All arithmetic is pure; no I/O, no side-effects, no global state.
* The ``freshness_penalty`` field (multiplier range 0.0–1.0) signals:
    - ``1.0`` → full strength (fresh)
    - ``0.5–0.99`` → partial decay (aging / stale)
    - ``0.0`` → fully decayed (invalidated, or explicitly mitigated at 0)
* Hard gate: ``invalidated`` events are capped at ``FreshnessBucket.INVALIDATED``
  regardless of age.  In ``build_signal_quality_v2`` this caps the signal tier at
  ``"C"`` to prevent stale invalidated events from scoring into the top tiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

FreshnessBucket = Literal["fresh", "aging", "stale", "invalidated", "mitigated"]

#: Thresholds (in bars) for freshness classification.  These are intentionally
#: conservative — an event that has lasted more than STALE_BARS bars has had
#: ample opportunity to be mitigated or invalidated; surviving that long may
#: reflect persistence OR neglect.  Calibrate against the measurement pipeline
#: before tightening.
FRESH_BARS: int = 5
AGING_BARS: int = 20
STALE_BARS: int = 50

#: Decay schedule: multiplier applied to OB/FVG/Liquidity buckets per bucket tier.
_DECAY: dict[FreshnessBucket, float] = {
    "fresh": 1.00,
    "aging": 0.85,
    "stale": 0.60,
    "invalidated": 0.00,
    "mitigated": 0.40,
}


@dataclass(frozen=True, slots=True)
class FreshnessState:
    """Canonical freshness descriptor for a single SMC event.

    Parameters
    ----------
    event_age_bars:
        Number of bars elapsed since the event was detected.  Always ≥ 0.
    event_age_seconds:
        Wall-clock age of the event in seconds; 0.0 if not available.
    freshness_bucket:
        Categorical freshness tier — one of ``fresh``, ``aging``, ``stale``,
        ``invalidated``, or ``mitigated``.
    freshness_penalty:
        0.0–1.0 multiplier.  ``1.0`` = no penalty (full strength).  In
        ``build_signal_quality_v2`` this multiplies the OB, FVG, and Liquidity
        bucket raw scores before they are summed.
    invalidated_at:
        POSIX timestamp at which the event was structurally invalidated (e.g.
        a BOS was negated by a counter-move).  ``None`` if still structurally
        valid.
    mitigated_at:
        POSIX timestamp at which the event zone was first touched / mitigated.
        ``None`` if not yet mitigated.
    """

    event_age_bars: int
    event_age_seconds: float
    freshness_bucket: FreshnessBucket
    freshness_penalty: float
    invalidated_at: float | None
    mitigated_at: float | None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def classify_freshness(
    age_bars: int,
    *,
    mitigated: bool,
    invalidated: bool = False,
    mitigated_ts: float | None = None,
    invalidated_ts: float | None = None,
    bar_seconds: float = 60.0,
) -> FreshnessState:
    """Classify the freshness of an SMC event from raw inputs.

    Parameters
    ----------
    age_bars:
        Number of bars since the event was detected.  Must be ≥ 0.
    mitigated:
        True if the event's zone has been touched/mitigated at least once.
    invalidated:
        True if the event has been structurally negated (e.g. BOS countered,
        OB fully consumed, FVG completely filled).
    mitigated_ts:
        POSIX timestamp of first mitigation touch; required when
        ``mitigated=True``.
    invalidated_ts:
        POSIX timestamp of structural invalidation; required when
        ``invalidated=True``.
    bar_seconds:
        Duration of one bar in seconds (default 60 → 1-minute bars).  Used to
        compute ``event_age_seconds``.

    Returns
    -------
    FreshnessState
        Fully populated freshness descriptor.
    """
    if age_bars < 0:
        raise ValueError(f"age_bars must be ≥ 0, got {age_bars!r}")

    age_seconds: float = float(age_bars) * bar_seconds

    # Hard invalidation gate — overrides all other classification.
    if invalidated:
        return FreshnessState(
            event_age_bars=age_bars,
            event_age_seconds=age_seconds,
            freshness_bucket="invalidated",
            freshness_penalty=_DECAY["invalidated"],
            invalidated_at=invalidated_ts,
            mitigated_at=mitigated_ts,
        )

    if mitigated:
        return FreshnessState(
            event_age_bars=age_bars,
            event_age_seconds=age_seconds,
            freshness_bucket="mitigated",
            freshness_penalty=_DECAY["mitigated"],
            invalidated_at=None,
            mitigated_at=mitigated_ts,
        )

    # Age-based classification for valid, unmitigated events.
    if age_bars <= FRESH_BARS:
        bucket: FreshnessBucket = "fresh"
    elif age_bars <= AGING_BARS:
        bucket = "aging"
    else:
        bucket = "stale"

    return FreshnessState(
        event_age_bars=age_bars,
        event_age_seconds=age_seconds,
        freshness_bucket=bucket,
        freshness_penalty=_DECAY[bucket],
        invalidated_at=None,
        mitigated_at=None,
    )


def freshness_decay_multiplier(state: FreshnessState) -> float:
    """Return the 0.0–1.0 score multiplier for this freshness state.

    This is a thin pass-through of :attr:`FreshnessState.freshness_penalty`
    provided as a named function so call sites are self-documenting.

    Used by ``build_signal_quality_v2`` to multiply the OB, FVG, and Liquidity
    bucket scores *before* summing.  Has no effect on v1 scoring.
    """
    return state.freshness_penalty

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

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from governance.family_walkforward import family_outcome_horizon
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
    """
    grouped = extract_family_returns(events, cost_bps=cost_bps)
    families: dict[str, Any] = {}
    for family, bucket in grouped.items():
        entry: dict[str, Any] = {"returns": bucket["returns"]}
        if as_of is not None:
            entry["timestamps"] = [_epoch_to_iso(t) for t in bucket["timestamps"]]
            entry["as_of"] = _epoch_to_iso(as_of)
        families[family] = entry
    return {"periods_per_year": periods_per_year, "families": families}


def _epoch_to_iso(epoch_seconds: float) -> str:
    """Render an epoch-second timestamp as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(float(epoch_seconds), tz=UTC).isoformat()


__all__ = [
    "DEFAULT_COST_BPS",
    "RETURN_RULE",
    "EntryMode",
    "FamilyEvent",
    "extract_family_returns",
    "realized_return",
    "to_build_spec",
]

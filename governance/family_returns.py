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
from typing import Any, TypedDict

from governance.family_walkforward import family_outcome_horizon
from governance.types import EventFamily

# Fixed round-turn transaction cost (bps) subtracted from every realized
# return. 5 bps is a conservative large-cap incl.-slippage default; tune
# only with measured fill data. Configurable per call.
DEFAULT_COST_BPS = 5.0

# Tag recorded so downstream provenance can audit which trade definition
# produced a return series.
RETURN_RULE = "touch_then_horizon_close"

_BULLISH = {"UP", "BULL", "BULLISH", "LONG"}
_BEARISH = {"DOWN", "BEAR", "BEARISH", "SHORT"}


class FamilyEvent(TypedDict, total=False):
    """A detected SMC family event plus its forward bars.

    ``forward_*`` are the bars strictly AFTER the anchor (as produced by
    ``smc_integration.measurement_evidence._future_price_lists``).
    ``forward_timestamps`` is optional; when present it is leak-checked
    against ``anchor_ts``.
    """

    family: EventFamily
    direction: str
    zone_low: float
    zone_high: float
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
    """Realized return for a single event under variant A.

    Returns ``None`` when the setup did not trigger (no touch) or is
    degenerate (non-positive entry / no exit bar) — those are not trades.
    """
    family = event["family"]
    zone_low = float(event["zone_low"])
    zone_high = float(event["zone_high"])
    if zone_low <= 0.0 or zone_high <= 0.0 or zone_high < zone_low:
        return None

    sign = _direction_sign(str(event.get("direction", "")))
    if sign == 0:
        return None

    _assert_forward_after_anchor(event)

    highs = [float(x) for x in event.get("forward_highs", [])]
    lows = [float(x) for x in event.get("forward_lows", [])]
    closes = [float(x) for x in event.get("forward_closes", [])]

    touch_idx = _first_touch_index(sign, zone_low, zone_high, highs, lows)
    if touch_idx is None:
        return None

    horizon = family_outcome_horizon(family)
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
    "FamilyEvent",
    "extract_family_returns",
    "realized_return",
    "to_build_spec",
]

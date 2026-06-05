"""EV-07 wiring adapter: real SMC structure + bars -> ``FamilyEvent``.

This module is the bridge between *detected* SMC structure (BOS / OB / FVG /
SWEEP events, as produced from Pine artifacts via
``smc_adapters.ingest.build_structure_from_raw`` or recomputed in Python via
``scripts.explicit_structure_from_bars.build_explicit_structure_from_bars``)
and the realized-return machinery in :mod:`governance.family_returns`.

It fabricates nothing. Detection happens upstream; this adapter only:

  1. locates each event's anchor bar (first bar at-or-after the event time),
  2. extracts the forward bars strictly *after* the anchor, and
  3. emits a :class:`~governance.family_returns.FamilyEvent` with the exact
     same geometry the live scorer uses
     (:func:`smc_integration.measurement_evidence._find_bar_index` /
     ``_future_price_lists``), mirrored here so this module carries no heavy
     import chain and stays trivially testable.

Two event geometries map to two entry rules (see ``family_returns``):

  * **Zone families** OB / FVG -> ``entry_mode="retest_touch"`` using the
    detected ``low``/``high`` zone.
  * **Level families** BOS / SWEEP -> ``entry_mode="immediate"`` using the
    detected break / sweep ``price`` as the entry level. SWEEP direction is
    the *reversal* of the swept side, matching the live scorer.

**Anchor requirement (honest limitation).** Every event needs a formation
timestamp (``anchor_ts``, or legacy ``time``) to locate its anchor bar; an
event without one cannot be anchored without fabricating a position in time,
so it is *dropped* (never anchored to bar 0 or "now"). BOS and SWEEP carry a
``time`` in the SMC type model and the explicit-recompute path
(:func:`scripts.explicit_structure_from_bars.build_explicit_structure_from_bars`)
emits ``anchor_ts`` for OB/FVG zones too — so both anchor cleanly. The raw
**Pine** OB/FVG serialization (``smc_adapters.pine._ob_entry`` /
``_fvg_entry``), however, carries no time field because
:class:`smc_core.types.Orderblock` / :class:`~smc_core.types.Fvg` have none.
OB/FVG zones taken straight from Pine artifacts are therefore silently
unanchorable and dropped: use the explicit-recompute path for zone returns
until the zone types/serialization grow a formation timestamp.

The production path feeds REAL databento bars and REAL detected structure;
unit tests may feed synthetic bars, but the adapter logic never invents
prices, touches, or outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from governance.family_avg_trade_size_v2 import average_trade_size_at
from governance.family_event_score import point_in_time_regime, raw_score
from governance.family_kyle_lambda_v2 import kyle_lambda_at
from governance.family_ofi_imbalance_v2 import ofi_imbalance_at
from governance.family_returns import FamilyEvent
from governance.family_score_features_v2 import relative_volume_at
from governance.family_signed_uoa_notional_v2 import signed_uoa_notional_at
from governance.family_vpin_v2 import vpin_at
from governance.types import EventFamily

# Lookahead windows, mirrored from
# ``smc_integration.measurement_evidence`` so the forward bars handed to the
# return calculator match exactly what the live scorer observes.
_BOS_LOOKAHEAD_BARS = 8
_ZONE_LOOKAHEAD_BARS = 12
_FVG_LOOKAHEAD_BARS = 20
_SWEEP_LOOKAHEAD_BARS = 8

# Raw-structure container keys (Pine ingest / explicit recompute share these).
_BOS_KEY = "bos"
_OB_KEY = "orderblocks"
_FVG_KEY = "fvg"
_SWEEP_KEY = "liquidity_sweeps"


class BarRow(TypedDict, total=False):
    """A single OHLC(V) bar. ``timestamp`` is epoch seconds (UTC).

    ``volume`` is optional and carried point-in-time for the ADR-0019 v2
    order-flow features (``governance.family_score_features_v2``). It does not
    affect the v1 score, regime, or any gate; bars without it stay fully
    supported and the v2 feature is simply reported as absent.
    """

    timestamp: float
    high: float
    low: float
    close: float
    volume: float


def _bar_index_at_or_after(timestamps: Sequence[float], anchor_ts: float) -> int | None:
    """First bar index whose timestamp is at-or-after ``anchor_ts``.

    Mirror of ``measurement_evidence._find_bar_index``.
    """
    target = float(anchor_ts)
    for idx, ts in enumerate(timestamps):
        if float(ts) >= target:
            return idx
    return None


def _forward_window(
    bars: Sequence[Mapping[str, Any]], *, anchor_idx: int, lookahead_bars: int
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Bars strictly AFTER ``anchor_idx`` (mirror of ``_future_price_lists``)."""
    window = bars[anchor_idx + 1 : anchor_idx + 1 + int(lookahead_bars)]
    highs = [float(b["high"]) for b in window]
    lows = [float(b["low"]) for b in window]
    closes = [float(b["close"]) for b in window]
    timestamps = [float(b["timestamp"]) for b in window]
    return highs, lows, closes, timestamps


def _anchor_ts(event: Mapping[str, Any]) -> float:
    return float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)


def _sweep_direction(side: str) -> str:
    # Mirror of ``_expected_reversal_direction``: a swept sell-side liquidity
    # pool is expected to reverse up (long), a buy-side pool down (short).
    # Any other / malformed side returns "" so the level builder drops the
    # event rather than coercing a bad record into a spurious short.
    normalized = str(side).strip().upper()
    if normalized == "SELL_SIDE":
        return "LONG"
    if normalized == "BUY_SIDE":
        return "SHORT"
    return ""


def _zone_event_to_family(
    event: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    timestamps: Sequence[float],
    *,
    family: EventFamily,
    lookahead_bars: int,
) -> FamilyEvent | None:
    low = float(event.get("low", 0.0) or 0.0)
    high = float(event.get("high", 0.0) or 0.0)
    anchor_ts = _anchor_ts(event)
    direction = str(event.get("dir", "")).strip()
    if low <= 0.0 or high <= 0.0 or high < low or anchor_ts <= 0.0:
        return None

    anchor_idx = _bar_index_at_or_after(timestamps, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    highs, lows, closes, fwd_ts = _forward_window(
        bars, anchor_idx=anchor_idx, lookahead_bars=lookahead_bars
    )
    if not closes:
        return None

    mapped = FamilyEvent(
        family=family,
        direction=direction,
        entry_mode="retest_touch",
        zone_low=low,
        zone_high=high,
        anchor_ts=anchor_ts,
        forward_highs=highs,
        forward_lows=lows,
        forward_closes=closes,
        forward_timestamps=fwd_ts,
    )
    score = raw_score(
        family, bars=bars, anchor_idx=anchor_idx, zone_low=low, zone_high=high
    )
    if score is not None:
        mapped["score"] = score
    regime = point_in_time_regime(bars, anchor_idx)
    if regime is not None:
        mapped["regime"] = regime
    rel_volume = relative_volume_at(bars, anchor_idx)
    if rel_volume is not None:
        mapped["relative_volume"] = rel_volume
    kyle_lambda = kyle_lambda_at(bars, anchor_idx)
    if kyle_lambda is not None:
        mapped["kyle_lambda"] = kyle_lambda
    avg_trade_size = average_trade_size_at(bars, anchor_idx)
    if avg_trade_size is not None:
        mapped["average_trade_size"] = avg_trade_size
    ofi = ofi_imbalance_at(bars, anchor_idx)
    if ofi is not None:
        mapped["ofi_imbalance"] = ofi
    vpin = vpin_at(bars, anchor_idx)
    if vpin is not None:
        mapped["vpin"] = vpin
    signed_uoa = signed_uoa_notional_at(bars, anchor_idx)
    if signed_uoa is not None:
        mapped["signed_uoa_notional"] = signed_uoa
    return mapped


def _level_event_to_family(
    event: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    timestamps: Sequence[float],
    *,
    family: EventFamily,
    direction: str,
    lookahead_bars: int,
) -> FamilyEvent | None:
    price = float(event.get("price", 0.0) or 0.0)
    anchor_ts = _anchor_ts(event)
    if price <= 0.0 or anchor_ts <= 0.0 or not direction:
        return None

    anchor_idx = _bar_index_at_or_after(timestamps, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    highs, lows, closes, fwd_ts = _forward_window(
        bars, anchor_idx=anchor_idx, lookahead_bars=lookahead_bars
    )
    if not closes:
        return None

    mapped = FamilyEvent(
        family=family,
        direction=direction,
        entry_mode="immediate",
        entry_price=price,
        anchor_ts=anchor_ts,
        forward_highs=highs,
        forward_lows=lows,
        forward_closes=closes,
        forward_timestamps=fwd_ts,
    )
    score = raw_score(family, bars=bars, anchor_idx=anchor_idx)
    if score is not None:
        mapped["score"] = score
    regime = point_in_time_regime(bars, anchor_idx)
    if regime is not None:
        mapped["regime"] = regime
    rel_volume = relative_volume_at(bars, anchor_idx)
    if rel_volume is not None:
        mapped["relative_volume"] = rel_volume
    kyle_lambda = kyle_lambda_at(bars, anchor_idx)
    if kyle_lambda is not None:
        mapped["kyle_lambda"] = kyle_lambda
    avg_trade_size = average_trade_size_at(bars, anchor_idx)
    if avg_trade_size is not None:
        mapped["average_trade_size"] = avg_trade_size
    ofi = ofi_imbalance_at(bars, anchor_idx)
    if ofi is not None:
        mapped["ofi_imbalance"] = ofi
    vpin = vpin_at(bars, anchor_idx)
    if vpin is not None:
        mapped["vpin"] = vpin
    signed_uoa = signed_uoa_notional_at(bars, anchor_idx)
    if signed_uoa is not None:
        mapped["signed_uoa_notional"] = signed_uoa
    return mapped


def family_events_from_structure(
    structure: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
) -> list[FamilyEvent]:
    """Convert a detected SMC structure + bars into ``FamilyEvent`` records.

    ``structure`` is the raw container with keys ``bos``, ``orderblocks``,
    ``fvg`` and ``liquidity_sweeps`` (Pine ingest or explicit recompute).
    ``bars`` is an ordered sequence of OHLC bars with epoch-second
    ``timestamp`` fields. Events that cannot be anchored (no bar at-or-after
    the event time, or no forward bar) or are degenerate are dropped, exactly
    as the live scorer drops them.
    """
    timestamps = [float(b["timestamp"]) for b in bars]
    events: list[FamilyEvent] = []

    for raw in structure.get(_BOS_KEY, []) or []:
        mapped = _level_event_to_family(
            raw,
            bars,
            timestamps,
            family="BOS",
            direction=str(raw.get("dir", "")).strip(),
            lookahead_bars=_BOS_LOOKAHEAD_BARS,
        )
        if mapped is not None:
            events.append(mapped)

    for raw in structure.get(_OB_KEY, []) or []:
        mapped = _zone_event_to_family(
            raw, bars, timestamps, family="OB", lookahead_bars=_ZONE_LOOKAHEAD_BARS
        )
        if mapped is not None:
            events.append(mapped)

    for raw in structure.get(_FVG_KEY, []) or []:
        mapped = _zone_event_to_family(
            raw, bars, timestamps, family="FVG", lookahead_bars=_FVG_LOOKAHEAD_BARS
        )
        if mapped is not None:
            events.append(mapped)

    for raw in structure.get(_SWEEP_KEY, []) or []:
        mapped = _level_event_to_family(
            raw,
            bars,
            timestamps,
            family="SWEEP",
            direction=_sweep_direction(str(raw.get("side", ""))),
            lookahead_bars=_SWEEP_LOOKAHEAD_BARS,
        )
        if mapped is not None:
            events.append(mapped)

    return events


__all__ = [
    "BarRow",
    "family_events_from_structure",
]

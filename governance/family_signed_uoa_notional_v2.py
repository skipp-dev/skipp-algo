"""ADR-0020 — signed unusual-options-activity (UOA) notional shadow feature.

This is the first feature on the **options-flow datapath** (ADR-0020), the next
information axis after the OHLCV / equity-microstructure seam was declared
saturated (``docs/governance/feature_onramp_saturation_verdict.md``). Where every
ADR-0019 candidate measured a different *function of the same bars*, this feature
reads a **different instrument class entirely**: the aggressor-signed options
tape (OPRA ``trades``), which is forward-looking in a way the underlying's own
OHLCV is not — a wall of bid-lifting call premium is a directional bet placed
*before* the move shows up in the stock's bars.

Over a window it is the **signed options-flow imbalance**

    signed_uoa = sum(uoa_signed_notional) / sum(uoa_abs_notional)   in [-1, +1]

where, per bar, the producer embeds

  * ``uoa_signed_notional`` = ``sum`` over the bar's OPRA prints of
    ``(+1 if side == 'A' else -1 if side == 'B' else 0) * price * size * 100``
    (the OCC contract multiplier), and
  * ``uoa_abs_notional`` = ``sum`` of ``price * size * 100`` over **all** the
    bar's prints (the total premium notional that changed hands).

Note the OPRA aggressor convention is the **inverse** of the equity tape used by
the ADR-0016 ``signed_volume`` features: on options ``A`` (trade hit the ask) is
the aggressive **buyer** -> bullish (+), and ``B`` (hit the bid) is the
aggressive **seller** -> bearish (-); ``N`` (cross / unknown) is unsigned. This
matches ``newsstack_fmp.opra_uoa._side_to_aggressor`` exactly, so the recorded
shadow feature and the live UOA alerts speak the same sign language.

Unlike order-flow *imbalance* (``ofi_imbalance_at``), which takes the absolute
value because magnitude one-sidedness is its question, this feature **keeps the
sign**: the whole thesis of options flow is *direction* — are the big premium
prints leaning bullish or bearish — so ``+1`` is fully bid-lifting call/put
premium one way and ``-1`` the other.

Options do not print on every bar (especially out-of-the-money strikes), so the
window is **gap-tolerant**: a bar with no embedded UOA keys contributed no flow
and adds ``0`` to both sums (it is *not* a missing-data refusal). This makes the
honest-None test clean: when OPRA was never pulled, *no* bar carries the keys,
so both sums are zero over the window and the feature is honestly absent; when
OPRA was pulled but the window simply saw no prints, the sums are likewise zero
and the (undefined) ratio is honestly ``None`` — there is no flow to take a side.

RECORDED-ONLY (ADR-0019 / ADR-0020 discipline): a shadow feature whose values
ride alongside event outcomes so a pre-registered purged walk-forward A/B can
decide whether it lifts resolution. It is NOT wired into the v1 score or any
gate. Strictly point-in-time and honest-None: it never reads a bar after the
anchor and returns ``None`` rather than fabricating a value when its inputs are
absent or the window carries no traded premium.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so this candidate shares the single trailing horizon
# every other v2 order-flow feature uses (no per-family tuning, minimal degrees
# of freedom).
from governance.family_event_score import ATR_PERIOD

# Provenance tag recording how each event's signed-UOA-notional feature was
# produced. The ``_v2`` suffix marks it as an ADR-0020 candidate, distinct from
# the v1 ``SCORE_SOURCE`` and the ADR-0019 order-flow tags.
SIGNED_UOA_NOTIONAL_SOURCE = "options_flow_signed_uoa_notional_v2"

# Sentinel distinguishing "key present but corrupt" (refuse the window) from
# "key honestly absent" (no flow on this bar -> contribute 0). A single-member
# enum is used (rather than a bare ``object()``) so the static type checker can
# narrow it out of the ``float | _Corrupt | None`` union after an ``is`` check —
# a bare ``object`` would subsume ``float`` and defeat narrowing.
class _Corrupt(enum.Enum):
    TOKEN = enum.auto()


_CORRUPT = _Corrupt.TOKEN


def _bar_signed_notional(bar: Mapping[str, Any]) -> float | _Corrupt | None:
    """Signed options-flow premium notional for one bar.

    Returns the embedded ``uoa_signed_notional`` as a float, ``None`` when the
    key is honestly absent (the bar saw no OPRA prints, or OPRA was never
    pulled), or ``"corrupt"`` when present but non-numeric / NaN so the caller
    can refuse the whole window rather than silently drop a bad bar.
    """
    raw = bar.get("uoa_signed_notional")
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _CORRUPT
    if val != val:  # NaN guard
        return _CORRUPT
    return val


def _bar_abs_notional(bar: Mapping[str, Any]) -> float | _Corrupt | None:
    """Total (unsigned) options-flow premium notional for one bar.

    Embedded alongside ``uoa_signed_notional`` by the producer. Must be
    non-negative (a sum of ``price * size * 100`` magnitudes); a negative or NaN
    value is treated as corrupt. Returns ``None`` when honestly absent.
    """
    raw = bar.get("uoa_abs_notional")
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _CORRUPT
    if val != val or val < 0.0:  # NaN guard + non-negativity
        return _CORRUPT
    return val


def signed_uoa_notional_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Signed options-flow imbalance over the trailing ``period``-bar window.

    Over the window of ``period`` bars ending at ``anchor_idx`` (inclusive),
    return ``sum(uoa_signed_notional) / sum(uoa_abs_notional)`` in ``[-1, +1]``.
    Summing the signed and absolute premium separately (rather than averaging
    per-bar ratios) weights each bar by its premium activity, so one thin bar
    cannot dominate. The sign is preserved: ``+1`` is fully bullish (ask-lifting)
    premium, ``-1`` fully bearish (bid-hitting) premium, ``0`` balanced flow.

    Strictly point-in-time: the window covers indices
    ``[anchor_idx - period + 1, anchor_idx]`` and never touches a bar after the
    anchor, so it is leak-free by construction.

    Gap-tolerant: a bar with no embedded UOA keys saw no options prints and adds
    ``0`` to both sums (it is not a refusal). Returns ``None`` (feature honestly
    absent) when ``period`` is below 1, there is not enough trailing history, any
    bar carries a corrupt UOA value, or the total premium notional over the
    window is zero (no flow to take a side -> undefined).
    """
    if period < 1 or anchor_idx < period - 1 or anchor_idx >= len(bars):
        return None

    total_signed = 0.0
    total_abs = 0.0
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        signed = _bar_signed_notional(bars[k])
        abs_notional = _bar_abs_notional(bars[k])
        if signed is _CORRUPT or abs_notional is _CORRUPT:
            return None
        # A bar with one key present and the other absent is malformed: the
        # producer always embeds the pair together. Refuse rather than guess.
        if (signed is None) != (abs_notional is None):
            return None
        # honest gap: no prints on this bar -> no flow. Testing both (rather
        # than just ``signed``) lets the type checker narrow each operand to
        # ``float`` for the sums below; the XOR guard above already proved the
        # pair is either both-None or both-present.
        if signed is None or abs_notional is None:
            continue
        total_signed += signed
        total_abs += abs_notional

    if total_abs <= 0.0:
        return None
    ratio = total_signed / total_abs
    # |sum(signed)| <= sum(|notional|) = total_abs holds per bar, but float
    # rounding over a long window can nudge the ratio a hair past the bound;
    # clamp so the recorded feature stays in its definitional [-1, +1] range.
    if ratio > 1.0:
        return 1.0
    if ratio < -1.0:
        return -1.0
    return ratio


__all__ = ["SIGNED_UOA_NOTIONAL_SOURCE", "signed_uoa_notional_at"]

"""Contract enforcement for public SMC score fields.

The regular score computations clamp their outputs to a documented range (e.g.
``SIGNAL_QUALITY_SCORE`` 0–100, ``SWEEP_QUALITY_SCORE`` 0–5, the profile rate
fields 0–1). Two boundaries bypassed that contract:

* **Overrides.** The score builders accept a manual ``overrides`` dict (a test /
  manual affordance) that was applied *verbatim* after clamping, so an
  out-of-contract value like ``SIGNAL_QUALITY_SCORE=500`` or ``ZONE_PRIORITY_SCORE=-20``
  reached the Pine / Trust consumers, which then interpret it on its nominal scale.
* **Rate inputs.** ``smc_profile_context`` read rate columns straight from a
  DataFrame with only ``round()`` — a ``NaN`` (thin-history symbol) or an
  out-of-[0,1] value flowed unchecked into ``PROFILE_CLEAN_SCORE`` → ticker grade.

These helpers enforce the field contract at those boundaries: clamp finite
numeric values into range and REJECT a non-finite / non-numeric override so the
computed value stands. No ``try/except`` — numeric coercion is done with explicit
``isinstance`` / ``math.isfinite`` checks so the helpers never raise.
"""
from __future__ import annotations

import math
from typing import Any

# (lo, hi, as_int) contract for a numeric field.
FieldBound = tuple[float, float, bool]


def clamp_finite_01(value: float, default: float = 0.0) -> float:
    """Clamp ``value`` into ``[0.0, 1.0]``; a non-finite input yields ``default``."""
    return default if not math.isfinite(value) else max(0.0, min(1.0, value))


def clamp_finite(value: float, lo: float, hi: float, default: float = 0.0) -> float:
    """Clamp ``value`` into ``[lo, hi]``; a non-finite input yields ``default``."""
    return default if not math.isfinite(value) else max(lo, min(hi, value))


def clamp_override(value: Any, lo: float, hi: float, *, as_int: bool) -> float | int | None:
    """Return ``value`` clamped into ``[lo, hi]``, or ``None`` to REJECT it.

    A ``bool``, a non-numeric type, or a non-finite number is rejected (returns
    ``None``) so the caller keeps the contract-valid computed value instead of a
    poisoned override. ``bool`` is excluded explicitly because ``bool`` is an
    ``int`` subclass and ``True``/``False`` are never a meaningful score.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    v = max(lo, min(hi, v))
    return round(v) if as_int else v


def apply_bounded_override(
    result: dict[str, Any],
    key: str,
    value: Any,
    bounds: dict[str, FieldBound],
) -> None:
    """Apply one override onto ``result`` in place, contract-clamped.

    If ``key`` names a bounded numeric field, the value is clamped; a rejected
    (non-finite / non-numeric) override is dropped so the computed value stands.
    A non-bounded key (string fields such as tiers / ranks / directions) passes
    through unchanged.
    """
    bound = bounds.get(key)
    if bound is None:
        result[key] = value
        return
    clamped = clamp_override(value, bound[0], bound[1], as_int=bound[2])
    if clamped is not None:
        result[key] = clamped
    # else: reject the out-of-contract override; keep the computed value.

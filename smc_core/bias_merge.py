"""Central chart-timeframe / session bias merge — Single Source of Truth.

Priority rule:
  1. **Chart-TF bias** sets the directional anchor in production.
  2. **Session context** *modulates* the confidence without flipping direction.
  3. If HTF is unavailable, session bias is used as a lower-confidence fallback.

The merge result is a ``BiasVerdict`` consumed by service orchestration and
measurement evidence (not by ``smc_core/layering.py``, which never imports it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

BiasDirection = Literal["BULLISH", "BEARISH", "NEUTRAL"]


@dataclass(slots=True, frozen=True)
class BiasVerdict:
    """Immutable merge result of chart-timeframe + session bias."""

    direction: BiasDirection
    confidence: float  # 0.0–1.0 deterministic conviction/reliability WEIGHT from a fixed table (NOT a probability; rename-later: bias_conviction_score)
    htf_direction: BiasDirection  # deprecated compatibility name; see chart_tf_direction
    session_direction: BiasDirection
    conflict: bool  # True when HTF and session disagree
    source: Literal["HTF", "SESSION", "MERGED", "NONE"]

    @property
    def chart_tf_direction(self) -> BiasDirection:
        """Honest name for the production chart-timeframe direction."""
        return self.htf_direction

    @property
    def source_detail(self) -> Literal["CHART_TF", "SESSION", "MERGED_CHART_TF_SESSION", "NONE"]:
        """Honest provenance for consumers migrating from the legacy source."""
        return {
            "HTF": "CHART_TF",
            "SESSION": "SESSION",
            "MERGED": "MERGED_CHART_TF_SESSION",
            "NONE": "NONE",
        }[self.source]


def _direction_from_counter(counter: int) -> BiasDirection:
    if counter > 0:
        return "BULLISH"
    if counter < 0:
        return "BEARISH"
    return "NEUTRAL"


def _direction_from_killzones(killzones: list[dict[str, Any]]) -> BiasDirection:
    """Derive session bias from the most recent killzone high/low relationship."""
    if not killzones:
        return "NEUTRAL"
    latest = killzones[-1]
    mid = float(latest.get("mid", 0))
    high = float(latest.get("high", 0))
    low = float(latest.get("low", 0))
    if high == low:
        return "NEUTRAL"
    ratio = (mid - low) / (high - low) if (high - low) != 0 else 0.5
    if ratio > 0.55:
        return "BULLISH"
    if ratio < 0.45:
        return "BEARISH"
    return "NEUTRAL"


# Fixed conviction/reliability weights (NOT probabilities): HTF anchor is trusted
# above a session-only fallback; conflict scales ×0.6, concordance ×1.15 (below).
_CONFIDENCE_BASE = {
    "HTF": 0.8,
    "SESSION": 0.5,
    "NONE": 0.0,
}


def merge_bias(
    htf_context: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> BiasVerdict:
    """Merge HTF and session bias into a single deterministic verdict.

    Parameters
    ----------
    htf_context:
        Output of ``build_htf_bias_context`` (may be ``None`` or empty dict).
    session_context:
        Output of ``build_session_liquidity_context`` (may be ``None`` or empty dict).

    Returns
    -------
    BiasVerdict
        A frozen dataclass with the merged direction, confidence, and conflict flag.
    """
    htf_dir: BiasDirection = "NEUTRAL"
    session_dir: BiasDirection = "NEUTRAL"
    htf_available = False
    session_available = False

    # --- HTF ---
    if htf_context:
        bias_list = htf_context.get("fvg_bias_counter") or []
        if bias_list:
            last_counter = int(bias_list[-1].get("counter", 0))
            htf_dir = _direction_from_counter(last_counter)
            htf_available = True

    # --- Session ---
    if session_context:
        kz = session_context.get("killzones") or []
        if kz:
            session_dir = _direction_from_killzones(kz)
            session_available = True

    # --- Merge logic ---
    if not htf_available and not session_available:
        return BiasVerdict(
            direction="NEUTRAL",
            confidence=0.0,
            htf_direction="NEUTRAL",
            session_direction="NEUTRAL",
            conflict=False,
            source="NONE",
        )

    if not htf_available:
        return BiasVerdict(
            direction=session_dir,
            confidence=_CONFIDENCE_BASE["SESSION"],
            htf_direction="NEUTRAL",
            session_direction=session_dir,
            conflict=False,
            source="SESSION",
        )

    conflict = htf_dir != "NEUTRAL" and session_dir != "NEUTRAL" and htf_dir != session_dir

    # HTF dominates direction; session modulates confidence.
    base_conf = _CONFIDENCE_BASE["HTF"]
    if conflict:
        base_conf *= 0.6  # reduce confidence on conflicting signal
    elif session_dir == htf_dir:
        base_conf = min(1.0, base_conf * 1.15)  # concordance bonus

    return BiasVerdict(
        direction=htf_dir,
        confidence=round(base_conf, 4),
        htf_direction=htf_dir,
        session_direction=session_dir,
        conflict=conflict,
        source="MERGED" if session_available else "HTF",
    )

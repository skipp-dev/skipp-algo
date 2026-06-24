"""SMC v2 SMT Divergence detector (Phase E scaffolding, 2026-06-24).

SMT (Smart Money Technique) divergence compares the local SMC structure
with a correlated market context.  A divergence is flagged when the
primary structure is bullish but the correlated asset is showing
bearish structural evidence, or vice versa.  The detector is gated by
``ENABLE_SMT_DIVERGENCE`` and safe-defaults to neutral when the flag is
OFF or inputs are unavailable.
"""
from __future__ import annotations

from typing import Any

from smc_core.v2_config import smt_divergence_config
from smc_core.v2_features import smt_divergence_enabled


def detect_smt_divergence(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect SMT divergence against a correlated market.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``structure_state_light`` and an
        optional ``correlated_context`` block.

    Returns
    -------
    dict[str, Any]
        ``{"SMT_DIVERGENCE_DETECTED": bool, "SMT_DIVERGENCE_SIDE": str,
        "SMT_DIVERGENCE_CONFIDENCE": int}``.  Side is ``"bull"``,
        ``"bear"`` or ``"none"``.  When the feature flag is OFF the
        detector returns the neutral block.
    """
    neutral = {
        "SMT_DIVERGENCE_DETECTED": False,
        "SMT_DIVERGENCE_SIDE": "none",
        "SMT_DIVERGENCE_CONFIDENCE": 0,
    }

    if not smt_divergence_enabled():
        return neutral

    enr = enrichment or {}

    ssl = enr.get("structure_state_light") or {}
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", "NONE")).upper()
    primary_bull = last_event in ("BOS_BULL", "CHOCH_BULL")
    primary_bear = last_event in ("BOS_BEAR", "CHOCH_BEAR")

    if not (primary_bull or primary_bear):
        return neutral

    cc = enr.get("correlated_context") or {}
    corr_bias = str(cc.get("CORRELATED_BIAS", "NEUTRAL")).upper()
    corr_event = str(cc.get("CORRELATED_LAST_EVENT", "NONE")).upper()
    corr_bull = corr_bias == "BULLISH" or corr_event in ("BOS_BULL", "CHOCH_BULL")
    corr_bear = corr_bias == "BEARISH" or corr_event in ("BOS_BEAR", "CHOCH_BEAR")

    if primary_bull and corr_bear:
        return {
            "SMT_DIVERGENCE_DETECTED": True,
            "SMT_DIVERGENCE_SIDE": "bear",
            "SMT_DIVERGENCE_CONFIDENCE": smt_divergence_config.confidence,
        }

    if primary_bear and corr_bull:
        return {
            "SMT_DIVERGENCE_DETECTED": True,
            "SMT_DIVERGENCE_SIDE": "bull",
            "SMT_DIVERGENCE_CONFIDENCE": smt_divergence_config.confidence,
        }

    return neutral

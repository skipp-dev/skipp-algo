"""Phase E — SMT / Correlation Divergence Layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

from smc_core.v2_config import smt_divergence_config
from smc_core.v2_features import smt_divergence_enabled


class SMTPair(NamedTuple):
    """A pair of instruments to monitor for SMT divergence."""

    base_symbol: str
    corr_symbol: str


KNOWN_SMT_PAIRS: list[SMTPair] = [
    SMTPair("XAUUSD", "XAGUSD"),
    SMTPair("BTCUSD", "ETHUSD"),
    SMTPair("US100", "US500"),
    SMTPair("EURUSD", "GBPUSD"),
]


@dataclass(frozen=True, slots=True)
class SMTDivergenceResult:
    """SMT divergence descriptor for the core classifier API."""

    pair_corr_window: int
    pair_corr_value: float
    smt_high_divergence: bool
    smt_low_divergence: bool
    smt_strength: float


def classify_smt_divergence(
    *,
    base_symbol: str,
    corr_symbol: str,
    base_bars: object,
    corr_bars: object,
    window: int = 20,
) -> SMTDivergenceResult:
    """Classify SMT divergence between two symbols (Phase E.0 pending)."""
    raise NotImplementedError(
        "classify_smt_divergence is not yet implemented. Complete Phase E.0 "
        "(correlated-pair data feed in open_prep/realtime_signals.py) before "
        "enabling ENABLE_SMT_DIVERGENCE."
    )


def detect_smt_divergence(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detector-style SMT divergence signal used by v2 integration tests."""
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

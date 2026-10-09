"""Bridge between open_prep.regime.RegimeSnapshot and smc_core.types.MarketRegimeContext.

Keeps open_prep as an optional dependency — if unavailable, or if the snapshot
is None, the adapter returns None and downstream layering runs without regime
context.
"""
from __future__ import annotations

from typing import Any

from smc_core.types import MarketRegime, MarketRegimeContext

_VALID_REGIMES: set[str] = {"RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL"}


def regime_snapshot_to_context(snapshot: Any) -> MarketRegimeContext | None:
    """Convert an open_prep RegimeSnapshot (or compatible dict) to MarketRegimeContext.

    Accepts either a RegimeSnapshot dataclass or a plain dict with at least
    a ``regime`` key.  Returns ``None`` for unknown/invalid inputs so the
    caller never has to import open_prep types.
    """
    if snapshot is None:
        return None

    # Support dict form (e.g. from JSON or test fixtures)
    if isinstance(snapshot, dict):
        regime_str = str(snapshot.get("regime", "")).upper()
        if regime_str not in _VALID_REGIMES:
            return None
        regime: MarketRegime = regime_str  # type: ignore[assignment]
        vix = snapshot.get("vix_level")
        breadth = snapshot.get("sector_breadth", 0.5)
        return MarketRegimeContext(
            regime=regime,
            vix_level=float(vix) if vix is not None else None,
            sector_breadth=float(breadth),
        )

    # Dataclass / object form — duck-type on .regime attribute
    regime_str = str(getattr(snapshot, "regime", "")).upper()
    if regime_str not in _VALID_REGIMES:
        return None
    regime = regime_str  # type: ignore[assignment]
    vix = getattr(snapshot, "vix_level", None)
    breadth = getattr(snapshot, "sector_breadth", 0.5)
    return MarketRegimeContext(
        regime=regime,
        vix_level=float(vix) if vix is not None else None,
        sector_breadth=float(breadth),
    )

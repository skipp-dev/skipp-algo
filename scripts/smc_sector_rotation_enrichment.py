"""Sector rotation detail enrichment for SMC micro-profile generation."""
from __future__ import annotations

from typing import Any


def compute_sector_rotation(sector_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank sectors by performance and identify rotation.

    Parameters
    ----------
    sector_data:
        Output of ``fmp.get_sector_performance()`` — each dict has
        ``sector`` and ``changesPercentage``.
    """
    if not sector_data:
        return {
            "sector_leading": [],
            "sector_lagging": [],
            "sector_strongest": "",
            "sector_weakest": "",
        }

    def _change(s: dict[str, Any]) -> float:
        try:
            return float(s.get("changesPercentage") or 0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(sector_data, key=_change, reverse=True)
    names = [str(s.get("sector", "")).strip() for s in ranked if str(s.get("sector", "")).strip()]

    return {
        "sector_leading": names[:3],
        "sector_lagging": list(reversed(names[-3:])) if len(names) >= 3 else list(names),
        "sector_strongest": names[0] if names else "",
        "sector_weakest": names[-1] if names else "",
    }

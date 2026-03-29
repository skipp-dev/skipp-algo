"""V5.1 Zone Intelligence builder.

Derives a zone context block from support/resistance lifecycle data
in the base snapshot.  Concepts: entries/tests, sweeps,
mitigation/break, duration, traded volume.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_zone_intelligence import build_zone_intelligence, DEFAULTS

    zones = build_zone_intelligence(snapshot=base_snapshot_df)
    enrichment["zone_intelligence"] = zones
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "ACTIVE_SUPPORT_COUNT": 0,
    "ACTIVE_RESISTANCE_COUNT": 0,
    "ACTIVE_ZONE_COUNT": 0,
    "PRIMARY_SUPPORT_LEVEL": 0.0,
    "PRIMARY_RESISTANCE_LEVEL": 0.0,
    "PRIMARY_SUPPORT_STRENGTH": 0,
    "PRIMARY_RESISTANCE_STRENGTH": 0,
    "SUPPORT_SWEEP_COUNT": 0,
    "RESISTANCE_SWEEP_COUNT": 0,
    "SUPPORT_MITIGATION_PCT": 0.0,
    "RESISTANCE_MITIGATION_PCT": 0.0,
    "ZONE_CONTEXT_BIAS": "NEUTRAL",        # SUPPORT_HEAVY | RESISTANCE_HEAVY | NEUTRAL
    "ZONE_LIQUIDITY_IMBALANCE": 0.0,       # -1..+1  (negative = more resistance liquidity)
}

# ── Thresholds ──────────────────────────────────────────────────────

SUPPORT_HEAVY_THRESHOLD = 2     # min support excess over resistance
RESISTANCE_HEAVY_THRESHOLD = 2  # min resistance excess over support


def build_zone_intelligence(
    *,
    snapshot: pd.DataFrame | None = None,
    zones: list[dict[str, Any]] | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a zone intelligence block.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with per-symbol zone summary columns.
    zones : list[dict], optional
        Explicit zone records with keys: ``type`` (support/resistance),
        ``level``, ``strength``, ``tests``, ``sweeps``, ``mitigated``,
        ``duration_bars``, ``volume``.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    zone_list = zones
    if zone_list is None and snapshot is not None and not snapshot.empty:
        zone_list = _extract_zones_from_snapshot(snapshot, symbol)

    if zone_list:
        supports = [z for z in zone_list if z.get("type") == "support"]
        resistances = [z for z in zone_list if z.get("type") == "resistance"]

        # Active counts
        result["ACTIVE_SUPPORT_COUNT"] = len(supports)
        result["ACTIVE_RESISTANCE_COUNT"] = len(resistances)
        result["ACTIVE_ZONE_COUNT"] = len(zone_list)

        # Primary levels (strongest by strength, then by test count)
        if supports:
            primary_sup = max(supports, key=lambda z: (z.get("strength", 0), z.get("tests", 0)))
            result["PRIMARY_SUPPORT_LEVEL"] = round(float(primary_sup.get("level", 0)), 2)
            result["PRIMARY_SUPPORT_STRENGTH"] = int(primary_sup.get("strength", 0))

        if resistances:
            primary_res = max(resistances, key=lambda z: (z.get("strength", 0), z.get("tests", 0)))
            result["PRIMARY_RESISTANCE_LEVEL"] = round(float(primary_res.get("level", 0)), 2)
            result["PRIMARY_RESISTANCE_STRENGTH"] = int(primary_res.get("strength", 0))

        # Sweep counts
        result["SUPPORT_SWEEP_COUNT"] = sum(int(z.get("sweeps", 0)) for z in supports)
        result["RESISTANCE_SWEEP_COUNT"] = sum(int(z.get("sweeps", 0)) for z in resistances)

        # Mitigation percentages
        result["SUPPORT_MITIGATION_PCT"] = _mitigation_pct(supports)
        result["RESISTANCE_MITIGATION_PCT"] = _mitigation_pct(resistances)

        # Context bias
        sup_count = len(supports)
        res_count = len(resistances)
        if sup_count - res_count >= SUPPORT_HEAVY_THRESHOLD:
            result["ZONE_CONTEXT_BIAS"] = "SUPPORT_HEAVY"
        elif res_count - sup_count >= RESISTANCE_HEAVY_THRESHOLD:
            result["ZONE_CONTEXT_BIAS"] = "RESISTANCE_HEAVY"
        else:
            result["ZONE_CONTEXT_BIAS"] = "NEUTRAL"

        # Liquidity imbalance: normalized delta of total zone volume
        sup_vol = sum(float(z.get("volume", 0)) for z in supports)
        res_vol = sum(float(z.get("volume", 0)) for z in resistances)
        total_vol = sup_vol + res_vol
        if total_vol > 0:
            result["ZONE_LIQUIDITY_IMBALANCE"] = round(
                (sup_vol - res_vol) / total_vol, 4
            )

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Helpers ─────────────────────────────────────────────────────────


def _extract_zones_from_snapshot(
    df: pd.DataFrame, symbol: str
) -> list[dict[str, Any]]:
    """Extract zone records from snapshot columns if present."""
    # Look for zone summary columns in the snapshot
    if "zones_json" in df.columns:
        import json
        if symbol and "symbol" in df.columns:
            match = df.loc[df["symbol"] == symbol]
            if not match.empty:
                raw = match.iloc[0]["zones_json"]
                try:
                    return json.loads(raw) if isinstance(raw, str) else []
                except (json.JSONDecodeError, TypeError):
                    return []
        if len(df) == 1:
            raw = df.iloc[0]["zones_json"]
            try:
                return json.loads(raw) if isinstance(raw, str) else []
            except (json.JSONDecodeError, TypeError):
                return []
    return []


def _mitigation_pct(zones: list[dict[str, Any]]) -> float:
    """Percentage of zones that are mitigated."""
    if not zones:
        return 0.0
    mitigated = sum(1 for z in zones if z.get("mitigated", False))
    return round(mitigated / len(zones) * 100.0, 1)

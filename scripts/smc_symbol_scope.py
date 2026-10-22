"""Restrict a snapshot to the rows of one symbol before treating its rows as a bar series.

The bar-series enrichment builders (structure state, imbalance lifecycle, session
structure, range regime, range profile regime) read consecutive rows as consecutive
bars. Called without a symbol on a snapshot that holds several symbols, they would
read the rows of different symbols as one series — a cross-symbol write. The global
Pine library has no chart symbol, so the generator calls them exactly that way
(``symbol=""`` on the universe snapshot, one row per symbol). ``scope_to_symbol``
returns no rows in that case, so the builders fall back to their defaults instead.
"""
from __future__ import annotations

import pandas as pd


def scope_to_symbol(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Rows of ``symbol``; without a symbol only a single-symbol frame passes, otherwise no rows."""
    if "symbol" not in df.columns:
        return df
    if symbol:
        return df[df["symbol"] == symbol]
    if df["symbol"].nunique(dropna=True) <= 1:
        return df
    return df.iloc[0:0]


def snapshot_symbol_count(df: pd.DataFrame | None) -> int:
    """Distinct symbols in a snapshot (0 for none/empty, 1 when there is no symbol column)."""
    if df is None or df.empty:
        return 0
    if "symbol" not in df.columns:
        return 1
    return int(df["symbol"].nunique(dropna=True))


# Enrichment families whose builders read one symbol's row (or bar series) of the
# snapshot. Their symbol-dependent fields cannot be computed for the global library.
PER_SYMBOL_FAMILIES: tuple[str, ...] = (
    "flow_qualifier", "compression_regime", "zone_intelligence", "reversal_context",
    "session_context", "liquidity_sweeps", "liquidity_pools", "order_blocks",
    "zone_projection", "profile_context", "structure_state", "imbalance_lifecycle",
    "session_structure", "range_regime", "range_profile_regime",
)


def per_symbol_scope_diagnostic(snapshot: pd.DataFrame | None, families: list[str]) -> dict | None:
    """Diagnostic for ``enrichment["_diagnostics"]["per_symbol_scope"]``, or None when nothing is affected.

    The global library is built from the universe snapshot without a chart symbol; with more
    than one symbol in it the symbol-dependent fields of ``families`` stay at their defaults.
    """
    n = snapshot_symbol_count(snapshot)
    affected = [f for f in families if f in PER_SYMBOL_FAMILIES]
    if n <= 1 or not affected:
        return None
    return {
        "status": "not_computed",
        "reason": "global library has no chart symbol; symbol-dependent fields stay at their defaults",
        "symbols_in_snapshot": n,
        "families": affected,
    }

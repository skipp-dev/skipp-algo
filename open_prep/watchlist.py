"""Persistent watchlist: file-based storage for pinned symbols and notes.

Watchlist entries are stored in ``artifacts/open_prep/watchlist.json``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("open_prep.watchlist")

WATCHLIST_PATH = Path("artifacts/open_prep/watchlist.json")


def _load_raw() -> list[dict[str, Any]]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning("Failed to load watchlist, returning empty")
        return []


def _save_raw(entries: list[dict[str, Any]]) -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(entries, indent=2, default=str)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=WATCHLIST_PATH.parent, suffix=".tmp", prefix="watchlist_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, WATCHLIST_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_watchlist() -> list[dict[str, Any]]:
    """Load the persistent watchlist.

    Each entry::

        {
            "symbol": "NVDA",
            "added_at": "2025-06-20T08:30:00",
            "note": "strong accumulation pattern",
            "source": "manual" | "auto",
        }
    """
    return _load_raw()


def add_to_watchlist(
    symbol: str,
    note: str = "",
    source: str = "manual",
) -> list[dict[str, Any]]:
    """Add a symbol to the watchlist (no duplicates)."""
    entries = _load_raw()
    symbols = {e["symbol"] for e in entries}
    if symbol.upper() in symbols:
        logger.info("%s already on watchlist", symbol)
        return entries

    entries.append({
        "symbol": symbol.upper(),
        "added_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "source": source,
    })
    _save_raw(entries)
    logger.info("Added %s to watchlist (%d total)", symbol, len(entries))
    return entries


def remove_from_watchlist(symbol: str) -> list[dict[str, Any]]:
    """Remove a symbol from the watchlist."""
    entries = _load_raw()
    before = len(entries)
    entries = [e for e in entries if e["symbol"] != symbol.upper()]
    _save_raw(entries)
    removed = before - len(entries)
    if removed:
        logger.info("Removed %s from watchlist", symbol)
    return entries


def update_note(symbol: str, note: str) -> list[dict[str, Any]]:
    """Update the note for a watchlist entry."""
    entries = _load_raw()
    for e in entries:
        if e["symbol"] == symbol.upper():
            e["note"] = note
            break
    _save_raw(entries)
    return entries


def auto_add_high_conviction(
    ranked: list[dict[str, Any]],
    min_tier: str = "HIGH_CONVICTION",
) -> int:
    """Automatically add HIGH_CONVICTION candidates to watchlist.

    Returns the number of newly added symbols.
    """
    entries = _load_raw()
    existing = {e["symbol"] for e in entries}
    added = 0

    for row in ranked:
        tier = row.get("confidence_tier", "")
        if tier == min_tier:
            sym = str(row.get("symbol", "")).upper()
            if sym and sym not in existing:
                entries.append({
                    "symbol": sym,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "note": f"Auto-added: score={row.get('score', 0):.2f}, gap={row.get('gap_pct', 0):.1f}%",
                    "source": "auto",
                })
                existing.add(sym)
                added += 1

    if added:
        _save_raw(entries)
        logger.info("Auto-added %d HIGH_CONVICTION symbol(s) to watchlist", added)
    return added


def get_watchlist_symbols() -> set[str]:
    """Return just the set of watchlist symbols for quick lookup."""
    return {e["symbol"] for e in _load_raw()}

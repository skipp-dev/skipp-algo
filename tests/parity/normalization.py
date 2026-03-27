"""Explicit normalization rules for comparing canonical ↔ bridge ↔ TV payloads.

Each rule is documented inline. No fuzzy matching — only exact, approved
transformations are allowed.
"""
from __future__ import annotations

from typing import Any


# ── Required fields per pine payload entity type ──────────────────
# If a new field is added to the pine payload, it must be registered here
# or the required-field parity test will fail.

PINE_REQUIRED_BOS_FIELDS: set[str] = {"id", "time", "price", "kind", "dir", "style"}
PINE_REQUIRED_OB_FIELDS: set[str] = {"id", "low", "high", "dir", "valid", "style"}
PINE_REQUIRED_FVG_FIELDS: set[str] = {"id", "low", "high", "dir", "valid", "style"}
PINE_REQUIRED_SWEEP_FIELDS: set[str] = {"id", "time", "price", "side", "style"}


# ── Normalization: canonical structure dict → comparable form ──────

# The canonical builder returns dicts with extra fields the bridge
# does NOT carry (e.g. anchor_ts on orderblocks).  These are the
# allowed extra fields that may be silently dropped during bridge
# ingestion.  If a new field appears in the canonical output but
# not in the bridge, it must be added here explicitly or the parity
# test will fail.
_CANONICAL_EXTRA_BOS_FIELDS: set[str] = {"source"}
_CANONICAL_EXTRA_OB_FIELDS: set[str] = {"anchor_ts", "source"}
_CANONICAL_EXTRA_FVG_FIELDS: set[str] = {"anchor_ts", "source"}
_CANONICAL_EXTRA_SWEEP_FIELDS: set[str] = {"source", "source_liquidity_id"}


def _strip_extras(item: dict[str, Any], extras: set[str]) -> dict[str, Any]:
    """Return a copy of *item* with *extras* keys removed."""
    return {k: v for k, v in item.items() if k not in extras}


def normalize_canonical_bos(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [_strip_extras(i, _CANONICAL_EXTRA_BOS_FIELDS) for i in items],
        key=lambda x: x["id"],
    )


def normalize_canonical_ob(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [_strip_extras(i, _CANONICAL_EXTRA_OB_FIELDS) for i in items],
        key=lambda x: x["id"],
    )


def normalize_canonical_fvg(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [_strip_extras(i, _CANONICAL_EXTRA_FVG_FIELDS) for i in items],
        key=lambda x: x["id"],
    )


def normalize_canonical_sweeps(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [_strip_extras(i, _CANONICAL_EXTRA_SWEEP_FIELDS) for i in items],
        key=lambda x: x["id"],
    )


# ── Normalization: bridge SmcStructure → comparable dicts ──────

def bridge_bos_to_dicts(bos_events: list) -> list[dict[str, Any]]:
    """Convert list of BosEvent dataclasses to sorted dicts."""
    return sorted(
        [{"id": e.id, "time": e.time, "price": e.price, "kind": e.kind, "dir": e.dir} for e in bos_events],
        key=lambda x: x["id"],
    )


def bridge_ob_to_dicts(obs: list) -> list[dict[str, Any]]:
    return sorted(
        [{"id": o.id, "low": o.low, "high": o.high, "dir": o.dir, "valid": o.valid} for o in obs],
        key=lambda x: x["id"],
    )


def bridge_fvg_to_dicts(fvgs: list) -> list[dict[str, Any]]:
    return sorted(
        [{"id": f.id, "low": f.low, "high": f.high, "dir": f.dir, "valid": f.valid} for f in fvgs],
        key=lambda x: x["id"],
    )


def bridge_sweep_to_dicts(sweeps: list) -> list[dict[str, Any]]:
    return sorted(
        [{"id": s.id, "time": s.time, "price": s.price, "side": s.side} for s in sweeps],
        key=lambda x: x["id"],
    )


# ── Normalization: pine payload entries → comparable dicts ──────
# Pine payload entries have an extra "style" key injected by layering.
# For structure-level parity we strip it.

_PINE_STYLE_KEY = "style"


def strip_pine_style(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove the 'style' enrichment from pine payload entries."""
    return sorted(
        [{k: v for k, v in i.items() if k != _PINE_STYLE_KEY} for i in items],
        key=lambda x: x["id"],
    )


# ── TV pipe-encoding verification helpers ──────


def decode_tv_bos(encoded: str) -> list[dict[str, Any]]:
    """Parse pipe-encoded BOS string → list of dicts."""
    if not encoded:
        return []
    entries: list[dict[str, Any]] = []
    for segment in encoded.split(";"):
        parts = segment.split("|")
        entries.append({"time": int(parts[0]), "price": float(parts[1]), "dir": parts[2]})
    return sorted(entries, key=lambda x: x["time"])


def decode_tv_zones(encoded: str) -> list[dict[str, Any]]:
    """Parse pipe-encoded OB/FVG string → list of dicts."""
    if not encoded:
        return []
    entries: list[dict[str, Any]] = []
    for segment in encoded.split(";"):
        parts = segment.split("|")
        entries.append({"low": float(parts[0]), "high": float(parts[1]), "dir": parts[2], "valid": bool(int(parts[3]))})
    return sorted(entries, key=lambda x: (x["low"], x["high"]))


def decode_tv_sweeps(encoded: str) -> list[dict[str, Any]]:
    """Parse pipe-encoded sweeps string → list of dicts."""
    if not encoded:
        return []
    entries: list[dict[str, Any]] = []
    for segment in encoded.split(";"):
        parts = segment.split("|")
        entries.append({"time": int(parts[0]), "price": float(parts[1]), "side": parts[2]})
    return sorted(entries, key=lambda x: x["time"])

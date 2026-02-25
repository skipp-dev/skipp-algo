"""Diff view: compare previous open-prep result with the current one.

Shows which candidates are new, dropped, changed score significantly,
or experienced sector rotation.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .utils import to_float

logger = logging.getLogger("open_prep.diff")

try:
    SCORE_CHANGE_THRESHOLD = max(
        float(os.environ.get("OPEN_PREP_DIFF_SCORE_THRESHOLD", "0.5") or "0.5"),
        0.01,
    )
except (ValueError, TypeError):
    SCORE_CHANGE_THRESHOLD = 0.5

LAST_RESULT_PATH = Path("artifacts/open_prep/last_result.json")


# ---------------------------------------------------------------------------
# Persistence for the *previous* run
# ---------------------------------------------------------------------------

def save_result_snapshot(result: dict[str, Any]) -> Path:
    """Persist a lean snapshot of the result for next-run diff.

    Stores only the fields relevant for comparison to keep the file small.
    """
    LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

    snapshot: dict[str, Any] = {
        "ts": result.get("generated_at"),
        "regime": result.get("regime"),
        "candidates": [],
    }
    for c in result.get("candidates", []):
        snapshot["candidates"].append({
            "symbol": c.get("symbol"),
            "gap_pct": c.get("gap_pct"),
            "score": c.get("score"),
            "confidence_tier": c.get("confidence_tier"),
            "sector": c.get("symbol_sector") or c.get("sector"),
        })

    # Atomic write: tmp file + os.replace to avoid half-written files on crash.
    fd, tmp_path = tempfile.mkstemp(
        dir=LAST_RESULT_PATH.parent, suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, LAST_RESULT_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return LAST_RESULT_PATH


def load_previous_snapshot() -> dict[str, Any] | None:
    """Load the previous run snapshot, or None if unavailable."""
    if not LAST_RESULT_PATH.exists():
        return None
    try:
        with open(LAST_RESULT_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.warning("Failed to load previous snapshot")
        return None


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def compute_diff(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compute a structured diff between previous and current runs.

    Returns::

        {
            "has_changes": bool,
            "new_entrants": [...],
            "dropped": [...],
            "score_changes": [...],
            "regime_change": {"from": ..., "to": ...} | None,
            "sector_rotations": [...],
        }
    """
    if previous is None:
        return {
            "has_changes": True,
            "new_entrants": [c.get("symbol") for c in current.get("candidates", [])],
            "dropped": [],
            "score_changes": [],
            "regime_change": None,
            "sector_rotations": [],
            "first_run": True,
        }

    prev_syms = {
        str(c.get("symbol") or "").strip().upper(): c
        for c in previous.get("candidates", [])
        if str(c.get("symbol") or "").strip()
    }
    curr_syms = {
        str(c.get("symbol") or "").strip().upper(): c
        for c in current.get("candidates", [])
        if str(c.get("symbol") or "").strip()
    }

    prev_set = set(prev_syms.keys())
    curr_set = set(curr_syms.keys())

    new_entrants = sorted(curr_set - prev_set)
    dropped = sorted(prev_set - curr_set)

    # Score changes for symbols present in both
    score_changes: list[dict[str, Any]] = []
    for sym in sorted(prev_set & curr_set):
        prev_score = to_float(prev_syms[sym].get("score"))
        curr_score = to_float(curr_syms[sym].get("score"))
        delta = curr_score - prev_score
        if abs(delta) >= SCORE_CHANGE_THRESHOLD:  # Only show meaningful changes
            score_changes.append({
                "symbol": sym,
                "prev_score": round(prev_score, 2),
                "curr_score": round(curr_score, 2),
                "delta": round(delta, 2),
                "direction": "↑" if delta > 0 else "↓",
            })

    # Regime change
    prev_regime = previous.get("regime")
    curr_regime = current.get("regime")
    regime_change = None
    if prev_regime and curr_regime and prev_regime != curr_regime:
        regime_change = {"from": prev_regime, "to": curr_regime}

    # Sector rotations: sectors that lost or gained candidates
    prev_sectors: dict[str, int] = {}
    for c in previous.get("candidates", []):
        s = str(c.get("symbol_sector") or c.get("sector") or "Unknown")
        prev_sectors[s] = prev_sectors.get(s, 0) + 1

    curr_sectors: dict[str, int] = {}
    for c in current.get("candidates", []):
        s = str(c.get("symbol_sector") or c.get("sector") or "Unknown")
        curr_sectors[s] = curr_sectors.get(s, 0) + 1

    all_sectors = set(prev_sectors.keys()) | set(curr_sectors.keys())
    sector_rotations: list[dict[str, Any]] = []
    for sector in sorted(all_sectors):
        prev_n = prev_sectors.get(sector, 0)
        curr_n = curr_sectors.get(sector, 0)
        if prev_n != curr_n:
            sector_rotations.append({
                "sector": sector,
                "prev_count": prev_n,
                "curr_count": curr_n,
                "delta": curr_n - prev_n,
            })

    has_changes = bool(new_entrants or dropped or score_changes or regime_change or sector_rotations)

    return {
        "has_changes": has_changes,
        "new_entrants": new_entrants,
        "dropped": dropped,
        "score_changes": score_changes,
        "regime_change": regime_change,
        "sector_rotations": sector_rotations,
        "first_run": False,
    }


def format_diff_summary(diff: dict[str, Any]) -> str:
    """Produce a human-readable summary of the diff."""
    if diff.get("first_run"):
        n = len(diff.get("new_entrants", []))
        return f"First run — {n} candidate(s) identified."

    if not diff.get("has_changes"):
        return "No meaningful changes since last run."

    parts: list[str] = []

    regime = diff.get("regime_change")
    if regime:
        parts.append(f"⚠️ Regime changed: {regime['from']} → {regime['to']}")

    new = diff.get("new_entrants", [])
    if new:
        parts.append(f"🆕 New entrants ({len(new)}): {', '.join(new[:8])}")

    dropped = diff.get("dropped", [])
    if dropped:
        parts.append(f"❌ Dropped ({len(dropped)}): {', '.join(dropped[:8])}")

    score_ch = diff.get("score_changes", [])
    if score_ch:
        lines = [f"  {c['symbol']} {c['direction']} {c['delta']:+.2f}" for c in score_ch[:6]]
        parts.append("📊 Score changes:\n" + "\n".join(lines))

    rotations = diff.get("sector_rotations", [])
    if rotations:
        lines = [f"  {r['sector']}: {r['prev_count']}→{r['curr_count']}" for r in rotations[:6]]
        parts.append("🔄 Sector rotation:\n" + "\n".join(lines))

    return "\n".join(parts)

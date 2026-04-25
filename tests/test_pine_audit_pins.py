"""Pine-script audit pins (defense-only):

1. **Same-TF `request.security` zero-tripwire** — bans the silent-no-op
   pattern ``request.security(syminfo.tickerid, timeframe.period, ...)``
   where the security call uses the current chart's symbol *and*
   timeframe (yields the same bar that's already on the chart, just
   pays the cross-script latency cost).

2. **Pine legacy root-tripwire** — the 23 legacy ``.pine`` scripts have
   been moved under ``pine/legacy/`` (not part of the active
   SMC-engine surface). This pin ensures none of those filenames
   reappear at the repository root.

Both are zero-inventory tripwires.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_SAME_TF_RE = re.compile(
    r"request\.security\s*\(\s*syminfo\.tickerid\s*,\s*timeframe\.period\b",
)

_LEGACY_FILENAMES = frozenset(
    {
        "BFI-Reversal.pine",
        "BTC 3m EV Scalper BALANCED (Harmonized).pine",
        "Breakout_Finder_Intelligent.pine",
        "CHOCH-Base_Indikator.pine",
        "CHOCH-Base_Strategy.pine",
        "CHOCH-Indicator.pine",
        "CHOCH-Strategy.pine",
        "CHoCH.pine",
        "QuickALGO.pine",
        "REV-BUY.pine",
        "REV-Ladder-CHoCH.pine",
        "REV-Ladder.pine",
        "USI-CHOCH.pine",
        "USI-Flip.pine",
        "USI-REV-BUY.pine",
        "USI.pine",
        "USI_Lines.pine",
        "USI_Strategy.pine",
        "VWAP_Long_Reclaim_Indicator.pine",
        "VWAP_Long_Reclaim_Strategy.pine",
        "VWAP_Reclaim_Indicator.pine",
        "VWAP_Reclaim_Strategy.pine",
        "Volume_Weighted_Trend_SkippAlgo.pine",
    }
)


def _iter_pine_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.pine"):
        # Skip vendor/cache directories
        parts = path.relative_to(_REPO_ROOT).parts
        if any(p in {".git", ".venv", "venv", "node_modules"} for p in parts):
            continue
        out.append(path)
    return sorted(out)


def test_no_same_tf_request_security_calls() -> None:
    """``request.security(syminfo.tickerid, timeframe.period, ...)`` is a
    silent no-op pattern: same symbol + same timeframe just returns the
    current bar's value. Use the source expression directly."""
    hits: list[tuple[str, int, str]] = []
    for path in _iter_pine_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _SAME_TF_RE.search(line):
                hits.append((rel, lineno, line.strip()))
    assert not hits, (
        "Same-TF `request.security(syminfo.tickerid, timeframe.period, ...)` "
        "is a silent no-op (same symbol + same timeframe). Use the source "
        "expression directly:\n  - "
        + "\n  - ".join(f"{f}:{ln}  {snip[:120]}" for f, ln, snip in hits)
    )


def test_no_legacy_pine_at_repo_root() -> None:
    """The 23 legacy Pine scripts were moved under ``pine/legacy/``. None
    of those filenames may reappear at the repository root."""
    intruders = sorted(
        name for name in _LEGACY_FILENAMES if (_REPO_ROOT / name).exists()
    )
    assert not intruders, (
        "Legacy Pine filename(s) reappeared at repo root — they belong under "
        "`pine/legacy/`:\n  - " + "\n  - ".join(intruders)
    )


def test_legacy_inventory_still_lives_under_pine_legacy() -> None:
    """Bidirectional sanity: every name in the legacy inventory must still
    exist under ``pine/legacy/`` so the tripwire keeps measuring something
    real (catches silent deletions of the legacy folder)."""
    legacy_dir = _REPO_ROOT / "pine" / "legacy"
    missing = sorted(
        name for name in _LEGACY_FILENAMES if not (legacy_dir / name).exists()
    )
    assert not missing, (
        "Legacy inventory references missing file(s) under `pine/legacy/` "
        "— update the ledger if the file was intentionally retired:\n  - "
        + "\n  - ".join(missing)
    )


def test_pine_file_inventory_sane() -> None:
    files = _iter_pine_files()
    assert len(files) >= 30, (
        f"Pine-file scan only found {len(files)} files — repo layout drift?"
    )

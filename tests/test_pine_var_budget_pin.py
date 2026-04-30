"""Pin: Pine Script ``var`` / ``varip`` declaration budget per file.

Rationale
---------
``var`` and ``varip`` declarations in Pine Script allocate persistent
runtime state. Beyond a certain count per file:

- The single-script Pine compiler hits internal limits.
- Code becomes hard to audit (state surface explodes).
- Refactor into a library or split into context modules is overdue.

This pin freezes the **current** per-file declaration count as a hard
upper bound. Adding new ``var`` / ``varip`` statements to any locked
file requires a deliberate ledger update. New ``.pine`` files carry no
budget initially (default budget = caller's choice; here we track only
files that have ≥1 declaration today).

A separate global-total budget catches "I'll just add a new file" drift.

Detection
---------
Regex: ``^\\s*(?:var|varip)\\s+\\w`` (multiline). This matches the
canonical declaration form used throughout the codebase. It does *not*
match in-line uses of the words "var" / "varip" inside expressions
because those are never at line start in this repo's Pine style.

Excluded directories: ``.git``, ``.venv``, ``venv``, ``node_modules``,
``artifacts``, ``docs``, ``SMC++``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "artifacts",
        "docs",
        "SMC++",
    }
)

_DECL_RE = re.compile(r"^\s*(?:var|varip)\s+\w", re.MULTILINE)


# Frozen ledger: file path (relative to repo root, forward-slash) → max
# allowed ``var`` / ``varip`` declaration count. Captured 2026-04-25.
_FROZEN_LEDGER: dict[str, int] = {
    "SMC_Breakout_Overlay.pine": 32,
    "SMC_Core_Engine.pine": 415,
    # 27 → 34 (2026-04-30, commit 68e1aac0): Trade-Mgmt rows in
    # Mobile_Dashboard mirrored extra var/varip state into SMC_Dashboard.
    # Re-frozen here as part of v3 phase 1 pine-consumer-discipline fix.
    "SMC_Dashboard.pine": 34,
    "SMC_Event_Overlay.pine": 13,
    "SMC_Exit_Signal.pine": 13,
    "SMC_HTF_Confluence.pine": 8,
    "SMC_Hold_Manager.pine": 10,
    "SMC_Imbalance_Context.pine": 14,
    "SMC_Liquidity_Context.pine": 12,
    "SMC_Liquidity_Structure.pine": 9,
    "SMC_Long_Strategy.pine": 19,
    # 9 → 16 (2026-04-30, commit 68e1aac0): Trade-Mgmt rows feature added
    # 7 var declarations to track per-row state. Ledger re-frozen.
    "SMC_Mobile_Dashboard.pine": 16,
    "SMC_Orderflow_Overlay.pine": 10,
    "SMC_Profile_Context.pine": 11,
    "SMC_Session_Context.pine": 11,
    "SMC_Setup_Check.pine": 2,
    "SMC_Structure_Context.pine": 10,
    "SMC_TV_Bridge.pine": 3,
    "SMC_VRVP_Overlay.pine": 55,
    "SkippALGO_Confluence.pine": 7,
    "pine/legacy/BFI-Reversal.pine": 37,
    "pine/legacy/BTC 3m EV Scalper BALANCED (Harmonized).pine": 6,
    "pine/legacy/Breakout_Finder_Intelligent.pine": 6,
    "pine/legacy/CHOCH-Base_Indikator.pine": 7,
    "pine/legacy/CHOCH-Base_Strategy.pine": 15,
    "pine/legacy/CHOCH-Indicator.pine": 6,
    "pine/legacy/CHOCH-Strategy.pine": 11,
    "pine/legacy/CHoCH.pine": 7,
    "pine/legacy/QuickALGO.pine": 82,
    "pine/legacy/REV-BUY.pine": 3,
    "pine/legacy/REV-Ladder-CHoCH.pine": 7,
    "pine/legacy/REV-Ladder.pine": 14,
    "pine/legacy/USI-CHOCH.pine": 13,
    "pine/legacy/USI_Strategy.pine": 2,
    "pine/legacy/VWAP_Long_Reclaim_Indicator.pine": 12,
    "pine/legacy/VWAP_Long_Reclaim_Strategy.pine": 13,
    "pine/legacy/VWAP_Reclaim_Indicator.pine": 17,
    "pine/legacy/VWAP_Reclaim_Strategy.pine": 19,
    "pine/legacy/Volume_Weighted_Trend_SkippAlgo.pine": 3,
    "test_div.pine": 2,
}

_TOTAL_BUDGET = 986  # bumped 2026-04-30 (audit cascade from F-04 PR #1924) for 4 SMC overlay/exit/hold/VRVP files (+32 +13 +10 +55 = +110); was 876 (v3 phase 1).


def _iter_pine() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.pine")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _count_decls(path: Path) -> int:
    src = path.read_text(encoding="utf-8", errors="replace")
    return len(_DECL_RE.findall(src))


def _build_observed_map() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_pine():
        rel = p.relative_to(_REPO_ROOT).as_posix()
        n = _count_decls(p)
        if n >= 1:
            out[rel] = n
    return out


def test_total_var_decl_budget_not_exceeded() -> None:
    observed = _build_observed_map()
    total = sum(observed.values())
    assert total <= _TOTAL_BUDGET, (
        f"Total Pine var/varip declarations {total} exceeds frozen "
        f"budget {_TOTAL_BUDGET}. Refactor before lifting the budget."
    )


def test_no_unledgered_pine_file_with_decls() -> None:
    """Any new ``.pine`` file containing ``var``/``varip`` must be ledgered."""
    observed = _build_observed_map()
    unledgered = sorted(set(observed.keys()) - set(_FROZEN_LEDGER.keys()))
    assert unledgered == [], (
        "New Pine file(s) with var/varip declarations not in ledger: "
        f"{unledgered}. Add them to _FROZEN_LEDGER with their current count."
    )


def test_no_stale_ledger_entries() -> None:
    """Files in the ledger must still exist (with at least 1 decl)."""
    observed = _build_observed_map()
    stale = sorted(set(_FROZEN_LEDGER.keys()) - set(observed.keys()))
    assert stale == [], (
        f"Stale ledger entries (file removed or no longer has decls): {stale}. "
        "Remove them from _FROZEN_LEDGER."
    )


@pytest.mark.parametrize(
    "rel_path,budget",
    sorted(_FROZEN_LEDGER.items()),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_per_file_var_decl_budget_not_exceeded(rel_path: str, budget: int) -> None:
    p = _REPO_ROOT / rel_path
    assert p.exists(), f"Ledger entry references missing file: {rel_path}"
    actual = _count_decls(p)
    assert actual <= budget, (
        f"{rel_path}: var/varip declaration count {actual} exceeds "
        f"frozen budget {budget}. Refactor or update ledger deliberately."
    )

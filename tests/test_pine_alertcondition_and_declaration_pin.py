"""Defense-pin: Pine ``alertcondition()`` ledger + single-declaration discipline.

Two complementary pins on top of `*.pine` artifacts:

A. ``alertcondition()`` budget ledger
   ----------------------------------
   ``alertcondition()`` exposes user-facing TradingView alert slots. New
   alerts are not free — each one expands the user-visible alert surface
   and must be added intentionally with a corresponding alert-name in the
   compile preflight. Frozen total = 35 across 6 files.

B. Single declaration per Pine file
   --------------------------------
   Every standalone Pine file must contain exactly one top-level
   ``indicator(...)``, ``strategy(...)``, or ``library(...)`` declaration.
   A second declaration would silently shadow the first and make TV's
   "Add to chart" pick the wrong one. The frozen distribution covers
   20 indicator/strategy entries (one per file).

Defense-only, no Pine code changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_PINE_GENERATED_NAMES = frozenset({"_snippet.pine"})


def _iter_pine_files() -> Iterator[Path]:
    for p in sorted(ROOT.glob("*.pine")):
        if p.name in _PINE_GENERATED_NAMES:
            continue
        yield p


def _strip_strings_and_comments(line: str) -> str:
    """Remove ``//`` comments while honouring ``"`` and ``'`` string literals."""
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(line[i])
                if line[i] == "\\" and i + 1 < n:
                    out.append(line[i + 1])
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Layer A — alertcondition ledger
# ---------------------------------------------------------------------------

_ALERTCOND_RE = re.compile(r"\balertcondition\s*\(")

_FROZEN_ALERTCOND_COUNTS: dict[str, int] = {
    "SMC_Breakout_Overlay.pine": 3,
    "SMC_Core_Engine.pine": 16,
    "SMC_Event_Overlay.pine": 2,
    "SMC_Exit_Signal.pine": 6,
    "SMC_Hold_Manager.pine": 6,
    "SkippALGO_Confluence.pine": 2,
}
_FROZEN_ALERTCOND_TOTAL = sum(_FROZEN_ALERTCOND_COUNTS.values())


def _scan_alertconditions() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_pine_files():
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = 0
        for line in src.splitlines():
            stripped = _strip_strings_and_comments(line)
            n += len(_ALERTCOND_RE.findall(stripped))
        if n:
            out[p.name] = n
    return out


def test_pine_inventory_sane() -> None:
    files = list(_iter_pine_files())
    assert len(files) >= 15, f"Pine inventory shrank: {len(files)}"


def test_alertcondition_total_frozen() -> None:
    counts = _scan_alertconditions()
    total = sum(counts.values())
    assert total == _FROZEN_ALERTCOND_TOTAL, (
        f"alertcondition() total drifted: expected {_FROZEN_ALERTCOND_TOTAL}, "
        f"got {total}; per-file = {counts}"
    )


def test_alertcondition_no_new_files() -> None:
    counts = _scan_alertconditions()
    new = sorted(set(counts) - set(_FROZEN_ALERTCOND_COUNTS))
    assert not new, (
        "New Pine files declare alertcondition() — add to ledger and "
        f"register the alert names in the compile preflight: {new}"
    )


def test_alertcondition_no_stale_entries() -> None:
    counts = _scan_alertconditions()
    stale = sorted(set(_FROZEN_ALERTCOND_COUNTS) - set(counts))
    assert not stale, (
        "Frozen alertcondition() ledger lists files with no remaining "
        f"alerts — remove from _FROZEN_ALERTCOND_COUNTS: {stale}"
    )


@pytest.mark.parametrize("name,expected", sorted(_FROZEN_ALERTCOND_COUNTS.items()))
def test_alertcondition_per_file_count(name: str, expected: int) -> None:
    counts = _scan_alertconditions()
    actual = counts.get(name, 0)
    assert actual == expected, (
        f"{name}: alertcondition() count drifted (expected {expected}, "
        f"got {actual})."
    )


@pytest.mark.parametrize("name", sorted(_FROZEN_ALERTCOND_COUNTS))
def test_alertcondition_files_exist(name: str) -> None:
    assert (ROOT / name).is_file(), f"Ledger Pine file missing: {name}"


# ---------------------------------------------------------------------------
# Layer B — single top-level declaration per Pine file
# ---------------------------------------------------------------------------

_DECL_RE = re.compile(r"^(indicator|strategy|library)\s*\(", re.MULTILINE)

# Frozen distribution: file -> declaration kind. Exactly one per file.
_FROZEN_DECL_KIND: dict[str, str] = {
    "SMC_Breakout_Overlay.pine": "indicator",
    "SMC_Core_Engine.pine": "indicator",
    "SMC_Dashboard.pine": "indicator",
    "SMC_Event_Overlay.pine": "indicator",
    "SMC_Exit_Signal.pine": "indicator",
    "SMC_HTF_Confluence.pine": "indicator",
    "SMC_Hold_Manager.pine": "indicator",
    "SMC_Imbalance_Context.pine": "indicator",
    "SMC_Liquidity_Context.pine": "indicator",
    "SMC_Liquidity_Structure.pine": "indicator",
    "SMC_Long_Strategy.pine": "strategy",
    "SMC_Mobile_Dashboard.pine": "indicator",
    "SMC_Orderflow_Overlay.pine": "indicator",
    "SMC_Profile_Context.pine": "indicator",
    "SMC_Session_Context.pine": "indicator",
    "SMC_Setup_Check.pine": "indicator",
    "SMC_Structure_Context.pine": "indicator",
    "SMC_TV_Bridge.pine": "indicator",
    "SMC_VRVP_Overlay.pine": "indicator",
    "SkippALGO_Confluence.pine": "indicator",
    "test_div.pine": "indicator",
}


def _scan_declarations() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in _iter_pine_files():
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Strip comments line-by-line first, then match.
        cleaned_lines = []
        for line in src.splitlines():
            stripped = _strip_strings_and_comments(line)
            cleaned_lines.append(stripped)
        cleaned = "\n".join(cleaned_lines)
        kinds = _DECL_RE.findall(cleaned)
        if kinds:
            out[p.name] = kinds
    return out


def test_declaration_no_new_files() -> None:
    decls = _scan_declarations()
    new = sorted(set(decls) - set(_FROZEN_DECL_KIND))
    assert not new, (
        "New Pine files contain top-level indicator/strategy/library — "
        f"append to _FROZEN_DECL_KIND: {new}"
    )


def test_declaration_no_stale_entries() -> None:
    decls = _scan_declarations()
    stale = sorted(set(_FROZEN_DECL_KIND) - set(decls))
    assert not stale, (
        "Frozen declaration ledger lists files with no remaining "
        f"declaration — remove from _FROZEN_DECL_KIND: {stale}"
    )


@pytest.mark.parametrize("name,expected_kind", sorted(_FROZEN_DECL_KIND.items()))
def test_declaration_single_and_correct_kind(name: str, expected_kind: str) -> None:
    decls = _scan_declarations()
    kinds = decls.get(name, [])
    assert len(kinds) == 1, (
        f"{name}: expected exactly 1 top-level declaration, got {len(kinds)}: "
        f"{kinds}. A second indicator/strategy/library would silently shadow "
        "the first."
    )
    assert kinds[0] == expected_kind, (
        f"{name}: declaration kind drifted (expected {expected_kind!r}, "
        f"got {kinds[0]!r}). Switching indicator <-> strategy is breaking."
    )


@pytest.mark.parametrize("name", sorted(_FROZEN_DECL_KIND))
def test_declaration_files_exist(name: str) -> None:
    assert (ROOT / name).is_file(), f"Ledger Pine file missing: {name}"

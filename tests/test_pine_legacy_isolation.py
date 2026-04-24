"""Pin: legacy Pine scripts live under ``pine/legacy/`` and are not referenced.

Background
==========

23 legacy Pine strategies (USI*, BFI*, CHOCH*, REV*, VWAP*, QuickALGO,
Volume_Weighted_Trend_SkippAlgo, BTC 3m EV Scalper, Breakout_Finder_Intelligent)
have been moved out of the repo root into ``pine/legacy/``. This test
locks that move in:

1. The exact 23 filenames must exist under ``pine/legacy/``.
2. None of those filenames may reappear at the repo root.
3. No non-legacy Python / config / Markdown file may reference any legacy
   filename, except the test itself, the audit report, and the legacy
   directory's own README (if any).

Background memory: ``/memories/repo/pine-canonical-lean-shared-exports.md``,
``/memories/repo/pine-module-pack-d-slot-contract.md`` describe the
canonical Pine layout. Legacy scripts may import older library majors
(ADR-0003) and are excluded from the active Pine library version-skew
gate (see ``tests/test_pine_library_version_consistency.py``).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIR = REPO_ROOT / "pine" / "legacy"

# Canonical legacy inventory — 23 files. Adding here means the file MUST
# exist under pine/legacy/. Removing here means the file may be deleted
# from the repo entirely.
_LEGACY_FILENAMES: frozenset[str] = frozenset({
    "BFI-Reversal.pine",
    "Breakout_Finder_Intelligent.pine",
    "BTC 3m EV Scalper BALANCED (Harmonized).pine",
    "CHOCH-Base_Indikator.pine",
    "CHOCH-Base_Strategy.pine",
    "CHOCH-Indicator.pine",
    "CHOCH-Strategy.pine",
    "CHoCH.pine",
    "QuickALGO.pine",
    "REV-BUY.pine",
    "REV-Ladder-CHoCH.pine",
    "REV-Ladder.pine",
    "USI_Lines.pine",
    "USI_Strategy.pine",
    "USI-CHOCH.pine",
    "USI-Flip.pine",
    "USI-REV-BUY.pine",
    "USI.pine",
    "Volume_Weighted_Trend_SkippAlgo.pine",
    "VWAP_Long_Reclaim_Indicator.pine",
    "VWAP_Long_Reclaim_Strategy.pine",
    "VWAP_Reclaim_Indicator.pine",
    "VWAP_Reclaim_Strategy.pine",
})

# Files that MAY mention legacy names: this test, audit reports, CHANGELOG,
# memories, and legacy's own docs.
_REFERENCE_ALLOWLIST_PARTS: frozenset[str] = frozenset({
    "tests",  # this test file lives here
    "docs",   # audit reports
    "memories",  # repo memory directory if mirrored
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "site-packages",
})

_REFERENCE_ALLOWLIST_NAMES: frozenset[str] = frozenset({
    "CHANGELOG.md",
    "README.md",
    "PINE_LEGACY.md",
    # Legacy-aware tooling: enumerates legacy filenames as part of its
    # surface-classification or lifecycle-management responsibility.
    "smc_bus_manifest.py",
    "smc_file_lifecycle.py",
    "smc_surface_matrix.py",
    "pine_apply_surface_reduction.py",
    "test_usi_lint.py",
})


def test_legacy_dir_exists() -> None:
    assert LEGACY_DIR.is_dir(), f"missing pine/legacy/: {LEGACY_DIR}"


def test_all_legacy_files_present_in_legacy_dir() -> None:
    """Every entry in the canonical inventory must exist under pine/legacy/."""
    missing = sorted(name for name in _LEGACY_FILENAMES if not (LEGACY_DIR / name).is_file())
    assert not missing, (
        f"Files missing from pine/legacy/: {missing}. "
        "Either restore the file or remove it from _LEGACY_FILENAMES."
    )


def test_no_unexpected_files_in_legacy_dir() -> None:
    """pine/legacy/ must contain exactly the canonical inventory (no drift)."""
    observed = frozenset(p.name for p in LEGACY_DIR.glob("*.pine"))
    extras = sorted(observed - _LEGACY_FILENAMES)
    assert not extras, (
        f"pine/legacy/ contains files not in _LEGACY_FILENAMES: {extras}. "
        "Add them to the canonical inventory or move them out."
    )


def test_legacy_filenames_do_not_appear_at_repo_root() -> None:
    """No legacy .pine file may be re-introduced at the repo root."""
    re_introduced = sorted(name for name in _LEGACY_FILENAMES if (REPO_ROOT / name).is_file())
    assert not re_introduced, (
        f"Legacy Pine files re-introduced at repo root: {re_introduced}. "
        "Move them back under pine/legacy/."
    )


def _is_allowed_referrer(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT)
    parts = set(rel.parts)
    if parts & _REFERENCE_ALLOWLIST_PARTS:
        return True
    if rel.parts and rel.parts[0] == "pine" and len(rel.parts) >= 2 and rel.parts[1] == "legacy":
        return True
    if path.name in _REFERENCE_ALLOWLIST_NAMES:
        return True
    return False


def _candidate_files() -> list[Path]:
    out: list[Path] = []
    skip_top = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache",
                ".pytest_cache", ".ruff_cache", "site-packages"}
    for ext in ("*.py", "*.json", "*.toml", "*.yaml", "*.yml", "*.md"):
        for p in REPO_ROOT.rglob(ext):
            try:
                rel = p.relative_to(REPO_ROOT)
            except ValueError:
                continue
            if any(part in skip_top for part in rel.parts):
                continue
            out.append(p)
    return out


def test_no_non_legacy_file_references_legacy_pine_names() -> None:
    """Only allowlisted files may mention any legacy .pine filename."""
    offenders: list[str] = []
    for path in _candidate_files():
        if _is_allowed_referrer(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = sorted(name for name in _LEGACY_FILENAMES if name in text)
        if hits:
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"  {rel}: {hits}")
    assert not offenders, (
        "Non-legacy file(s) reference legacy .pine filename(s):\n"
        + "\n".join(offenders)
        + "\nEither remove the reference or add the file/path part to "
        "_REFERENCE_ALLOWLIST_NAMES / _REFERENCE_ALLOWLIST_PARTS."
    )

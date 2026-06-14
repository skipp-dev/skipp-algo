"""Pin: production writers must use ``smc_atomic_write`` (or carry a marker).

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**H-2** (Klasse #8/#9/#10, "Direct to_csv / to_parquet / json.dump"): a
crash mid-write left a truncated artifact behind that propagated silently
to downstream consumers (Pine export, calibration, Streamlit UI).

Scope
=====

Originally ``scripts/`` only. Audit E-1 2026-06-13 (AW-1) expanded the
scan to ``open_prep/ ml/ rl/ governance/ smc_core/ smc_integration/
newsstack_fmp/`` plus the repo-root ``*.py`` modules — those surfaces
were previously blind spots where a new non-atomic writer regressed
silently. Pre-existing sites were inventoried at expansion time and are
documented in ``_FILE_LEVEL_EXEMPT`` with a rationale each.

This pin walks every in-scope ``.py`` with AST and rejects:

  - ``df.to_csv(...)`` / ``df.to_parquet(...)`` calls
  - ``json.dump(payload, fh, ...)`` calls (the ``open(..., "w")`` companion)
  - ``Path.write_text(...)`` calls

unless the call site is whitelisted via either:

  1. presence in ``_FILE_LEVEL_EXEMPT`` (the helper module itself, plus
     files whose writes were verified atomic / intentionally exempt at
     scope-expansion time — keys are repo-relative POSIX paths), OR
  2. an inline marker comment within the 6 lines preceding the call:

         # ATOMIC-WRITE-EXEMPT: <reason>

This is a discipline pin — the marker forces a reviewer to read the
exemption rationale rather than letting silent regressions slip in.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Audit E-1 2026-06-13 (AW-1): scan all production surfaces, not just scripts/.
_SCAN_DIRS: tuple[Path, ...] = tuple(
    _REPO_ROOT / name
    for name in (
        "scripts", "open_prep", "ml", "rl", "governance",
        "smc_core", "smc_integration", "newsstack_fmp",
    )
)

_EXEMPT_MARKER = "ATOMIC-WRITE-EXEMPT:"
_PROXIMITY_LINES = 6

# Files whose content is the helper itself or whose direct writes are
# intentional. Keys are repo-relative POSIX paths (Audit E-1 2026-06-13:
# previously bare filenames — collision-prone across directories).
# Add new entries with explicit reason; prefer inline ATOMIC-WRITE-EXEMPT
# markers for new code so the rationale lives next to the call site.
_FILE_LEVEL_EXEMPT: dict[str, str] = {
    # The atomic helper itself.
    "scripts/smc_atomic_write.py": "Helper module that defines the atomic writers.",
    # --- Audit E-1 2026-06-13 (AW-1) scope-expansion baseline ---
    # Verified atomic (mkstemp/tmp + os.replace) — flagged only because the
    # banned call writes to the tempfile, which AST alone cannot prove:
    "newsstack_fmp/open_prep_export.py": "json.dump into mkstemp+fsync+os.replace atomic pattern",
    "open_prep/candidate_weights.py": "json.dump inside local _atomic_write_json (mkstemp+os.replace; AW-4 consolidation candidate)",
    "open_prep/diff.py": "json.dump into mkstemp+fsync+os.replace atomic pattern",
    "open_prep/feature_importance_report.py": "json.dump inside local _atomic_write_json (mkstemp+os.replace; AW-4 consolidation candidate)",
    "open_prep/outcome_backfill.py": "json.dump into mkstemp+fsync+os.replace atomic patterns",
    "open_prep/outcomes.py": "json.dump into mkstemp+fsync+os.replace atomic pattern",
    "databento_utils.py": "to_parquet writes the tempfile inside _write_parquet_atomic (tmp+os.replace)",
    "databento_volatility_screener.py": "write_text/to_parquet write the tempfile inside _write_*_atomic helpers (tmp+os.replace)",
    # Atomic intent, but fixed tmp-name + no cleanup-on-exception —
    # tracked as Audit E-1 finding AW-2/AW-3 for hardening:
    "databento_reference.py": "tmp+os.replace with fixed tmp name (AW-2 hardening candidate)",
    "databento_universe.py": "tmp+os.replace with fixed tmp name (AW-2 hardening candidate)",
    "newsstack_fmp/shared_fetch.py": "tmp+os.replace under _file_lock, fixed tmp name (AW-3 hardening candidate)",
    # Intentionally non-atomic:
    "open_prep/realtime_signals.py": "PID-file write_text (single small value, transient state) + json.dump into mkstemp atomic pattern",
    "governance/family_verdict.py": "operator CLI --output report (one-shot, not pipeline-consumed)",
    "pine_apply_surface_reduction.py": "operator CLI rewriting git-tracked .pine sources (recoverable via git, AW-6)",
    "pine_input_surface.py": "operator CLI rewriting git-tracked .pine sources (recoverable via git, AW-6)",
}

_BANNED_METHOD_NAMES: frozenset[str] = frozenset({
    "to_csv",
    "to_parquet",
    "write_text",
})


def _has_marker(source_lines: list[str], lineno: int) -> bool:
    start = max(0, lineno - 1 - _PROXIMITY_LINES)
    end = min(len(source_lines), lineno)
    return any(_EXEMPT_MARKER in line for line in source_lines[start:end])


def _is_json_dump_to_open_writer(call: ast.Call) -> bool:
    """Detect ``json.dump(payload, open(...) | fh, ...)`` patterns.

    We accept any ``json.dump`` call because the second argument is a
    file handle; whether that handle wraps an atomic tempfile or a direct
    target path is not deducible from AST alone. The pin therefore demands
    an explicit exemption marker for every json.dump in scripts/.
    """
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "dump"
        and isinstance(func.value, ast.Name)
        and func.value.id == "json"
    )


def _iter_violations(path: Path) -> list[str]:
    rel = path.relative_to(_REPO_ROOT)
    if rel.as_posix() in _FILE_LEVEL_EXEMPT:
        return []
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ValueError(
            f"SyntaxError while scanning {path} — fix the file or exclude it "
            f"from the scan: {exc}"
        ) from exc
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        banned = False
        kind = ""
        if isinstance(func, ast.Attribute) and func.attr in _BANNED_METHOD_NAMES:
            banned = True
            kind = func.attr
        elif _is_json_dump_to_open_writer(node):
            banned = True
            kind = "json.dump"
        if not banned:
            continue
        if _has_marker(source_lines, node.lineno):
            continue
        violations.append(f"{rel}:{node.lineno}: {kind}() — use scripts.smc_atomic_write or add `# ATOMIC-WRITE-EXEMPT: <reason>` marker")
    return violations


def _iter_scan_files() -> list[Path]:
    """All production .py files in scope: scan dirs (recursive) + repo root."""
    files: list[Path] = []
    for scan_dir in _SCAN_DIRS:
        if scan_dir.is_dir():
            files.extend(sorted(scan_dir.rglob("*.py")))
    # Repo-root modules (non-recursive); exclude test helpers and conftest
    # which may use raw writes in test-only contexts (not production surfaces).
    files.extend(
        p
        for p in sorted(_REPO_ROOT.glob("*.py"))
        if not p.name.startswith("test_") and p.name != "conftest.py"
    )
    return files


def test_no_direct_to_csv_or_json_dump_in_production() -> None:
    violations: list[str] = []
    for path in _iter_scan_files():
        violations.extend(_iter_violations(path))
    assert not violations, (
        "Direct non-atomic writes detected in production surfaces. Migrate to "
        "scripts.smc_atomic_write helpers or annotate each site with "
        "`# ATOMIC-WRITE-EXEMPT: <reason>`:\n  - "
        + "\n  - ".join(violations)
    )


def test_file_level_exempt_keys_exist() -> None:
    """Pin: every exemption key must point at an existing file.

    Prevents the exemption table from accumulating stale entries after
    renames/deletes (Audit E-1 2026-06-13).
    """
    missing = sorted(
        rel for rel in _FILE_LEVEL_EXEMPT if not (_REPO_ROOT / rel).is_file()
    )
    assert not missing, (
        f"_FILE_LEVEL_EXEMPT contains paths that no longer exist: {missing}"
    )

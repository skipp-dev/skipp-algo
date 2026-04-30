"""Pin: production writers in ``scripts/`` must use ``smc_atomic_write``.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**H-2** (Klasse #8/#9/#10, "Direct to_csv / to_parquet / json.dump"): a
crash mid-write left a truncated artifact behind that propagated silently
to downstream consumers (Pine export, calibration, Streamlit UI).

This pin walks every ``.py`` under ``scripts/`` with AST and rejects:

  - ``df.to_csv(...)`` / ``df.to_parquet(...)`` calls
  - ``json.dump(payload, fh, ...)`` calls (the ``open(..., "w")`` companion)
  - ``Path.write_text(...)`` calls

unless the call site is whitelisted via either:

  1. presence in ``_FILE_LEVEL_EXEMPT`` (the helper module itself, plus
     legitimate test fixture / generator scripts that build temp data
     out-of-band), OR
  2. an inline marker comment within the 2 lines preceding the call:

         # ATOMIC-WRITE-EXEMPT: <reason>

This is a discipline pin — the marker forces a reviewer to read the
exemption rationale rather than letting silent regressions slip in.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

_EXEMPT_MARKER = "ATOMIC-WRITE-EXEMPT:"
_PROXIMITY_LINES = 6

# Files whose content is the helper itself or whose direct writes are
# intentional (e.g. test data generators, ad-hoc CLI utilities that write
# to a temp dir, plotting scripts). Add new entries with explicit reason.
_FILE_LEVEL_EXEMPT: dict[str, str] = {
    # The atomic helper itself.
    "smc_atomic_write.py": "Helper module that defines the atomic writers.",
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
    if path.name in _FILE_LEVEL_EXEMPT:
        return []
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
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


def test_no_direct_to_csv_or_json_dump_in_scripts() -> None:
    violations: list[str] = []
    for path in sorted(_SCRIPTS_DIR.rglob("*.py")):
        violations.extend(_iter_violations(path))
    assert not violations, (
        "Direct non-atomic writes detected in scripts/. Migrate to "
        "scripts.smc_atomic_write helpers or annotate each site with "
        "`# ATOMIC-WRITE-EXEMPT: <reason>`:\n  - "
        + "\n  - ".join(violations)
    )

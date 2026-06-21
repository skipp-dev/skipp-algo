"""Zero-surface defense pin for ``hmac`` call sites in production code.

``hmac`` is the project's *only* primitive for authenticated message
integrity (webhook signing) and constant-time secret comparison
(token / API-key auth).  Both call sites are security-critical:

* ``hmac.new(secret, payload, sha256)`` — webhook HMAC signing.
  Drift here (e.g. swapping the digest, changing key encoding,
  silently accepting empty secrets) silently breaks downstream
  signature verification *without* test failure.
* ``hmac.compare_digest(a, b)`` — the constant-time string compare
  used to validate auth tokens.  Replacing it with ``==`` re-introduces
  a timing oracle (CWE-208).  Adding new ``compare_digest`` callers is
  fine, but each one MUST be appended to the allow-list below to
  prove a security review happened.

This test only enumerates ``(path, line, attr)`` for every
``hmac.<attr>(...)`` call discovered via AST.  It does not import
production modules and does not modify any production file.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parent.parent

# Each entry is (relative_path, line_number, attribute_name).
HMAC_ALLOWED: set[tuple[str, int, str]] = {
    # TradersPost webhook payload signing (HMAC-SHA256). Line shifted
    # 765 → 769 (deep-audit fallback-buffer lock refresh).
    ("terminal_export.py", 769, "new"),
    ("terminal_auth.py", 30, "compare_digest"),
    # 2026-06-16 (feat/live-overlay-daemon, PR #2794): token auth in FastAPI
    # endpoint uses hmac.compare_digest for constant-time comparison.
    # 2026-06-19 (fix/live-overlay-daemon-security, C1): _ct_eq compare site
    # moved repeatedly with daemon endpoint updates.
    # 2026-06-21 (merge refresh): combined branch changes shifted
    # compare_digest call to line 419.
    ("services/live_overlay_daemon/main.py", 419, "compare_digest"),
}

_DIR_EXCLUDE = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "docs",
    "tests",
    "SMC++",
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        rel_parts = p.relative_to(ROOT).parts
        # Exclude dot-directories and any path segment matching an
        # excluded directory name. Single check covers both nested
        # and top-level cases.
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel_parts[:-1]):
            continue
        out.append(p)
    return out


def _hmac_calls() -> set[tuple[str, int, str]]:
    found: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            value = func.value
            if not isinstance(value, ast.Name):
                continue
            if value.id != "hmac":
                continue
            rel = path.relative_to(ROOT).as_posix()
            found.add((rel, node.lineno, func.attr))
    return found


def test_hmac_zero_surface_pin() -> None:
    found = _hmac_calls()
    extra = found - HMAC_ALLOWED
    missing = HMAC_ALLOWED - found
    assert not extra, (
        "New hmac.* call site detected. Auth/integrity primitive — "
        "requires security review. Append (path, line, attr) to "
        f"HMAC_ALLOWED if approved. Extra: {sorted(extra)}"
    )
    assert not missing, (
        "Allow-listed hmac.* call site disappeared. If intentional, "
        f"remove from HMAC_ALLOWED. Missing: {sorted(missing)}"
    )

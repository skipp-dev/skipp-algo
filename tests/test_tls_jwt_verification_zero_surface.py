"""Defense-pin: TLS context tampering + JWT skip-verify zero-surface invariant.

Three closely related "skip-the-verification" call shapes that are all
empty in first-party non-test code today. Sister pin of the
``verify=False`` tripwire in
``tests/test_silent_security_and_boundary_bundle.py`` — same theme
(don't disable transport / token verification), different shapes the
existing pin doesn't catch.

The three banned shapes:

* ``ssl._create_unverified_context()`` — explicitly returns an
  ``SSLContext`` with hostname+chain verification disabled. CWE-295.
* Any constant reference to ``ssl.CERT_NONE`` — the marker for
  "trust any peer cert"; only legitimate use is a deliberate test
  rig, which lives under ``tests/`` and is excluded.
* ``jwt.decode(..., verify=False)`` — silently accepts unsigned
  tokens. CWE-347. The repo doesn't use PyJWT today; the pin
  prevents future drift if someone adds it.

Detection:

* AST attribute walk; matches every binding style (e.g. ``ssl.CERT_NONE``,
  ``from ssl import CERT_NONE`` then a bare ``CERT_NONE`` reference).
* For ``CERT_NONE`` we look at both ``ast.Attribute`` (``ssl.CERT_NONE``)
  and ``ast.Name`` (after a ``from ssl import CERT_NONE``); the latter
  is gated to files that actually import ``ssl`` so we don't false-
  positive on unrelated identifiers.

Defense-only — no production changes. Three surfaces, three tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
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
    }
)


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def _imported_cert_none_names(tree: ast.AST) -> set[str]:
    """Return the local names that ``CERT_NONE`` was imported as.

    Handles ``from ssl import CERT_NONE`` and
    ``from ssl import CERT_NONE as X``.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "ssl":
            continue
        for alias in node.names:
            if alias.name == "CERT_NONE":
                out.add(alias.asname or alias.name)
    return out


def test_no_ssl_create_unverified_context() -> None:
    """CWE-295: no ``ssl._create_unverified_context(...)`` calls."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "_create_unverified_context"
                and isinstance(f.value, ast.Name)
                and f.value.id == "ssl"
            ):
                findings.append(
                    f"  - {rel}:{node.lineno}  ssl._create_unverified_context(...)"
                )
    assert not findings, (
        "ssl._create_unverified_context(...) call(s) found — disables "
        "TLS hostname + chain verification (CWE-295):\n"
        + "\n".join(findings)
        + "\n\nUse ``ssl.create_default_context()`` and let it verify."
    )


def test_no_ssl_cert_none_constant() -> None:
    """CWE-295: no constant reference to ``ssl.CERT_NONE``."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        local_names = _imported_cert_none_names(tree)
        for node in ast.walk(tree):
            # Direct ``ssl.CERT_NONE``.
            if isinstance(node, ast.Attribute):
                if (
                    node.attr == "CERT_NONE"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "ssl"
                ):
                    findings.append(f"  - {rel}:{node.lineno}  ssl.CERT_NONE")
                continue
            # Bare ``CERT_NONE`` after a ``from ssl import CERT_NONE``.
            if isinstance(node, ast.Name) and node.id in local_names:
                findings.append(
                    f"  - {rel}:{node.lineno}  {node.id}  (from ssl import CERT_NONE)"
                )
    assert not findings, (
        "ssl.CERT_NONE reference(s) found — marks 'trust any peer cert' "
        "(CWE-295):\n"
        + "\n".join(findings)
        + "\n\nKeep verification on. Test rigs that genuinely need to "
        "skip cert verification belong under ``tests/``."
    )


def test_no_jwt_decode_verify_false() -> None:
    """CWE-347: no ``jwt.decode(..., verify=False)`` calls."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (
                isinstance(f, ast.Attribute)
                and f.attr == "decode"
                and isinstance(f.value, ast.Name)
                and f.value.id == "jwt"
            ):
                continue
            for kw in node.keywords or []:
                if (
                    kw.arg == "verify"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                ):
                    findings.append(
                        f"  - {rel}:{node.lineno}  jwt.decode(..., verify=False)"
                    )
    assert not findings, (
        "jwt.decode(..., verify=False) call(s) found — silently accepts "
        "unsigned tokens (CWE-347):\n"
        + "\n".join(findings)
        + "\n\nVerify the signature. If you genuinely need to inspect an "
        "untrusted JWT (e.g. read the header to pick a key), use a "
        "library API that makes that intent explicit."
    )

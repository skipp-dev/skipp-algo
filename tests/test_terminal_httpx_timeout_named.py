"""Audit pin: ``terminal_*.py`` httpx calls must use named timeouts.

Every ``httpx.Client(...)`` constructor and every direct call to
``httpx.{get,post,put,delete,patch,head,options,request,stream}(...)``
inside a top-level ``terminal_*.py`` module must pass ``timeout=`` as a
``Name``/``Attribute`` reference (e.g. ``_API_TIMEOUT``) — not as a
bare numeric/``Constant`` literal.

This makes timeouts auditable at module level: a reviewer can grep for
``_TIMEOUT``-style constants and see all baselines without scanning
call sites.

Companion to the per-script httpx pins in ``scripts/`` (PR #133):
- budget × singleton-guard × timeout-consistency × **named timeout**.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GLOB = "terminal_*.py"

# Modules we exclude — non-network terminal_* helpers. Keep minimal.
_FILE_EXCLUDE = {
    "terminal_status_helpers.py",
    "terminal_ui_helpers.py",
}

# Specific (file, line) sites where a numeric-literal ``timeout=`` is
# allowed with documented reason. Empty for now; extend only with cause.
_SITE_ALLOWLIST: set[tuple[str, int]] = set()

_HTTPX_DIRECT_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "request", "stream"}
)


def _terminal_files() -> list[Path]:
    return sorted(
        p for p in _REPO_ROOT.glob(_GLOB)
        if p.is_file() and p.name not in _FILE_EXCLUDE
    )


def _is_httpx_call(node: ast.Call) -> tuple[bool, str]:
    """Return (is_httpx_call_with_relevant_signature, label)."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False, ""
    value = func.value
    if not (isinstance(value, ast.Name) and value.id == "httpx"):
        return False, ""
    attr = func.attr
    if attr == "Client":
        return True, "httpx.Client"
    if attr in _HTTPX_DIRECT_METHODS:
        return True, f"httpx.{attr}"
    return False, ""


def _timeout_kwarg(node: ast.Call) -> ast.keyword | None:
    for kw in node.keywords:
        if kw.arg == "timeout":
            return kw
    return None


def _is_acceptable_timeout_value(value: ast.expr) -> bool:
    """``Name`` or ``Attribute`` references are auditable; literals are not."""
    return isinstance(value, (ast.Name, ast.Attribute))


def test_terminal_files_present() -> None:
    files = _terminal_files()
    assert files, f"No {_GLOB} files found at {_REPO_ROOT}"


def test_httpx_calls_use_named_timeout() -> None:
    violations: list[str] = []
    for path in _terminal_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - defensive
            violations.append(f"{rel}: parse error {exc!r}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            ok, label = _is_httpx_call(node)
            if not ok:
                continue
            kw = _timeout_kwarg(node)
            if kw is None:
                # No explicit timeout = httpx default (None / pool default);
                # this pin only governs explicit timeouts.
                continue
            if _is_acceptable_timeout_value(kw.value):
                continue
            site = (rel, node.lineno)
            if site in _SITE_ALLOWLIST:
                continue
            violations.append(
                f"{rel}:{node.lineno}: {label}(...) uses bare literal "
                f"timeout=...; promote to a module-level named constant "
                f"(e.g. _API_TIMEOUT) so reviewers can audit the baseline."
            )
    assert not violations, (
        "terminal_*.py httpx timeout discipline violations:\n  - "
        + "\n  - ".join(violations)
    )


def test_site_allowlist_entries_still_apply() -> None:
    """Stale guard: every (file, line) on the allowlist must still match."""
    stale: list[str] = []
    for rel, lineno in sorted(_SITE_ALLOWLIST):
        path = _REPO_ROOT / rel
        if not path.is_file():
            stale.append(f"{rel}:{lineno} (file missing)")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.lineno != lineno:
                continue
            ok, _ = _is_httpx_call(node)
            if not ok:
                continue
            kw = _timeout_kwarg(node)
            if kw is None or _is_acceptable_timeout_value(kw.value):
                continue
            found = True
            break
        if not found:
            stale.append(f"{rel}:{lineno} (no longer a literal-timeout httpx call)")
    assert not stale, (
        "Stale entries in _SITE_ALLOWLIST — remove:\n  - "
        + "\n  - ".join(stale)
    )

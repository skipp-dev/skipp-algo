"""Pin: ``urllib.request`` network discipline (timeout + call-site ledger).

`urllib.request.urlopen()` without an explicit `timeout` defaults to
the global socket default (often ``None`` → blocks forever). Every
network call must carry a timeout to bound failure latency and
prevent DoS via slow-loris servers.

Layers:

1. **Zero-tripwire**: any ``urlopen()`` without a `timeout=` keyword
   (or 2nd-positional `timeout`) fails the test. Currently 0.
2. **Frozen call-site ledger**: 5 known call sites
   (2× `urlopen`, 3× `Request`). New sites must be reviewed and
   added explicitly — guards against silent surface expansion.

This is a defense pin — no production code changes.

OWASP A05 (Security Misconfiguration) + CWE-400 (Resource Exhaustion).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# Frozen call-site ledger: (rel, lineno, attr).
# `urlopen` sites all confirmed to carry a timeout (verified by the
# zero-tripwire test below).
_URLLIB_CALL_LEDGER: frozenset[tuple[str, int, str]] = frozenset({
    ("terminal_notifications.py", 201, "urlopen"),
    ("terminal_notifications.py", 265, "urlopen"),
    ("open_prep/alerts.py", 396, "Request"),
    ("terminal_notifications.py", 197, "Request"),
    ("terminal_notifications.py", 262, "Request"),
})


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.py")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _scan() -> tuple[set[tuple[str, int]], set[tuple[str, int, str]]]:
    """Return (urlopen_no_timeout, all_call_sites)."""
    urlopen_no_timeout: set[tuple[str, int]] = set()
    all_calls: set[tuple[str, int, str]] = set()
    for p in _iter_prod_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(p.relative_to(_REPO_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute):
                continue
            if f.attr not in ("urlopen", "Request"):
                continue
            all_calls.add((rel, node.lineno, f.attr))
            if f.attr == "urlopen":
                has_kw_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                # urlopen(url, data=None, timeout=...) — 3rd positional
                has_pos_timeout = len(node.args) >= 3
                if not (has_kw_timeout or has_pos_timeout):
                    urlopen_no_timeout.add((rel, node.lineno))
    return urlopen_no_timeout, all_calls


def test_urlopen_must_have_explicit_timeout() -> None:
    """Zero-tripwire: every ``urlopen()`` carries an explicit timeout.

    Without a timeout, `urlopen` blocks forever on slow-loris peers
    or hung sockets — DoS surface.
    """
    no_timeout, _ = _scan()
    assert no_timeout == set(), (
        f"urlopen() without timeout= in production code: "
        f"{sorted(no_timeout)}. Pass `timeout=<seconds>` explicitly."
    )


def test_urllib_call_sites_frozen_no_new() -> None:
    """No new ``urlopen`` / ``Request`` call sites without ledger update.

    Every new site is a network surface expansion that needs review.
    """
    _, all_calls = _scan()
    new_sites = all_calls - _URLLIB_CALL_LEDGER
    assert new_sites == set(), (
        f"New urllib call site(s) without ledger entry: {sorted(new_sites)}. "
        f"Review the network surface, then add to _URLLIB_CALL_LEDGER."
    )


def test_urllib_call_ledger_no_stale() -> None:
    """Every entry in `_URLLIB_CALL_LEDGER` still exists in code."""
    _, all_calls = _scan()
    stale = _URLLIB_CALL_LEDGER - all_calls
    assert stale == set(), (
        f"Stale entries in _URLLIB_CALL_LEDGER: {sorted(stale)}. Remove them."
    )


@pytest.mark.parametrize(
    ("rel", "lineno", "attr"),
    sorted(_URLLIB_CALL_LEDGER),
    ids=lambda v: str(v),
)
def test_urllib_call_ledger_files_exist(rel: str, lineno: int, attr: str) -> None:
    """Every ledgered file still exists."""
    p = _REPO_ROOT / rel
    assert p.is_file(), f"Ledger references missing file: {rel}"

"""Pin: every weak-hash (md5/sha1) call must explicitly pass
``usedforsecurity=False``.

This complements ``test_weak_hash_pin.py`` (which pins **count** + ledger).
This pin enforces **intent annotation** at every existing call site:

- Silences Bandit B324 / Ruff S324.
- Documents that the digest is non-cryptographic content-addressing
  (cache key, dirty-flag fingerprint, dedupe ID).
- Required by FIPS-mode interpreters where md5/sha1 raise ``ValueError``
  unless ``usedforsecurity=False`` is set.

A failing site means a new weak-hash call was added without the flag —
either add the flag (preferred) or migrate to sha256.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

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
        "scripts",
        "tests",
        "SMC++",
    }
)


def _is_weak_hash_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return False
    if func.value.id != "hashlib":
        return False
    if func.attr in ("md5", "sha1"):
        return True
    if func.attr == "new" and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.lower() in ("md5", "sha1")
    return False


def _iter_first_party_py():
    for p in REPO.rglob("*.py"):
        rel_parts = p.relative_to(REPO).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        yield p


def _collect_weak_hash_calls() -> list[tuple[str, int, ast.Call]]:
    out: list[tuple[str, int, ast.Call]] = []
    for p in _iter_first_party_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = p.relative_to(REPO).as_posix()
        for node in ast.walk(tree):
            if _is_weak_hash_call(node):
                out.append((rel, node.lineno, node))
    return out


def _has_usedforsecurity_false(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "usedforsecurity":
            v = kw.value
            return isinstance(v, ast.Constant) and v.value is False
    return False


_CALLS = _collect_weak_hash_calls()
_IDS = [f"{rel}:{ln}" for rel, ln, _ in _CALLS]


def test_at_least_one_weak_hash_call_exists() -> None:
    # Sanity: if the AST scanner returns 0 hits we want a loud failure
    # rather than a silently-passing parametrised suite.
    assert _CALLS, (
        "No weak-hash calls detected. Either every call was migrated to "
        "sha256 (then delete this pin) or the scanner regressed."
    )


@pytest.mark.parametrize(
    "rel,lineno,call",
    [(rel, ln, call) for rel, ln, call in _CALLS],
    ids=_IDS,
)
def test_weak_hash_call_has_usedforsecurity_false(
    rel: str, lineno: int, call: ast.Call
) -> None:
    assert _has_usedforsecurity_false(call), (
        f"{rel}:{lineno}: hashlib.md5/sha1 call is missing "
        f"`usedforsecurity=False`. Add the kwarg (preferred for "
        f"non-crypto content-addressing) or migrate the call to "
        f"`hashlib.sha256(...)`."
    )

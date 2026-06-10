"""Zero-surface pin for dynamic-name ``setattr(...)`` and ``hasattr(...)``.

Complements ``test_dynamic_getattr_ledger.py`` (CWE-470 read side) by
locking the *write* and *probe* counterparts. Same security family:
runtime reflection where the attribute name is not a string literal
defeats static analysis, hides cross-module coupling, and widens the
surface for any caller controlling the name argument.

Today the entire production tree has exactly *one* dynamic ``setattr``
caller and *one* dynamic ``hasattr`` caller — both small, local
helpers with deliberate fall-back semantics. Pinning these to a
zero-surface allow-list means any new dynamic write/probe becomes a
deliberate, reviewed change.

Literal-name calls (``setattr(obj, "field", v)`` /
``hasattr(obj, "field")``) are statically equivalent to plain
attribute access and are intentionally *not* tracked here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parents[1]

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
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _dynamic_builtin_sites(builtin: str) -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for ``<builtin>(obj, <non-literal>, ...)``
    calls — i.e. those where the second argument is NOT a string
    literal. Literal-name calls are filtered out because they are
    statically analysable and equal to plain attribute access.
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != builtin:
                continue
            if len(node.args) < 2:
                continue
            name_arg = node.args[1]
            if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
                continue
            sites.add((str(path.relative_to(ROOT)), node.lineno))
    return sites


# --- setattr -----------------------------------------------------------------

# Single legitimate caller: ``_set_field`` helper inside the live-story
# state layer. The name comes from a field-name registry inside the same
# module and is treated as trusted; the helper falls back to mapping
# assignment when ``item`` is a dict, so the dynamic write only happens
# on dataclass-style targets the caller already knows.
DYNAMIC_SETATTR_ALLOWED: set[tuple[str, int]] = {
    ("terminal_live_story_state.py", 49),
}


def test_dynamic_setattr_zero_surface_pin() -> None:
    sites = _dynamic_builtin_sites("setattr")

    unexpected = sites - DYNAMIC_SETATTR_ALLOWED
    assert not unexpected, (
        "New dynamic setattr(obj, <expr>, ...) call site detected. "
        "Dynamic reflection writes defeat static analysis (CWE-470) and "
        "are even riskier than the read side because they mutate state. "
        "Prefer an explicit ``Mapping[str, Callable]`` setter table or "
        "a TypedDict update so the set of writable names is statically "
        "visible. If a new caller is genuinely required, append the "
        "(path, line) tuple to DYNAMIC_SETATTR_ALLOWED with a "
        "justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = DYNAMIC_SETATTR_ALLOWED - sites
    assert not missing, (
        "DYNAMIC_SETATTR_ALLOWED entries no longer present in code. "
        "Update the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )


# --- hasattr -----------------------------------------------------------------

# Single legitimate caller: a probe inside the test-mode config builder
# that asks "does this dataclass field actually exist?" before merging
# overrides. The name comes from a small, trusted override-mapping
# defined in the same module.
DYNAMIC_HASATTR_ALLOWED: set[tuple[str, int]] = {
    ("streamlit_terminal.py", 591),
}


def test_dynamic_hasattr_zero_surface_pin() -> None:
    sites = _dynamic_builtin_sites("hasattr")

    unexpected = sites - DYNAMIC_HASATTR_ALLOWED
    assert not unexpected, (
        "New dynamic hasattr(obj, <expr>) call site detected. "
        "Dynamic attribute probing defeats static analysis (CWE-470) "
        "and is almost always a sign of missing structural typing. "
        "Prefer a TypedDict / Protocol with explicit fields. If a new "
        "caller is genuinely required, append the (path, line) tuple "
        "to DYNAMIC_HASATTR_ALLOWED with a justification in the commit "
        "message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = DYNAMIC_HASATTR_ALLOWED - sites
    assert not missing, (
        "DYNAMIC_HASATTR_ALLOWED entries no longer present in code. "
        "Update the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )

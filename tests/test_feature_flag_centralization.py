"""Centralization guard for ``ENABLE_*`` feature-flag env reads (audit F-002).

Enforces that ``ENABLE_*`` feature-flag *names* are referenced only inside the
sanctioned per-layer flag-reader modules. There is one reader per import layer
(and the layers are import-isolated from one another), so "the SSOT" is really a
small fixed set, not a single file:

* ``open_prep/feature_flags.py``              — open_prep layer (uses ``_bool_env``)
* ``smc_core/v2_features.py``                 — smc_core layer (uses ``_flag_enabled``;
  MUST NOT import ``open_prep`` per the layer guard, so it keeps its own reader)
* ``smc_integration/measurement_evidence.py`` — smc_integration layer (uses ``_bool_env``)

The check is **AST-based**, so it catches BOTH the literal form
``os.getenv("ENABLE_X")`` AND the wrapper form ``_bool_env("ENABLE_X")`` /
``_flag_enabled("ENABLE_X")``. The previous regex guard only matched the literal
``os.getenv("ENABLE_…`` shape and silently missed every wrapper call site — so it
"guaranteed" a centralization it never actually enforced (audit 2026-07-13). A new
flag added off-SSOT via a local wrapper would have passed green.

Any ``ENABLE_*`` flag-name string constant appearing in executable code outside
the sanctioned set means a flag is being read off-SSOT: wire it through the
layer's reader instead.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The per-layer flag-reader modules. ``ENABLE_*`` name literals may appear only
#: in these files (repo-relative, posix). Each is the single reader for its layer.
SANCTIONED_READERS: frozenset[str] = frozenset(
    {
        "open_prep/feature_flags.py",
        "smc_core/v2_features.py",
        "smc_integration/measurement_evidence.py",
        # The live-overlay daemon is a separate deployable that does not import
        # open_prep; config.py is its per-layer reader (railway_metrics_enabled()
        # centralises ENABLE_RAILWAY_METRICS). Surfaced by the AST guard on
        # 2026-07-13 — the old regex missed this _optional_str(...) wrapper read.
        "services/live_overlay_daemon/config.py",
    }
)

_ENABLE_PREFIX = "ENABLE_"
_EXCLUDE_TOP = {".venv", "venv", ".tox", "node_modules", "build", "dist"}


def _is_flag_name_literal(value: object) -> bool:
    """True for a standalone flag-NAME literal like ``"ENABLE_SWEEP_TRAP"``.

    A docstring that merely *mentions* ``ENABLE_X`` inline does not match: its
    Constant value is the whole prose string (which does not ``startswith`` the
    prefix), and even a leading mention would fail the trailing-token check.
    """
    if not isinstance(value, str) or not value.startswith(_ENABLE_PREFIX):
        return False
    tail = value[len(_ENABLE_PREFIX):]
    return bool(tail) and tail.replace("_", "").isalnum()


def flag_name_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(lineno, value)`` for every ``ENABLE_*`` name literal in the AST."""
    return sorted(
        {
            (node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and _is_flag_name_literal(node.value)
        }
    )


def _iter_non_test_sources():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        parts = rel.parts
        if parts[0] in _EXCLUDE_TOP or parts[0] == "tests":
            continue
        yield path, rel.as_posix()


def test_enable_flags_referenced_only_in_sanctioned_readers():
    """No .py file outside the sanctioned per-layer readers may reference an
    ``ENABLE_*`` flag name — whether via a literal ``os.getenv("ENABLE_X")`` or
    via a wrapper call ``_bool_env("ENABLE_X")`` (AST-detected, both forms)."""
    violations: list[str] = []
    for path, rel in _iter_non_test_sources():
        if rel in SANCTIONED_READERS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _ENABLE_PREFIX not in text:  # cheap pre-filter: a flag literal must contain it
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for lineno, name in flag_name_literals(tree):
            violations.append(f"  {rel}:{lineno}: {name}")

    assert not violations, (
        "ENABLE_* flag name(s) referenced outside the sanctioned per-layer readers "
        f"({', '.join(sorted(SANCTIONED_READERS))}). Read the flag through the "
        "layer's reader instead of touching the env var directly:\n"
        + "\n".join(violations)
    )


def test_sanctioned_readers_exist_and_are_used():
    """The allow-list must stay honest: every sanctioned reader must exist and
    actually reference at least one ``ENABLE_*`` flag (else prune the entry)."""
    stale: list[str] = []
    for rel in sorted(SANCTIONED_READERS):
        path = REPO / rel
        if not path.exists():
            stale.append(f"  {rel}: file missing")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not flag_name_literals(tree):
            stale.append(f"  {rel}: no ENABLE_* reads — remove from SANCTIONED_READERS")
    assert not stale, "Stale SANCTIONED_READERS entries:\n" + "\n".join(stale)


# ── Guard-logic unit tests (prove the AST detector catches what the regex missed) ──


def test_detects_literal_getenv():
    src = 'import os\nx = os.getenv("ENABLE_X", "0")\n'
    assert [v for _, v in flag_name_literals(ast.parse(src))] == ["ENABLE_X"]


def test_detects_wrapper_call_the_old_regex_missed():
    # The exact class the regex guard missed: an ENABLE_* literal passed into a
    # local wrapper (os.getenv(name)) rather than into os.getenv("ENABLE_…") directly.
    src = 'def f():\n    return _bool_env("ENABLE_SNEAKY", "0")\n'
    assert [v for _, v in flag_name_literals(ast.parse(src))] == ["ENABLE_SNEAKY"]


def test_ignores_docstring_mention_of_a_flag():
    # A docstring that merely mentions ENABLE_FOO must NOT count as a read.
    src = '"""We read ENABLE_FOO from the env in the reader module."""\ny = 1\n'
    assert flag_name_literals(ast.parse(src)) == []


def test_ignores_non_flag_and_prefix_only_strings():
    src = 'a = "ENABLED_STATE"\nb = "ENABLE_"\nc = "enable_x"\n'
    # "ENABLED_STATE" has no ENABLE_ prefix boundary flag name; "ENABLE_" has an
    # empty tail; lower-case is not a flag name. None are flag-name literals.
    assert flag_name_literals(ast.parse(src)) == []

"""Defense ledger for dynamic ``getattr(obj, <non-literal>)`` call sites.

``getattr(obj, "literal_attr")`` is fine — the attribute name is part of
the source and visible to refactoring tools / static analysis. Calls
where the attribute name is a *runtime expression* (variable,
parameter, or computed string) are different:

* they defeat static analysis — Pyright/Pylance can no longer prove
  which attributes are touched, so renaming the underlying field is
  silently broken;
* they widen the attack surface for any caller that controls the name
  argument (CWE-470 — unsafe reflection);
* they hide coupling between modules: ``getattr(state, name)`` quietly
  reaches across whatever the producer of ``name`` chose to emit.

The repository currently has 10 such call sites, all in well-understood
state-layer accessors and scoring helpers. Locking them with a ledger
gives drift detection (line shifts surface here) and a growth gate
(new dynamic-attr lookups must extend the ledger explicitly with a
justification — same pattern as
``test_warnings_simplefilter_ledger.py`` and
``test_os_unlink_remove_ledger.py``).
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


def _dynamic_getattr_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every ``getattr(obj, <expr>)``
    call where the second argument is *not* a string literal.

    A literal name (``getattr(obj, "field")``) is treated as safe and
    does not enter the ledger — it is statically analysable and equals
    plain attribute access.
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
            if not isinstance(func, ast.Name) or func.id != "getattr":
                continue
            if len(node.args) < 2:
                continue
            name_arg = node.args[1]
            if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
                continue
            # POSIX form keeps the ledger stable across OSes (#2244).
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


# Locked ledger of every production dynamic-name ``getattr(...)`` site.
# Adding a new caller? Append the (path, line) tuple in the same PR
# with a justification in the commit message; better yet, prefer a
# small ``Mapping[str, Callable]`` / TypedDict accessor so the set of
# valid names is statically visible.
DYNAMIC_GETATTR_LEDGER: set[tuple[str, int]] = {
    # 2026-06-19 (live-overlay bugfix): _record_to_bar uses a tiny helper to
    # preserve missing OHLC attrs as None instead of coercing to 0.0.
    # 2026-06-19 (follow-up): keep ledger pinned to current helper site.
    # 2026-06-19 (Copilot follow-up): feed metrics helpers shifted site 56 -> 64.
    # 2026-06-19 (telemetry): import line shifted getattr site to 65.
    ("services/live_overlay_daemon/feed.py", 65),
    ("smc_core/event_ledger.py", 79),
    ("smc_core/scoring.py", 308),
    ("streamlit_terminal_alerts.py", 41),
    ("terminal_attention_state.py", 45),
    ("terminal_catalyst_state.py", 31),
    ("terminal_live_story_state.py", 42),
    ("terminal_poller.py", 1160),
    ("terminal_posture_state.py", 53),
    ("terminal_reaction_state.py", 49),
    ("terminal_resolution_state.py", 43),
}


def test_dynamic_getattr_ledger_exact() -> None:
    sites = _dynamic_getattr_sites()

    unexpected = sites - DYNAMIC_GETATTR_LEDGER
    assert not unexpected, (
        "New / drifted dynamic-name getattr(obj, <expr>) call site "
        "detected. Dynamic reflection defeats static analysis (CWE-470). "
        "Prefer a small ``Mapping[str, Callable]`` / TypedDict accessor "
        "so the set of valid names is statically visible. If the dynamic "
        "lookup is genuinely required, append the (path, line) tuple to "
        "DYNAMIC_GETATTR_LEDGER with a justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = DYNAMIC_GETATTR_LEDGER - sites
    assert not missing, (
        "DYNAMIC_GETATTR_LEDGER entries no longer present in code. If a "
        "lookup was deliberately removed or refactored to literal "
        "attribute access, drop the matching tuple from the ledger.\n"
        f"missing = {sorted(missing)}"
    )

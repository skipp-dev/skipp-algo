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
    # 2026-07-08 signal-event log: event_row() serialises a signal by iterating the
    # module-level constant _FEATURE_FIELDS tuple — the valid name set is statically
    # visible there, and it must accept both dataclass and SimpleNamespace signals.
    ("open_prep/signal_events.py", 66),  # 2026-07-10 truth-audit docstring: 63->66
    # 2026-06-22 (ingest-stop sentinel wakeup): helper block growth shifted
    # _record_to_bar dynamic getattr site 81 -> 82.
    # 2026-07-03 correctness lane: _feed_connected_at global shifted
    # _record_to_bar dynamic getattr site 101 -> 102.
    ("services/live_overlay_daemon/feed.py", 102),
    ("smc_core/event_ledger.py", 84),  # 2026-07-13 schema-enforcement: import math + write-time validation shifted (79->84)
    ("smc_core/scoring.py", 308),
    ("streamlit_terminal_alerts.py", 41),
    ("terminal_attention_state.py", 45),
    ("terminal_catalyst_state.py", 31),
    ("terminal_live_story_state.py", 41),  # 2026-07-11 (truth-audit): -1 (removed DEFAULT_LIVE_STORY_COOLDOWN_S)
    ("terminal_poller.py", 1217),  # 2026-07-09: 1160->1222; 2026-07-11 truth-audit -5 (removed live_story cooldown config/field/to_dict)
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

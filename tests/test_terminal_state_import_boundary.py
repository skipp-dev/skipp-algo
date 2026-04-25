"""terminal_*_state.py import-boundary pin.

The ``terminal_*_state.py`` modules form a state-management layer that
must not depend on the higher-level ``terminal_*.py`` feed/UI modules.
Concretely: a ``terminal_X_state.py`` may import other ``terminal_*_state``
peers and any non-terminal modules, but it must NOT import any
``terminal_<X>`` module that does NOT end in ``_state``.

This protects the layering recorded in
``/memories/repo/terminal-*-state-layer.md`` and prevents accidental
cycles between feed modules and their state stores.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATE_GLOB = "terminal_*_state.py"

# Modules under terminal_*_state may import these peer modules even though
# they don't end in "_state" — record any documented exceptions here.
#
# terminal_feed_state.py is the orchestrator of the feed lifecycle and
# legitimately calls into terminal_export (snapshot writer),
# terminal_poller (refresh loop), and terminal_ui_helpers (formatting
# for status lines). These three are pre-existing structural
# dependencies; the pin documents them so any *new* coupling beyond
# this set must be added consciously by extending the allowlist.
_IMPORT_ALLOWLIST: dict[str, set[str]] = {
    "terminal_feed_state.py": {
        "terminal_export",
        "terminal_poller",
        "terminal_ui_helpers",
    },
}


def _state_files() -> list[Path]:
    return sorted(_REPO_ROOT.glob(_STATE_GLOB))


def _imported_terminal_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("terminal_"):
                    out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("terminal_"):
                out.add(mod.split(".")[0])
    return out


def test_state_files_present() -> None:
    files = _state_files()
    assert files, (
        f"No {_STATE_GLOB} files found at {_REPO_ROOT}; the state-layer "
        f"convention may have moved without updating this pin."
    )


def test_state_modules_do_not_import_non_state_terminal_modules() -> None:
    violations: list[str] = []
    for path in _state_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        allow = _IMPORT_ALLOWLIST.get(rel, set())
        for imp in sorted(_imported_terminal_modules(path)):
            if imp.endswith("_state"):
                continue
            if imp in allow:
                continue
            violations.append(f"{rel}: imports {imp!r} (non-state terminal module)")
    assert not violations, (
        "terminal_*_state.py modules must not import non-state "
        "terminal_*.py modules (state layer must not depend on feed/UI "
        "layer):\n  - " + "\n  - ".join(violations)
    )


def test_import_allowlist_entries_still_apply() -> None:
    """Stale-entry guard: every allowlisted (file, import) must still occur."""
    stale: list[str] = []
    for rel, imports in _IMPORT_ALLOWLIST.items():
        path = _REPO_ROOT / rel
        if not path.is_file():
            stale.append(f"{rel} (file no longer exists)")
            continue
        actual = _imported_terminal_modules(path)
        for imp in imports:
            if imp not in actual:
                stale.append(f"{rel} -> {imp!r} (no longer imported)")
    assert not stale, (
        "Stale entries in _IMPORT_ALLOWLIST — remove:\n  - "
        + "\n  - ".join(stale)
    )

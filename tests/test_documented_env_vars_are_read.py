"""Pin: every environment variable the README documents must actually be read.

A runbook row that names a variable nothing reads is worse than no row: the
operator sets it, sees no effect, and has no way to tell a typo from a broken
feature. README.md:450 documented ``TERMINAL_POLL_INTERVAL`` (default ``15``)
while ``terminal_poller.py`` reads ``TERMINAL_POLL_INTERVAL_S`` (default
``10.0``) — the name and the value were both wrong, so the documented knob did
nothing at all.

Consumption counts in either direction: read by first-party Python as a quoted
literal, or set/forwarded by a workflow, compose file, Dockerfile or shell
script. A variable that only reaches the process through the environment is
still genuinely wired.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, repo_root

_DIR_EXCLUDE = frozenset({".venv", "node_modules", "__pycache__", ".git"})

# A README table row: | `SOME_VAR` | ... | ... |
_VAR_CELL = re.compile(r"`([A-Z][A-Z0-9_]{3,})`")

# Below this the table was restructured or the parse broke, and a green result
# would mean nothing.
_MIN_DOCUMENTED_VARS = 20


def _documented_env_vars() -> dict[str, int]:
    """Every ``UPPER_SNAKE`` name in the first cell of a README table row."""
    found: dict[str, int] = {}
    readme = repo_root() / "README.md"
    for lineno, line in enumerate(readme.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        match = _VAR_CELL.fullmatch(cells[0])
        if match:
            found.setdefault(match.group(1), lineno)
    return found


def _joined(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in paths)


def _consumer_text() -> tuple[str, str]:
    """Return (first-party Python source, everything else that can wire a var)."""
    root = repo_root()
    py = [
        path
        for path in iter_tracked_files("*.py", _DIR_EXCLUDE, root=root)
        if not path.name.startswith("test_")
    ]
    other: list[Path] = []
    for pattern in ("*.yml", "*.yaml", "*.sh", "*.toml", "*.json", "Dockerfile*"):
        other.extend(iter_tracked_files(pattern, _DIR_EXCLUDE, root=root))
    return _joined(py), _joined(other)


def test_documented_env_vars_are_actually_read() -> None:
    documented = _documented_env_vars()
    assert len(documented) >= _MIN_DOCUMENTED_VARS, (
        f"only {len(documented)} documented variables parsed out of README.md "
        f"(expected >= {_MIN_DOCUMENTED_VARS}) — the table layout changed and "
        "this guard is no longer measuring anything"
    )

    python_src, other_src = _consumer_text()
    dead = []
    for var, lineno in sorted(documented.items()):
        if re.search(rf"""["']{re.escape(var)}["']""", python_src):
            continue
        if re.search(rf"\b{re.escape(var)}\b", other_src):
            continue
        dead.append(f"{var} (README.md:{lineno})")

    assert not dead, (
        "README.md documents environment variable(s) that nothing reads. An "
        "operator who sets one sees no effect and cannot tell a typo from a "
        "broken feature — TERMINAL_POLL_INTERVAL was documented for months "
        "while the code read TERMINAL_POLL_INTERVAL_S.\n\n"
        f"Documented but never read: {dead}\n\n"
        "Fix the name/default in README.md, or delete the row if the knob is "
        "gone."
    )

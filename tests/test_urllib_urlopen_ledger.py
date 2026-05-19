"""Defense-pin: ledger of ``urllib.request.urlopen`` sites + mandatory timeout=.

Two layers — sister of ``test_subprocess_shell_injection_pin.py``:

1. **Hard invariant (CWE-1088 / availability)**: every
   ``urlopen(...)`` call MUST pass ``timeout=`` as a keyword argument.
   A missing timeout makes the caller block on a slow server forever
   and is the most common availability bug in Python network code.
2. **Per-(file, lineno) ledger**: freezes the current 4 site
   locations. Refuses both new and removed sites — any change to the
   network egress surface is a forced design decision.

Detection is conservative: only matches calls whose function is an
``ast.Attribute`` with ``attr == "urlopen"`` (so any of
``urllib.request.urlopen``, ``request.urlopen``, ``urlopen`` rebound
on a module — but NOT bare-name ``urlopen()`` after a
``from urllib.request import urlopen`` (would need `ast.Name` match;
none in this repo today).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

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

# Frozen ledger: (relative posix path) -> frozenset of linenos.
_FROZEN_SITES: dict[str, frozenset[int]] = {
    "scripts/restore_databento_export_bundle.py": frozenset({62, 77}),
    "scripts/smc_alert_notifier.py": frozenset({481}),
    "scripts/verify_branch_protection.py": frozenset({104}),
    "terminal_notifications.py": frozenset({255, 319}),
}

_FROZEN_TOTAL = sum(len(v) for v in _FROZEN_SITES.values())


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


def _is_urlopen_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return isinstance(f, ast.Attribute) and f.attr == "urlopen"


def _scan_urlopen(tree: ast.AST) -> list[tuple[int, bool]]:
    """Return [(lineno, has_timeout_kwarg), ...] for urlopen calls."""
    out: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not _is_urlopen_call(node):
            continue
        assert isinstance(node, ast.Call)
        kw = {k.arg for k in node.keywords if k.arg}
        out.append((node.lineno, "timeout" in kw))
    return out


def _parse(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _live_inventory() -> dict[str, list[tuple[int, bool]]]:
    out: dict[str, list[tuple[int, bool]]] = {}
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        sites = _scan_urlopen(tree)
        if sites:
            out[path.relative_to(ROOT).as_posix()] = sites
    return out


# ----- Layer 1: hard invariant — every urlopen() must pass timeout= -----


def test_every_urlopen_call_passes_timeout_kwarg() -> None:
    """CWE-1088 / availability invariant: no bare-blocking ``urlopen(...)``."""
    missing: list[str] = []
    for rel, sites in sorted(_live_inventory().items()):
        for lineno, has_timeout in sites:
            if not has_timeout:
                missing.append(f"  - {rel}:{lineno}")
    assert not missing, (
        "urlopen call(s) without `timeout=` kwarg found:\n"
        + "\n".join(missing)
        + "\n\nA missing timeout makes the caller block forever on a "
        "slow / hung server. Always pass an explicit `timeout=N` "
        "(seconds). This is a hard invariant — not a per-site ledger."
    )


# ----- Layer 2: per-(file, lineno) ledger -----


def test_no_new_urlopen_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    new_files = sorted(live - frozen)
    assert not new_files, (
        "New file(s) introduced ``urlopen(...)`` egress without ledger "
        "update:\n"
        + "\n".join(f"  - {f}" for f in new_files)
        + "\n\nNetwork egress is a defense surface. If genuinely "
        "needed, add the file + line(s) to ``_FROZEN_SITES`` in this "
        "test with a justifying comment."
    )


def test_no_removed_urlopen_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    removed_files = sorted(frozen - live)
    assert not removed_files, (
        "Frozen ``urlopen(...)`` site file(s) disappeared (good if "
        "intentional, but the ledger must be shrunk to match):\n"
        + "\n".join(f"  - {f}" for f in removed_files)
    )


@pytest.mark.parametrize(
    ("rel_path", "expected_linenos"),
    sorted(_FROZEN_SITES.items()),
)
def test_frozen_urlopen_linenos_still_match(
    rel_path: str, expected_linenos: frozenset[int]
) -> None:
    inv = _live_inventory()
    assert rel_path in inv, (
        f"Frozen file {rel_path!r} no longer contains any urlopen call. "
        "Either re-introduce it or shrink ``_FROZEN_SITES``."
    )
    live_linenos = frozenset(lineno for lineno, _ in inv[rel_path])
    assert live_linenos == expected_linenos, (
        f"urlopen line-number drift in {rel_path}: "
        f"frozen={sorted(expected_linenos)} live={sorted(live_linenos)}. "
        "Update ``_FROZEN_SITES`` if the move is intentional."
    )


def test_total_count_pinned() -> None:
    inv = _live_inventory()
    total = sum(len(sites) for sites in inv.values())
    assert total == _FROZEN_TOTAL, (
        f"Total urlopen site count drifted: frozen={_FROZEN_TOTAL} "
        f"live={total}. Update ``_FROZEN_TOTAL`` after auditing the "
        "delta."
    )

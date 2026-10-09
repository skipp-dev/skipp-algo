"""Defense-pin: socket.socket(...) + bind() ledger with loopback-only invariant.

The repo currently has exactly **one** socket usage — a port-finding
helper in ``scripts/start_open_prep_suite.py`` that binds to
``("127.0.0.1", port)``. This pin freezes that fact:

* **Layer 1 (ledger)**: per-(file, lineno) inventory of
  ``socket.socket(...)`` constructions and ``.bind(...)`` call sites.
* **Layer 2 (hard invariant, CWE-1327 / unintended-exposure)**: every
  ``.bind(...)`` call where the host argument is a string literal MUST
  bind to a loopback address (``127.0.0.1`` / ``localhost`` / ``::1``).
  Binding to ``0.0.0.0`` / ``""`` / a public IP exposes the socket
  beyond the local machine and must be a deliberate, reviewed
  decision.

Detection notes:
* ``.bind(...)`` is matched on attribute name only — a custom class
  with a ``bind`` method would also be inspected; the loopback check
  silently skips calls whose first argument is not a string-literal
  tuple/host (no false positives, just no coverage).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

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

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Frozen ledger: (rel posix path) -> {"socket": frozenset[int], "bind": frozenset[int]}.
_FROZEN_SITES: dict[str, dict[str, frozenset[int]]] = {
    "scripts/start_open_prep_suite.py": {
        "socket": frozenset({16}),
        "bind": frozenset({19}),
    },
}

_FROZEN_TOTAL_SOCKET = sum(len(v["socket"]) for v in _FROZEN_SITES.values())
_FROZEN_TOTAL_BIND = sum(len(v["bind"]) for v in _FROZEN_SITES.values())


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


def _scan(tree: ast.AST) -> dict[str, list[tuple[int, ast.Call]]]:
    out: dict[str, list[tuple[int, ast.Call]]] = {"socket": [], "bind": []}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "socket"
            and f.attr == "socket"
        ):
            out["socket"].append((node.lineno, node))
        if isinstance(f, ast.Attribute) and f.attr == "bind":
            out["bind"].append((node.lineno, node))
    return out


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def _live_inventory() -> dict[str, dict[str, list[tuple[int, ast.Call]]]]:
    out: dict[str, dict[str, list[tuple[int, ast.Call]]]] = {}
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        scan = _scan(tree)
        if scan["socket"] or scan["bind"]:
            out[path.relative_to(ROOT).as_posix()] = scan
    return out


def _bind_host_literal(call: ast.Call) -> str | None:
    """Return host string literal if first arg is a (host, port) tuple of literals; else None."""
    if not call.args:
        return None
    a0 = call.args[0]
    # Common shape: bind(("127.0.0.1", port))
    if isinstance(a0, ast.Tuple) and a0.elts:
        first = a0.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    # Less common: bind("/tmp/sock") for AF_UNIX — return verbatim
    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
        return a0.value
    return None


# ----- Layer 1: hard invariant — bind() to loopback only -----


def test_every_bind_call_uses_loopback_host() -> None:
    """CWE-1327 / unintended-exposure invariant.

    For every ``.bind(...)`` whose host arg is a string literal,
    the host must be a loopback address. Calls with non-literal
    host args (e.g. configurable) are silently skipped — the ledger
    layer below catches their existence regardless.
    """
    bad: list[str] = []
    for rel, scan in sorted(_live_inventory().items()):
        for lineno, call in scan["bind"]:
            host = _bind_host_literal(call)
            if host is None:
                continue
            # AF_UNIX path-like binds (start with '/' or contain no dot/colon)
            # are not network exposure — accept silently.
            if "/" in host or host == "":
                if host == "":
                    bad.append(f"  - {rel}:{lineno}  bind((\"\", ...))  # all-interfaces")
                continue
            if host not in _LOOPBACK_HOSTS and not host.startswith("127."):
                bad.append(f"  - {rel}:{lineno}  bind(({host!r}, ...))")
    assert not bad, (
        "Non-loopback bind() detected — sockets exposed beyond the "
        "local machine:\n"
        + "\n".join(bad)
        + "\n\nIf intentional public exposure is required, this must "
        "go through an explicit code review and the test should be "
        "updated to allow-list the specific site."
    )


# ----- Layer 2: per-(file, lineno) ledger -----


def test_no_new_socket_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    new = sorted(live - frozen)
    assert not new, (
        "New file(s) introduced socket.socket()/bind() without ledger "
        "update:\n"
        + "\n".join(f"  - {f}" for f in new)
        + "\n\nRaw socket usage is a defense surface. If genuinely "
        "needed, add the file to ``_FROZEN_SITES`` with a justifying "
        "comment."
    )


def test_no_removed_socket_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    removed = sorted(frozen - live)
    assert not removed, (
        "Frozen socket file(s) disappeared (good if intentional, but "
        "shrink ``_FROZEN_SITES`` accordingly):\n"
        + "\n".join(f"  - {f}" for f in removed)
    )


@pytest.mark.parametrize(
    ("rel_path", "kind"),
    [(rel, kind) for rel, scan in sorted(_FROZEN_SITES.items()) for kind in ("socket", "bind")],
)
def test_frozen_socket_linenos_still_match(rel_path: str, kind: str) -> None:
    inv = _live_inventory()
    assert rel_path in inv, f"Frozen file {rel_path!r} no longer present in live inventory."
    expected = _FROZEN_SITES[rel_path][kind]
    live_linenos = frozenset(lineno for lineno, _ in inv[rel_path][kind])
    assert live_linenos == expected, (
        f"socket/{kind} line drift in {rel_path}: "
        f"frozen={sorted(expected)} live={sorted(live_linenos)}. "
        "Update ``_FROZEN_SITES`` after auditing the move."
    )


def test_total_counts_pinned() -> None:
    inv = _live_inventory()
    total_sock = sum(len(s["socket"]) for s in inv.values())
    total_bind = sum(len(s["bind"]) for s in inv.values())
    assert (total_sock, total_bind) == (_FROZEN_TOTAL_SOCKET, _FROZEN_TOTAL_BIND), (
        f"Socket totals drifted: frozen=(socket={_FROZEN_TOTAL_SOCKET}, "
        f"bind={_FROZEN_TOTAL_BIND}) live=(socket={total_sock}, "
        f"bind={total_bind}). Update frozen totals after audit."
    )

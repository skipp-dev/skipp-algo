"""Zero-surface pin for dangerous IO/process primitives.

Three small surfaces, each currently confined to a known set of files. Any
new caller in production code (outside ``tests/``, ``scripts/``, vendor and
cache directories) will trip these guards so that introducing them becomes
a deliberate, reviewed action.

Surfaces:

* ``os.kill(pid, sig)`` — process signalling. Allowed only as
  signal-0 liveness probes inside ``open_prep/realtime_signals.py``
  (realtime engine PID file) and ``scripts/ib_client_id.py``
  (IB-client-id leasing registry).
* ``shutil.rmtree(...)`` — recursive deletion. Allowed only inside
  ``scripts/`` (one-shot artifact refresh tooling).
* ``socket.socket(...)`` — raw socket creation. Allowed only inside
  ``scripts/`` (local port-probe helpers).

The point is *zero new surface in production*: tests assert the AST hit
set equals the explicit allow-list. If a legitimate new caller is needed,
update the allow-list in the same PR with a brief justification in the
commit message.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator

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
}


def _iter_py_files() -> Iterator[Path]:
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        yield path


def _attr_call_sites(attr_owner: str, attr_name: str) -> set[tuple[str, int]]:
    """Return call sites for a specific ``owner.attr(...)`` pattern.

    Args:
        attr_owner: The module/object name referenced on the call receiver
            (for example ``"os"`` in ``os.kill(...)``).
        attr_name: The attribute/method name being called
            (for example ``"kill"`` in ``os.kill(...)``).

    Returns:
        A set of ``(relpath, lineno)`` tuples for each matching call site.
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != attr_name:
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != attr_owner:
                continue
            sites.add((rel, node.lineno))
    return sites


# --- os.kill -----------------------------------------------------------------

# Signal-0 liveness probes only. Every one of these call sites passes ``0``
# as the signal, so they cannot terminate a process — they merely check
# existence. Two contexts are currently allow-listed:
#   * ``open_prep/realtime_signals.py`` — realtime engine PID file probe.
#   * ``scripts/ib_client_id.py`` — IB API client_id slot leasing registry.
# New non-zero ``os.kill`` callers must be explicitly added below with
# justification.
OS_KILL_ALLOWED: set[tuple[str, int]] = {
    ("open_prep/realtime_signals.py", 181),
    ("open_prep/realtime_signals.py", 211),
    # Signal-0 PID liveness probe for the IB-client-id leasing registry
    # (claims an IB API client_id slot only if the previous owner is gone).
    ("scripts/ib_client_id.py", 81),
}


def test_os_kill_zero_surface_pin() -> None:
    sites = _attr_call_sites("os", "kill")
    unexpected = sites - OS_KILL_ALLOWED
    assert not unexpected, (
        "New os.kill(...) call site detected. Process signalling must remain "
        "confined to the allow-listed signal-0 liveness probes (realtime engine "
        "PID file + IB-client-id leasing registry). If genuinely needed, "
        "add the new (path, line) pair to OS_KILL_ALLOWED in this test with "
        "a justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = OS_KILL_ALLOWED - sites
    assert not missing, (
        "OS_KILL_ALLOWED entries no longer present in code. Update the "
        "allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )


# --- shutil.rmtree -----------------------------------------------------------

# Recursive deletion is destructive and must stay out of production runtime
# code. The only legitimate caller today is the artifact-refresh tooling under
# ``scripts/``.
SHUTIL_RMTREE_ALLOWED_DIR_PREFIXES: tuple[str, ...] = ("scripts/",)


def test_shutil_rmtree_zero_surface_pin() -> None:
    sites = _attr_call_sites("shutil", "rmtree")
    leaks = {
        (path, lineno)
        for (path, lineno) in sites
        if not path.startswith(SHUTIL_RMTREE_ALLOWED_DIR_PREFIXES)
    }
    assert not leaks, (
        "shutil.rmtree(...) found outside the allowed scripts/ surface. "
        "Recursive deletion is destructive — wrap the deletion behind an "
        "explicit confirmation flag, or move the helper into scripts/.\n"
        f"leaks = {sorted(leaks)}"
    )


# --- socket.socket -----------------------------------------------------------

# Raw socket creation in production code is almost always a smell — networking
# should go through the dedicated provider clients (Databento, Finnhub, FMP,
# etc.) that already centralise retry/auth/telemetry. The only allowed caller
# today is the local port-probe helper in scripts/.
SOCKET_SOCKET_ALLOWED_DIR_PREFIXES: tuple[str, ...] = ("scripts/",)


def test_socket_socket_zero_surface_pin() -> None:
    sites = _attr_call_sites("socket", "socket")
    leaks = {
        (path, lineno)
        for (path, lineno) in sites
        if not path.startswith(SOCKET_SOCKET_ALLOWED_DIR_PREFIXES)
    }
    assert not leaks, (
        "socket.socket(...) found outside the allowed scripts/ surface. "
        "Production network access should go through the dedicated provider "
        "clients (Databento/Finnhub/FMP) which centralise retry/auth/telemetry. "
        "If a raw socket is genuinely required, add the file prefix to "
        "SOCKET_SOCKET_ALLOWED_DIR_PREFIXES with justification.\n"
        f"leaks = {sorted(leaks)}"
    )

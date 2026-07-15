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
from collections.abc import Iterator
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

# WHERE os.kill may appear. Signal-0-ness is NOT checked here — this set pins
# only (path, lineno); `test_os_kill_only_ever_sends_signal_zero` below enforces
# that every site passes the literal 0. Keep the two apart: a real signal is a
# redesign, not something an entry in this set can legitimise (before 2026-07-15
# this header claimed the signal was verified when nothing read the argument).
# Two contexts are currently allow-listed:
#   * ``open_prep/realtime_signals.py`` — realtime engine PID file probe.
#   * ``scripts/ib_client_id.py`` — IB API client_id slot leasing registry.
OS_KILL_ALLOWED: set[tuple[str, int]] = {
    # Signal-0 PID liveness probes in _detect_rt_engine_pid(): existing PID
    # file check and pgrep result validation.
    # 2026-07-15 (reconcile): shifted 207/237 -> 208/238 by #3584/#3587 edits above.
    ("open_prep/realtime_signals.py", 208),
    ("open_prep/realtime_signals.py", 238),
    # 2026-07-15 (security review): THIRD signal-0 probe, added by #3584 without a
    # ledger entry -- this pin is not on the required path, so the addition merged
    # green. Reviewed and accepted: same class as the two above, not new signalling
    # capability. `_status()` re-validates a `running:true` payload whose PID may be
    # dead (the status file is written on START paths only, so a crashed engine
    # leaves running:true forever). Signal 0 sends nothing -- it only probes
    # existence -- and OSError is caught and mapped to alive=False.
    ("open_prep/realtime_signals.py", 267),
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


def _os_kill_non_zero_signals() -> set[tuple[str, int, str]]:
    """Return every ``os.kill(...)`` whose signal argument is not literal ``0``.

    ``OS_KILL_ALLOWED`` above pins only ``(path, lineno)`` — it says WHERE
    os.kill may appear, never WHAT it sends. Signal-0-ness is a property of the
    call, so it is checked here for every site rather than being allow-listable
    per line: a real signal is a redesign, not a ledger entry.

    Anything that is not the literal ``0`` is reported, including a dynamic
    expression (``os.kill(pid, sig)``) whose value cannot be known statically.
    """
    offenders: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "kill":
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "os":
                continue
            if len(node.args) < 2:
                offenders.add((rel, node.lineno, f"malformed: {ast.unparse(node)}"))
                continue
            sig = node.args[1]
            is_literal_zero = (
                isinstance(sig, ast.Constant)
                and isinstance(sig.value, int)
                and not isinstance(sig.value, bool)
                and sig.value == 0
            )
            if not is_literal_zero:
                offenders.add((rel, node.lineno, ast.unparse(sig)))
    return offenders


def test_os_kill_only_ever_sends_signal_zero() -> None:
    """The signal argument must be the literal ``0`` at every os.kill site.

    Closes a name-promises-more-than-the-test-measures gap (2026-07-15). The
    header above asserts "Every one of these call sites passes ``0`` as the
    signal, so they cannot terminate a process", but the collector only
    recorded ``(path, lineno)`` and never inspected the argument. Mutating an
    ALLOW-LISTED site in place --

        os.kill(pid, 0)  ->  os.kill(pid, signal.SIGKILL)

    -- left the line number untouched, so the inventory pin above stayed green
    while the process-signalling surface this file exists to bound had actually
    opened. Verified: that mutation passed before this test existed.
    """
    offenders = _os_kill_non_zero_signals()
    assert not offenders, (
        "os.kill(...) called with a signal other than the literal 0. Signal 0 "
        "sends nothing — it only probes whether a PID exists, which is the ONLY "
        "process-signalling this repo allows. A real signal can terminate a "
        "live trading engine, so it is not an allow-list entry: if one is "
        "genuinely required, it needs its own review and an explicit change to "
        "this test. A dynamic signal expression is rejected too — its value "
        "cannot be checked statically.\n"
        f"offenders = {sorted(offenders)}"
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

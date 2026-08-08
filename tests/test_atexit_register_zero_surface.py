"""Zero-surface pin for ``atexit.register(...)`` in production code.

``atexit`` callbacks fire at interpreter shutdown in LIFO order and run
*after* most logging has been torn down, which means that:

* exceptions raised inside an atexit handler are essentially invisible —
  they are written to ``sys.stderr`` only after structured logging is gone;
* a handler that blocks (for example, an HTTP/WS close that waits on a
  network ack) can stall pytest workers, CI runners, and Streamlit
  reload cycles;
* ordering between modules that all register handlers is implicit and
  hard to reason about, so adding new ones casually is a footgun.

The repository currently has four reviewed production ``atexit`` hooks
(see ``ATEXIT_REGISTER_ALLOWED``). The ledger is keyed by
``(relpath, enclosing qualname)`` with an expected call count, so ordinary
line shifts no longer churn the pin, and the detector resolves import
aliases (``import atexit as _atexit``) so an aliased hook cannot slip past
the guard. Any new ``atexit.register(...)`` site therefore becomes a
deliberate, reviewed change.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_production_py_files, parse_module

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


def _iter_py_files() -> list[Path]:
    return iter_production_py_files(_DIR_EXCLUDE)


def _atexit_aliases(tree: ast.Module) -> set[str]:
    """Every name under which ``atexit`` is imported in this file."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "atexit":
                    names.add(alias.asname or alias.name)  # captures `as _atexit`
    return names


def _atexit_register_sites() -> dict[tuple[str, str], int]:
    """``{(relpath, enclosing qualname): count}`` for each atexit.register call.

    Keyed by enclosing qualname (not line number) so ordinary line shifts do
    not churn the ledger, and resolves import aliases so an aliased
    ``import atexit as _atexit`` hook cannot bypass the guard.
    """
    sites: dict[tuple[str, str], int] = {}
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        aliases = _atexit_aliases(tree)
        if not aliases:
            continue
        rel = path.relative_to(ROOT).as_posix()

        def _visit(node: ast.AST, scope: str, rel: str = rel, aliases: set[str] = aliases) -> None:
            for child in ast.iter_child_nodes(node):
                child_scope = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    child_scope = f"{scope}.{child.name}" if scope else child.name
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "register"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id in aliases
                ):
                    key = (rel, scope or "<module>")
                    sites[key] = sites.get(key, 0) + 1
                _visit(child, child_scope)

        _visit(tree, "")
    return sites


# Keyed by ``(relpath, enclosing qualname): expected register count`` so that
# ordinary line shifts do not churn the pin. Every entry has been reviewed to
# be parameter-less, idempotent, and non-blocking:
#   * terminal_bitcoin._get_client: closes the lazily-created httpx client;
#     tolerates an already-closed connection.
#   * scripts/databento_production_export.main: single-flush cache-probe-log
#     dump (dump_cache_probe_log disables the singleton after one parquet write).
#   * services/live_overlay_daemon/feed._do_start: unregister-then-register keeps
#     exactly one feed.stop() hook; stop() sets an Event and joins with a
#     5s/thread timeout (bounded, non-deadlocking).
#   * newsstack_fmp/pipeline (module scope): _cleanup_singletons closes module
#     singletons; each close/stop is try/except-guarded and the handler nulls
#     every singleton at the end, so a repeat call is a no-op (idempotent). This
#     site uses ``import atexit as _atexit`` and was previously invisible to the
#     line/``atexit``-only detector (F4) — now covered by alias resolution.
ATEXIT_REGISTER_ALLOWED: dict[tuple[str, str], int] = {
    ("terminal_bitcoin.py", "_get_client"): 1,
    ("scripts/databento_production_export.py", "main"): 1,
    ("services/live_overlay_daemon/feed.py", "_do_start"): 1,
    ("newsstack_fmp/pipeline.py", "<module>"): 1,
    # 2026-07-11 (#3258): fail-soft one-shot provider-usage telemetry flush,
    # armed lazily on first recorded call; handler swallows all exceptions.
    ("newsstack_fmp/provider_usage.py", "<module>"): 1,
}


def test_atexit_register_zero_surface_pin() -> None:
    sites = _atexit_register_sites()

    unexpected = {k: v for k, v in sites.items() if k not in ATEXIT_REGISTER_ALLOWED}
    assert not unexpected, (
        "New atexit.register(...) call site detected. atexit handlers run "
        "after structured logging has been torn down and can deadlock CI / "
        "Streamlit reloads. If a new shutdown hook is genuinely required, "
        "add the (relpath, enclosing qualname) key to ATEXIT_REGISTER_ALLOWED "
        "with a justification in the commit message and ensure the handler is "
        "idempotent and non-blocking.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = {k: v for k, v in ATEXIT_REGISTER_ALLOWED.items() if k not in sites}
    assert not missing, (
        "ATEXIT_REGISTER_ALLOWED entries no longer present in code. Update "
        "the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )

    count_drift = {
        k: (ATEXIT_REGISTER_ALLOWED[k], sites[k])
        for k in ATEXIT_REGISTER_ALLOWED
        if k in sites and ATEXIT_REGISTER_ALLOWED[k] != sites[k]
    }
    assert not count_drift, (
        "atexit.register count changed for a ledgered site (expected, actual). "
        "A second hook in the same scope is almost certainly a bug.\n"
        f"count_drift = {count_drift}"
    )

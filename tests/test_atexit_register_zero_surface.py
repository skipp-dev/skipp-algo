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

The whole repository currently has exactly *one* production ``atexit``
hook: closing the lazily-initialised httpx client in ``terminal_bitcoin``.
Lock that surface in so any new ``atexit.register(...)`` site becomes a
deliberate, reviewed change.
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
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _atexit_register_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every ``atexit.register(...)`` call."""

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "register":
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "atexit":
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


# Single legitimate caller: closes the lazily-created httpx client used by
# the bitcoin terminal helpers. This handler is parameter-less, idempotent,
# and tolerates a connection that has already been closed.
# F-V8-perf-3.5 (2026-05-19, PR #2292): single-flush cache-probe-log dump for
# the sharded producer. Handler is parameter-less, idempotent (dump_cache_probe_log
# disables the singleton after writing) and bounded (one parquet write).
ATEXIT_REGISTER_ALLOWED: set[tuple[str, int]] = {
    ("terminal_bitcoin.py", 103),
    ("scripts/databento_production_export.py", 4716),  # PR #2787: FMP bridge (+260 lines); rebaselined PR #2810 (+7 lines)
    # 2026-06-19 (fix/live-overlay-daemon-security, C2): feed.start() registers a
    # bounded, idempotent shutdown hook (feed.stop()) so the daemon=True feed
    # threads get a chance to close the Databento loop/sockets on a non-lifespan
    # process exit. unregister-then-register keeps exactly one hook; stop() sets
    # an Event and joins with a 5s/thread timeout (bounded, non-deadlocking).
    # 2026-06-20 (lifecycle follow-up): keep this pin aligned to the current
    # atexit.register location in feed.start().
    # 2026-06-21 (PR #2879 rebase): feed lifecycle changes shifted this callsite.
    ("services/live_overlay_daemon/feed.py", 484),
}


def test_atexit_register_zero_surface_pin() -> None:
    sites = _atexit_register_sites()

    unexpected = sites - ATEXIT_REGISTER_ALLOWED
    assert not unexpected, (
        "New atexit.register(...) call site detected. atexit handlers run "
        "after structured logging has been torn down and can deadlock CI / "
        "Streamlit reloads. If a new shutdown hook is genuinely required, "
        "add the (path, line) pair to ATEXIT_REGISTER_ALLOWED with a "
        "justification in the commit message and ensure the handler is "
        "idempotent and non-blocking.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = ATEXIT_REGISTER_ALLOWED - sites
    assert not missing, (
        "ATEXIT_REGISTER_ALLOWED entries no longer present in code. Update "
        "the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )

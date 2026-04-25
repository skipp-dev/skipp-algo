"""Defense pin: ``time.sleep(...)`` growth ledger.

Synchronous ``time.sleep()`` blocks the current thread. In an async or
event-loop context it stalls every co-routine on the same loop; in a
request-handler context it ties up a worker; in a hot retry loop without
a backoff cap it produces a self-DoS pattern.

This ledger freezes today's surface (28 sites across 16 files). New
``time.sleep(...)`` calls must be *justified* — either replace with
``asyncio.sleep`` / a scheduled callback / a backoff-capped retry helper,
or extend ``_FROZEN_SITES`` with the (file, line) tuple after explicit
review. The ledger may only **shrink**, never grow.

CWE-400 (Uncontrolled Resource Consumption) — closely related anti-pattern.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

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

_FROZEN_SITES: dict[str, frozenset[int]] = {
    "newsstack_fmp/_bz_http.py": frozenset({133, 148}),
    "newsstack_fmp/ingest_benzinga.py": frozenset({196, 207}),
    "newsstack_fmp/ingest_fmp.py": frozenset({91, 109}),
    "newsstack_fmp/pipeline.py": frozenset({824}),
    "newsstack_fmp/shared_fetch.py": frozenset({273}),
    "newsstack_fmp/store_sqlite.py": frozenset({80, 85}),
    "open_prep/alerts.py": frozenset({409, 419}),
    "open_prep/error_taxonomy.py": frozenset({117}),
    "open_prep/macro.py": frozenset({565, 578}),
    "open_prep/realtime_signals.py": frozenset({265, 338, 1590, 2691, 2704}),
    "open_prep/run_open_prep.py": frozenset({1695, 1697}),
    "scripts/smc_fmp_client.py": frozenset({194}),
    "scripts/start_open_prep_suite.py": frozenset({69}),
    "terminal_bitcoin.py": frozenset({864, 866}),
    "terminal_technicals.py": frozenset({287}),
    "terminal_tradingview_news.py": frozenset({352}),
}

_FROZEN_TOTAL = sum(len(v) for v in _FROZEN_SITES.values())


def _is_time_sleep(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id == "time"
    )


def _collect_sites() -> dict[str, set[int]]:
    sites: dict[str, set[int]] = {}
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        local: set[int] = set()
        for node in ast.walk(tree):
            if _is_time_sleep(node):
                local.add(node.lineno)
        if local:
            rel = str(path.relative_to(_REPO_ROOT))
            sites[rel] = local
    return sites


def test_total_time_sleep_count_does_not_grow() -> None:
    sites = _collect_sites()
    total = sum(len(v) for v in sites.values())
    assert total <= _FROZEN_TOTAL, (
        f"time.sleep(...) total grew: expected <= {_FROZEN_TOTAL}, got {total}. "
        "Replace with asyncio.sleep / backoff-capped retry, or extend _FROZEN_SITES."
    )


def test_no_new_files_with_time_sleep() -> None:
    sites = _collect_sites()
    new_files = sorted(set(sites) - set(_FROZEN_SITES))
    assert not new_files, (
        f"New files with time.sleep(): {new_files}. "
        "Synchronous sleep blocks the thread/loop. Use asyncio.sleep or a "
        "backoff helper, or add the file+lines to _FROZEN_SITES."
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_SITES))
def test_per_file_does_not_grow(rel: str) -> None:
    sites = _collect_sites()
    current = sites.get(rel, set())
    expected = _FROZEN_SITES[rel]
    assert len(current) <= len(expected), (
        f"{rel}: time.sleep() count grew from {len(expected)} to {len(current)}. "
        "Replace with asyncio.sleep / backoff helper, or update _FROZEN_SITES."
    )

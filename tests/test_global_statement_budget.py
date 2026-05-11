"""Audit pin: ``global`` statement frozen-inventory budget.

Module-level mutable state with ``global`` is a common cause of:
* test flakiness (state leaks between tests),
* concurrency bugs (no synchronisation around the assignment),
* dependency-injection blockers (singletons can't be overridden cleanly).

The current production codebase has 24 ``global`` statements, all
documented module-level singletons (rate-limit cooldown counters,
TradingView 429 backoff state, lazy provider singletons, regime-state
remembrance, Streamlit tab-availability flags).  Defense pin freezes
that inventory:

* New ``global`` statement → no-new-sites tripwire fires; reviewer
  must justify (could it be a class attribute? injected dependency?
  ``contextvars.ContextVar``?).
* Each frozen site is parametrised — if it moves or its declared
  names change, the ledger must be refreshed.
* Bidirectional inventory parity ensures the two cannot drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        # Note: ``scripts/`` is intentionally **NOT** excluded — V5 audit
        # (F-V5-G1, 2026-05-01) found that excluding it had hidden a
        # production regression in ``scripts/databento_production_export.py``.
        # Test-suite helpers under ``tests/`` are still excluded since
        # module-level fixtures legitimately use ``global`` for test setup.
        "tests",
        "SMC++",
    }
)


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _all_sites() -> list[tuple[str, int, tuple[str, ...]]]:
    """Yield ``(rel, lineno, names)`` triples for every ``global`` statement."""
    out: list[tuple[str, int, tuple[str, ...]]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                out.append((rel, node.lineno, tuple(node.names)))
    return out


# Frozen inventory of production ``global`` statements at the time this
# pin landed.  Each tuple is ``(rel, lineno, sorted-names)``.  Names are
# captured to catch silent mutation of an existing statement (someone
# adding a new global to an already-ledgered line).
_FROZEN_SITES: frozenset[tuple[str, int, tuple[str, ...]]] = frozenset(
    {
        ("databento_reference.py", 113, ("_STATE_CACHE_MTIME", "_STATE_CACHE_PATH", "_STATE_CACHE_VALUE")),
        ("databento_reference.py", 121, ("_STATE_CACHE_MTIME", "_STATE_CACHE_PATH", "_STATE_CACHE_VALUE")),
        ("newsstack_fmp/pipeline.py", 69, ("_store",)),
        ("newsstack_fmp/pipeline.py", 79, ("_fmp_adapter", "_fmp_adapter_key")),
        ("newsstack_fmp/pipeline.py", 94, ("_bz_rest_adapter", "_bz_rest_adapter_key")),
        ("newsstack_fmp/pipeline.py", 110, ("_bz_ws_adapter", "_bz_ws_adapter_key")),
        ("newsstack_fmp/pipeline.py", 136, ("_enricher",)),
        ("newsstack_fmp/pipeline.py", 1068, ("_last_meta",)),
        (
            "newsstack_fmp/pipeline.py",
            1157,
            ("_bz_rest_adapter", "_bz_ws_adapter", "_enricher", "_fmp_adapter", "_last_meta", "_store"),
        ),
        (
            "newsstack_fmp/pipeline.py",
            1158,
            ("_bz_rest_adapter_key", "_bz_ws_adapter_key", "_fmp_adapter_key"),
        ),
        ("open_prep/regime.py", 129, ("_prev_regime",)),
        ("open_prep/regime.py", 156, ("_prev_regime",)),
        # F-V5-G1 (2026-05-01): pre-existing site surfaced when ``scripts/``
        # was added to the audit scope. TODO move to a class attribute or
        # injected dependency in a follow-up PR.
        # Phase-5.2 Quickfix bundle B (PR #2058+): line shifted 687→700 by
        # the BentoHttpAPI.TIMEOUT module-patch insertion at the top of file.
        # P5.3-A7 (PR pending): line shifted 700→729 by ThreadPoolExecutor
        # imports + STEP8_SUBSTEP_PARALLELISM constant + _rss_mib_snapshot helper
        # inserted at top of file.
        # A8-Telemetry-Mini (PR pending): line shifted 729→734 by the
        # ``_fmt_rss_mib`` formatter helper added next to ``_rss_mib_snapshot``
        # for Step 9 RSS-bracket telemetry.
        # A8.1 (PR #2078): line shifted 734→781 by ``_rss_current_mib`` +
        # ``_fmt_rss_pair`` helpers added for current+peak RSS instrumentation
        # (see commit 9e93416c). Q1 obs(workbook): line shifted 781→782 by
        # ``Callable`` import added for ``progress_callback`` plumbing.
        (
            "scripts/databento_production_export.py",
            782,
            ("_DEFAULT_BULLISH_QUALITY_CFG",),
        ),
        ("smc_tv_bridge/smc_api.py", 184, ("_candle_provider",)),
        ("smc_tv_bridge/smc_api.py", 192, ("_regime_provider",)),
        ("smc_tv_bridge/smc_api.py", 200, ("_tech_provider",)),
        (
            "streamlit_terminal.py",
            591,
            ("btc_available", "databento_available", "ensure_rt_engine_running", "newsapi_available", "tv_available"),
        ),
        ("terminal_bitcoin.py", 97, ("_client",)),
        (
            "terminal_finnhub.py",
            187,
            (
                "_consecutive_429_count",
                "_rate_limit_backoff_until",
                "_social_sentiment_blocked",
            ),
        ),
        ("terminal_finnhub.py", 613, ("_social_sentiment_blocked",)),
        ("terminal_spike_scanner.py", 96, ("_YF_UNIVERSE_CACHE",)),
        ("terminal_technicals.py", 212, ("_tv_consecutive_429s", "_tv_cooldown_until")),
        (
            "terminal_technicals.py",
            213,
            ("_tv_last_429_log_key", "_tv_last_429_log_ts", "_tv_suppressed_429_logs"),
        ),
        ("terminal_technicals.py", 245, ("_tv_consecutive_429s",)),
        ("terminal_technicals.py", 262, ("_tv_cooldown_ended_at", "_tv_last_call_ts")),
        ("terminal_tradingview_news.py", 403, ("_last_request_ts",)),
    }
)


def _normalised_current() -> set[tuple[str, int, tuple[str, ...]]]:
    return {(rel, lineno, tuple(sorted(names))) for rel, lineno, names in _all_sites()}


def test_no_new_global_statements() -> None:
    """Tripwire: every new ``global`` deserves a deliberate review."""
    new_sites = sorted(_normalised_current() - _FROZEN_SITES)
    assert not new_sites, (
        "New ``global`` statement detected — could the state move to a "
        "class attribute, an injected dependency, or a "
        "``contextvars.ContextVar``? If a singleton is genuinely "
        "required, extend _FROZEN_SITES with the (file, line, "
        "sorted-names) tuple:\n  - "
        + "\n  - ".join(f"{rel}:{lineno} {names}" for rel, lineno, names in new_sites)
    )


@pytest.mark.parametrize(
    ("rel", "lineno", "names"),
    sorted(_FROZEN_SITES),
)
def test_frozen_global_site_still_present(
    rel: str, lineno: int, names: tuple[str, ...]
) -> None:
    """Stale guard: every ledger entry must still match a ``global`` with the same names."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Global) and node.lineno == lineno:
            actual = tuple(sorted(node.names))
            assert actual == names, (
                f"{rel}:{lineno}: ``global`` names changed "
                f"(expected {names!r}, found {actual!r}) — "
                f"refresh _FROZEN_SITES."
            )
            return
    raise AssertionError(
        f"{rel}:{lineno}: ``global`` statement no longer present — "
        f"refresh _FROZEN_SITES (statement may have moved by ±N lines)."
    )


def test_global_inventory_parity() -> None:
    """Bidirectional parity: ledger ∪ scan must be identical."""
    current = _normalised_current()
    missing_from_ledger = current - _FROZEN_SITES
    stale_in_ledger = _FROZEN_SITES - current
    assert not missing_from_ledger and not stale_in_ledger, (
        f"global ledger drift: "
        f"new={sorted(missing_from_ledger)} "
        f"stale={sorted(stale_in_ledger)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )

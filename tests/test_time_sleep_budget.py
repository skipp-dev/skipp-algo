"""Audit pin: ``time.sleep(...)`` frozen-inventory budget.

``time.sleep`` blocks the calling thread.  In production it is only
appropriate for **rate-limiting / retry-backoff / throttling** on a
worker thread the caller owns; using it inside an event loop, an
asyncio coroutine, or on the request-serving thread is a bug.

Current production codebase has 26 ``time.sleep(...)`` call sites, all
of which fall into the rate-limit / retry-backoff / inter-poll-throttle
category.  This pin freezes that inventory:

- New ``time.sleep`` sites fail the no-new-sites tripwire and force a
  deliberate review (asyncio? threaded worker? rate-limit constant?).
- Each ledgered site is parametrised — if it moves or disappears, the
  ledger must be refreshed.
- Bidirectional inventory parity ensures the two cannot drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import MIN_EXPECTED_PROD_FILES, parse_module

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
        "scripts",
        "tests",
        "SMC++",
    }
)


def _list_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _is_time_sleep_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id == "time"
    )


def _all_time_sleep_sites() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in _list_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        tree = parse_module(path)
        if tree is None:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_time_sleep_call(node):
                out.append((rel, node.lineno))
    return out


# Frozen inventory of rate-limit / backoff / throttle ``time.sleep``
# sites at the time this pin landed.  Categories observed:
#   * rate-limit between API calls (TradingView 429, FMP, Benzinga)
#   * retry backoff (exponential ``2 ** attempt``)
#   * inter-poll throttle (Streamlit/realtime poll loops)
#   * SQLite contention backoff
# Extend deliberately when (a) a new site is added with documented
# reason, or (b) an existing site moves by ±N lines.
_FROZEN_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("newsstack_fmp/ingest_benzinga.py", 197),
        ("newsstack_fmp/ingest_benzinga.py", 208),
        ("newsstack_fmp/ingest_fmp.py", 136),
        ("newsstack_fmp/ingest_fmp.py", 154),
        # PR #2154: ingest_fmp_filings.py shifted +8 (121→129, 134→142)
        # by the FMP-13F probe instrumentation + retry-after-Header parser.
        # Both sleeps remain legit retry-backoff (HTTP 429 + connect error).
        ("newsstack_fmp/ingest_fmp_filings.py", 129),
        ("newsstack_fmp/ingest_fmp_filings.py", 142),
        # PR #2154: open_prep/macro.py shifted +35/+36 (726→761, 744→780)
        # by FMP-13F probe instrumentation. Sleeps unchanged: legit
        # retry-backoff (HTTP 429 + connect error).
        # 2026-06-11 (eval-findings B8): surprise-scale comment block +8
        # (776→784, 795→803).
        # 2026-06-13: profile-bulk pagination constant shifted +1
        # (784→785, 803→804); sleeps unchanged: retry-backoff paths.
        ("open_prep/macro.py", 803),
        ("open_prep/macro.py", 822),
        ("newsstack_fmp/ingest_fmp_political.py", 122),
        ("newsstack_fmp/ingest_fmp_political.py", 135),
        ("newsstack_fmp/shared_fetch.py", 297),
        ("newsstack_fmp/pipeline.py", 1256),
        ("newsstack_fmp/store_sqlite.py", 81),
        ("newsstack_fmp/store_sqlite.py", 86),
        ("open_prep/alerts.py", 408),
        ("open_prep/alerts.py", 418),
        ("open_prep/error_taxonomy.py", 117),
        ("open_prep/realtime_signals.py", 279),
        ("open_prep/realtime_signals.py", 354),
        ("open_prep/realtime_signals.py", 1844),
        ("open_prep/realtime_signals.py", 2978),
        ("open_prep/realtime_signals.py", 2991),
        # 2026-06-11 (eval-findings D7): technical_analysis import block
        # +8 lines (1943→1951, 1945→1953).
        ("open_prep/run_open_prep.py", 2034),
        ("open_prep/run_open_prep.py", 2036),
        ("newsstack_fmp/_bz_http.py", 44),
        ("terminal_bitcoin.py", 846),
        ("terminal_bitcoin.py", 848),
        # 2026-06-10 (#2670 W3): source-field additions shifted +6 (286 -> 292).
        # 2026-06-19 (timeframe expansion): INTERVAL_MAP/default list additions
        # shifted the throttle sleep site 293 -> 294.
        ("terminal_technicals.py", 294),
        ("terminal_tradingview_news.py", 409),
        # 2026-06-24 feat/benzinga-rss-improvements (issue #2925): RSS-4 retry
        # backoff sleeps (3 attempts with 1s/2s/4s delays) for transient errors
        # in RSS adapter, plus existing REST client retry backoffs shifted +1.
        ("newsstack_fmp/ingest_benzinga.py", 198),
        ("newsstack_fmp/ingest_benzinga.py", 209),
        ("newsstack_fmp/ingest_benzinga.py", 915),
    }
)


def test_no_new_time_sleep_sites() -> None:
    """Tripwire: every new ``time.sleep(...)`` deserves a deliberate review."""
    current = set(_all_time_sleep_sites())
    new_sites = sorted(current - _FROZEN_SITES)
    assert not new_sites, (
        "New time.sleep(...) call site detected — confirm it's a "
        "legitimate rate-limit / retry-backoff / throttle (not an "
        "event-loop blocker / spin-wait / fixed wall-clock pause). For "
        "asyncio code prefer ``await asyncio.sleep(...)``. Then extend "
        "_FROZEN_SITES with the new (file, line) tuple:\n  - "
        + "\n  - ".join(f"{rel}:{lineno}" for rel, lineno in new_sites)
    )


@pytest.mark.parametrize(("rel", "lineno"), sorted(_FROZEN_SITES))
def test_frozen_time_sleep_site_still_present(rel: str, lineno: int) -> None:
    """Stale guard: every ledger entry must still match a ``time.sleep(...)`` call."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    tree = parse_module(path)
    assert tree is not None, f"{rel} no longer parses — refresh frozen ledger"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.lineno == lineno
            and _is_time_sleep_call(node)
        ):
            return
    raise AssertionError(
        f"{rel}:{lineno}: ``time.sleep(...)`` no longer present — "
        f"refresh _FROZEN_SITES (call may have moved by ±N lines)."
    )


def test_time_sleep_inventory_parity() -> None:
    """Bidirectional parity: ledger ∪ scan must be identical."""
    current = set(_all_time_sleep_sites())
    missing_from_ledger = current - _FROZEN_SITES
    stale_in_ledger = _FROZEN_SITES - current
    assert not missing_from_ledger and not stale_in_ledger, (
        f"time.sleep ledger drift: "
        f"new={sorted(missing_from_ledger)} "
        f"stale={sorted(stale_in_ledger)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _list_prod_files()
    assert len(files) >= MIN_EXPECTED_PROD_FILES, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )

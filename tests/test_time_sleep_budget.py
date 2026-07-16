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
        # 2026-06-24 feat/benzinga-rss: REST client retry backoff.
        ("newsstack_fmp/ingest_benzinga.py", 298),  # 284→298 (2026-07-12): fetch_news 429 wire + import block
        ("newsstack_fmp/ingest_benzinga.py", 309),  # 295→309 (2026-07-12): fetch_news 429 wire + import block
        ("newsstack_fmp/ingest_fmp.py", 143),  # +1 (2026-07-10): docstring 3→4 endpoints
        ("newsstack_fmp/ingest_fmp.py", 169),  # +1 (2026-07-10): docstring 3→4 endpoints
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
        ("open_prep/macro.py", 818),  # 2026-07-08 H3 response-bytes accounting shifted (+9)
        ("open_prep/macro.py", 837),  # 2026-07-08 H3 response-bytes accounting shifted (+9)
        ("newsstack_fmp/ingest_fmp_political.py", 122),
        ("newsstack_fmp/ingest_fmp_political.py", 135),
        ("newsstack_fmp/shared_fetch.py", 337),
        ("newsstack_fmp/pipeline.py", 1273),  # 2026-07-11 bz-direct display_output shifted (+4: 1264->1268)
        ("newsstack_fmp/store_sqlite.py", 81),
        ("newsstack_fmp/store_sqlite.py", 86),
        # 2026-07-01: alert candidate/throttle hardening + payload/url guards
        # shifted webhook retry sleeps 452/462 -> 489/499; semantics
        # unchanged: webhook retry-backoff paths.
        # 2026-07-02: SSRF path/query hardening shifted 489/499 -> 525/535.
        # 2026-07-02: target-host canonicalization + invalid-target guard
        # shifted webhook retry sleeps 527/537 -> 546/556.
        # 2026-07-04 (Workstream C): weather line + alert_weather_change added
        # above shifted the retry-backoff sleeps 546->595, 556->605.
        ("open_prep/alerts.py", 616),  # 2026-07-13 (drop dead last_exc tracking): 617->616
        ("open_prep/alerts.py", 625),  # 2026-07-13 (drop dead last_exc tracking): 627->625
        ("open_prep/error_taxonomy.py", 117),
        # 2026-06-28 (semantic monitoring): all realtime_signals sleep sites
        # shifted +20/+20/+72/+80/+80 lines by readiness metrics.
        ("open_prep/realtime_signals.py", 321),   # 2026-07-13 (status liveness re-validate above): 306->321
        ("open_prep/realtime_signals.py", 396),    # 2026-07-13 (status liveness re-validate above): 381->396
        ("open_prep/realtime_signals.py", 2323),  # 2026-07-16 targeted profile throttle: 2308->2323
        ("open_prep/realtime_signals.py", 3580),  # 2026-07-16 (FMP endpoint telemetry + bounded enrichment): 3552->3580
        ("open_prep/realtime_signals.py", 3596),  # 2026-07-16 (FMP endpoint telemetry + bounded enrichment): 3568->3596
        # 2026-06-11 (eval-findings D7): technical_analysis import block
        # +8 lines (1943→1951, 1945→1953).
        # 2026-07-04 (market-microstructure observe-only): module import
        # shifted these rate-limit sleeps +1 (2038->2039, 2040->2041).
        ("open_prep/run_open_prep.py", 1991),  # 2026-07-13 (upgrades/downgrades KNOWN-INERT disclosure above): 1987->1991
        ("open_prep/run_open_prep.py", 1989),  # 2026-07-13: second sleep after disclosure shift (1985->1989)
        ("newsstack_fmp/_bz_http.py", 44),
        # 2026-07-11 (truth-audit): removed inert _TECHNICALS_429_TTL + dead 429 branch (-5).
        ("terminal_bitcoin.py", 841),
        ("terminal_bitcoin.py", 843),
        # 2026-06-10 (#2670 W3): source-field additions shifted +6 (286 -> 292).
        # 2026-06-19 (timeframe expansion): INTERVAL_MAP/default list additions
        # shifted the throttle sleep site 293 -> 294.
        # 2026-07-09 (fix/tv-throttle-cooldown-fmp): -1 (removed _CACHE_ERROR_TTL_S)
        # +4 (clock-step clamp comment) shifted the throttle sleep 294 -> 297.
        ("terminal_technicals.py", 296),  # 2026-07-12 (drop dead "10m"): 297->296
        ("terminal_tradingview_news.py", 409),
        # 2026-06-24 feat/benzinga-rss: retry backoff sleeps in REST client
        # (198→199, 209→210 after RSS improvements).
        # 2026-06-24 feat/benzinga-rss-improvements: added retry sleep in
        # parallel fetch worker (line 901 after thread-safety follow-up).
        # 2026-07-03: shifted 919 -> 937 by the new _rss_http_get() helper
        # (feedparser.parse has no timeout kwarg; fetch bytes via httpx first).
        ("newsstack_fmp/ingest_benzinga.py", 298),  # 284→298 (2026-07-12): fetch_news 429 wire + import block
        ("newsstack_fmp/ingest_benzinga.py", 309),  # 295→309 (2026-07-12): fetch_news 429 wire + import block
        ("newsstack_fmp/ingest_benzinga.py", 1035),  # 1021→1035 (2026-07-12): fetch_news 429 wire + import block
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

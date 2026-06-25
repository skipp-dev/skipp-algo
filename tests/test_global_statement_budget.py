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

from tests._guard_corpus import parse_module

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
        tree = parse_module(path)
        if tree is None:  # pragma: no cover - defensive
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
        ("databento_reference.py", 137, ("_STATE_CACHE_MTIME", "_STATE_CACHE_PATH", "_STATE_CACHE_VALUE")),
        ("databento_reference.py", 145, ("_STATE_CACHE_MTIME", "_STATE_CACHE_PATH", "_STATE_CACHE_VALUE")),
        ("newsstack_fmp/pipeline.py", 70, ("_store",)),
        ("newsstack_fmp/pipeline.py", 79, ("_fmp_adapter", "_fmp_adapter_key")),
        ("newsstack_fmp/pipeline.py", 93, ("_bz_rest_adapter", "_bz_rest_adapter_key")),
        ("newsstack_fmp/pipeline.py", 108, ("_bz_ws_adapter", "_bz_ws_adapter_key")),
        ("newsstack_fmp/pipeline.py", 134, ("_bz_rss_adapter",)),
        ("newsstack_fmp/pipeline.py", 143, ("_enricher",)),
        ("newsstack_fmp/pipeline.py", 1116, ("_last_meta",)),
        (
            "newsstack_fmp/pipeline.py",
            1205,
            ("_bz_rest_adapter", "_bz_rss_adapter", "_bz_ws_adapter", "_enricher", "_fmp_adapter", "_last_meta", "_store"),
        ),
        (
            "newsstack_fmp/pipeline.py",
            1206,
            ("_bz_rest_adapter_key", "_bz_ws_adapter_key", "_fmp_adapter_key"),
        ),
        ("open_prep/regime.py", 129, ("_prev_regime",)),
        ("open_prep/regime.py", 156, ("_prev_regime",)),
        # R-E2 audit (2026-06-14): thread-safe one-time guard for
        # _normalize_tls_certificate_env os.environ write (see macro.py R-E2).
        # Line shifted 145→148 by M1 iteration-limit addition (PR #2828).
        ("open_prep/macro.py", 148, ("_TLS_NORM_DONE",)),
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
        # P5.4 A3 (PR #2194): line shifted 782→783 by the
        # ``from scripts._progress_flush import flush_progress_streams``
        # import added near the top for the extracted SSOT flush helper.
        # Bridge 1c (PR #2197): line shifted 783→844 by the
        # ``DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES`` + env-resolver
        # block inserted next to ``SMC_BASE_ONLY_CANONICAL_WORKBOOK_SHEET_NAMES``
        # to fix the 5 consecutive cron OOMs 2026-05-11 → 2026-05-13.
        (
            "scripts/databento_production_export.py",
            843,
            ("_DEFAULT_BULLISH_QUALITY_CFG",),
        ),
        # WP-H (PR #2612): lines shifted 184/192/200 -> 186/194/202 by the
        # ``import math``/``import threading`` + VIX overlay helper block added
        # above the lazy provider getters in smc_api.py.
        # 2026-06-19 (timeframe expansion): added 10m/30m map entries,
        # shifting provider-global sites 186/194/202 -> 192/200/208.
        ("smc_tv_bridge/smc_api.py", 192, ("_candle_provider",)),
        ("smc_tv_bridge/smc_api.py", 200, ("_regime_provider",)),
        ("smc_tv_bridge/smc_api.py", 208, ("_tech_provider",)),
        (
            "streamlit_terminal.py",
            599,
            ("btc_available", "databento_available", "ensure_rt_engine_running", "newsapi_available", "tv_available"),
        ),
        # F-V8-perf-3.5 (2026-05-19): opt-in cache probe log for the sharded
        # producer. The singleton stays disabled (`None`) until the workflow
        # sets DATABENTO_CACHE_PROBE_LOG and the producer explicitly enables it.
        # F-002 (PR #2295): extracted enable/reset helpers; the original
        # 5601-site relocated to enable_cache_probe_log()/reset_cache_probe_log().
        ("databento_volatility_screener.py", 87, ("_CACHE_PROBE_LOG",)),
        ("databento_volatility_screener.py", 94, ("_CACHE_PROBE_LOG",)),
        ("terminal_bitcoin.py", 96, ("_client",)),
        (
            "terminal_finnhub.py",
            213,
            (
                "_consecutive_429_count",
                "_rate_limit_backoff_until",
                "_social_sentiment_blocked",
            ),
        ),
        (
            "terminal_finnhub.py",
            619,
            (
                "_consecutive_429_count",
                "_rate_limit_backoff_until",
                "_social_sentiment_blocked",
            ),
        ),
        ("terminal_spike_scanner.py", 96, ("_YF_UNIVERSE_CACHE",)),
        # 2026-06-10 (#2670 W3): TechnicalResult gained a `source` field +
        # dc_replace import, shifting the four global sites +6 (212/213/245/262
        # -> 218/219/251/268).
        # 2026-06-19 (timeframe expansion): added 10m map/default interval,
        # shifting these global sites 219/220/252/269 -> 220/221/253/270.
        ("terminal_technicals.py", 220, ("_tv_consecutive_429s", "_tv_cooldown_until")),
        (
            "terminal_technicals.py",
            221,
            ("_tv_last_429_log_key", "_tv_last_429_log_ts", "_tv_suppressed_429_logs"),
        ),
        ("terminal_technicals.py", 253, ("_tv_consecutive_429s",)),
        ("terminal_technicals.py", 270, ("_tv_cooldown_ended_at", "_tv_last_call_ts")),
        ("terminal_tradingview_news.py", 403, ("_last_request_ts",)),
        # 2026-06-16 (feat/live-overlay-daemon): daemon singletons guarded by
        # threading.Lock() per concurrency-shared-mutables guideline.
        # 2026-06-17 (fix/overlay-daemon-robustness): shifted by logging import,
        # eviction helpers, circuit-breaker, readiness event, configurable TTL.
        # 2026-07-07 (fix/cache-eviction): added _last_eviction_at (L5).
        # 2026-06-19 (fix/live-overlay-post-merge-bugs): init_bar_cache gained
        # runtime deque-cap migration for existing symbols, shifting cache.py
        # global statements to 63/129/178.
        # 2026-06-19 (bug-hunt hardcap): immediate downscale cap-enforcement and
        # single-pass cap-eviction in push_bar shifted cache.py global lines to
        # 67/144/193.
        # 2026-06-19 (bug-hunt follow-up): patch_overlay gained explicit
        # allow_none_keys semantics for flow-field stale-state fixes, shifting
        # cache.py set_vix global line 198 -> 210.
        # 2026-06-20 (cache defensive copy): added copy import shifted globals +1.
        ("services/live_overlay_daemon/cache.py", 49, ("_max_symbols", "_rolling_bars_cap")),
        ("services/live_overlay_daemon/cache.py", 69, ("_last_eviction_at",)),
        ("services/live_overlay_daemon/cache.py", 146, ("_overlay_computed_at",)),
        ("services/live_overlay_daemon/cache.py", 216, ("_vix_level",)),
        # 2026-06-19 (fix/live-overlay-post-merge-bugs): separate _news_checked_at
        # from _news_loaded_at so missing-file rate-limiting does not pin the
        # success cache for the full TTL when a snapshot appears later.
        # 2026-06-19 (bug-hunt): added _news_lock + with-block around
        # _load_news_snapshot cache mutation for atomic state transitions.
        # 2026-06-23 (delivery-gap write-through): _persist_snapshot helper +
        # loader write-through calls shifted globals 121/199/300/347 ->
        # 144/226/331/379.
        # 2026-06-23 (mainline sync): active compute.py surface exposes
        # news/signals/experiment cache globals at 144/226/331/379.
        # 2026-06-23 (feat/grafana-tv-credential-age): TradingView credential
        # snapshot loader inserts a 5th global and shifts the news/signals/
        # experiment anchors to 161/243/333/448/496.
        # 2026-06-23 (Copilot/E702 follow-up): _persist_snapshot semicolon split +
        # log call formatting shifted globals to 164/246/336/451/499.
        # 2026-06-23 (audit #2909 F3): _validate_https_url helper added above the
        # fetchers shifted globals to 176/257/343/457/505.
        # 2026-06-23 (audit follow-up F2/F3): shared snapshot-fetch helper +
        # parsed GitHub-contents detection shifted globals to
        # 252/326/400/514/562.
        # 2026-06-23 (audit F2: _persist_snapshot finally-cleanup): +3 lines
        # before fetchers shifted globals to 255/328/401/515/563.
        ("services/live_overlay_daemon/compute.py", 255, ("_news_cache", "_news_checked_at", "_news_loaded_at")),
        # 2026-06-23 (feat/grafana-trading-signals): realtime trading-signals
        # snapshot loader mirrors the news snapshot caching pattern.
        ("services/live_overlay_daemon/compute.py", 328, ("_signals_cache", "_signals_checked_at", "_signals_loaded_at")),
        # 2026-06-23 (feat/grafana-tv-credential-age): credential-health report
        # loader mirrors the same snapshot caching pattern.
        ("services/live_overlay_daemon/compute.py", 401, ("_tradingview_credential_cache", "_tradingview_credential_checked_at", "_tradingview_credential_loaded_at")),
        # 2026-06-23 (feat/grafana-experiment-timeline): daily experiment rollup
        # + per-day history loaders mirror the same snapshot caching pattern.
        # 2026-06-24 (feat/live-overlay-credential-health): +5 lines for
        # _load_credential_health_snapshot alias shifted globals to 520/568.
        ("services/live_overlay_daemon/compute.py", 520, ("_experiment_cache", "_experiment_checked_at", "_experiment_loaded_at")),
        ("services/live_overlay_daemon/compute.py", 568, ("_experiment_history_cache", "_experiment_history_checked_at", "_experiment_history_loaded_at")),
        # 2026-06-21 (provider/bridge + queue backpressure follow-ups):
        # feed.py gained additional helper/config blocks, shifting global
        # statements to 362/420/496.
        # 2026-06-22 follow-ups shifted these anchors to 365/423/512.
        # Post-merge sync with main shifted these anchors to 374/432/521.
        ("services/live_overlay_daemon/feed.py", 373, ("_last_bar_at",)),
        ("services/live_overlay_daemon/feed.py", 431, ("_feed_thread", "_flow_refresh_thread", "_refresh_thread")),
        ("services/live_overlay_daemon/feed.py", 520, ("_feed_thread", "_flow_refresh_thread", "_refresh_thread")),
        # 2026-06-21: optional external bridge snapshot caches are guarded by
        # module locks and cached via module-level singleton snapshots.
        # 2026-06-23: workflow bridge hardening (status/conclusion semantics,
        # owner/repo encoding and pagination note) shifted this global anchor.
        ("services/live_overlay_daemon/github_workflow_bridge.py", 208, ("_cached_at_monotonic", "_cached_snapshot")),
        ("services/live_overlay_daemon/uptimerobot_bridge.py", 140, ("_cached_at_monotonic", "_cached_snapshot")),
        # 2026-06-24 (feat/railway-metrics): Railway GraphQL bridge for container
        # metrics exposes a lazily-refreshed TTL cache (mirroring uptimerobot).
        ("services/live_overlay_daemon/railway_metrics.py", 184, ("_CACHE", "_CACHE_EXPIRES_AT")),
        ("services/live_overlay_daemon/railway_metrics.py", 230, ("_CACHE", "_CACHE_EXPIRES_AT")),
        # 2026-06-19 (fix/live-overlay-post-merge-bugs): added non-finite JSON
        # sanitization helper and related imports, shifting _startup_ts line.
        # 2026-06-19 (Copilot follow-up): _VALID_TFS contract alignment shifted
        # surrounding code; 2026-06-20 (liveness/readiness split +
        # basic-auth endpoint updates) shifted _startup_ts to line 71.
        # 2026-06-21 (auth decode hardening): binascii import shifted
        # _startup_ts to line 72.
        ("services/live_overlay_daemon/main.py", 72, ("_startup_ts",)),
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
    tree = parse_module(path)
    assert tree is not None, f"{rel} no longer parses — refresh frozen ledger"
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

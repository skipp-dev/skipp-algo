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
        ("newsstack_fmp/pipeline.py", 113, ("_bz_ws_adapter", "_bz_ws_adapter_key")),  # 2026-07-11 bz-direct key-select (+3: 108->111)
        ("newsstack_fmp/pipeline.py", 142, ("_bz_rss_adapter",)),  # 2026-07-11 bz-direct key-select (+3: 134->137)
        ("newsstack_fmp/pipeline.py", 151, ("_enricher",)),  # 2026-07-11 bz-direct key-select (+3: 143->146)
        ("newsstack_fmp/pipeline.py", 1079, ("_last_meta",)),  # 2026-07-19 remove retired TradingView pipeline lane (-45)
        (
            # 2026-07-19 remove retired TradingView pipeline lane (-44)
            "newsstack_fmp/pipeline.py",
            1168,
            ("_bz_rest_adapter", "_bz_rss_adapter", "_bz_ws_adapter", "_enricher", "_fmp_adapter", "_last_meta", "_store"),
        ),
        (
            # 2026-07-19 remove retired TradingView pipeline lane (-44)
            "newsstack_fmp/pipeline.py",
            1169,
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
            851,  # 2026-07-18 (dataset-policy imports): 846->851
            ("_DEFAULT_BULLISH_QUALITY_CFG",),
        ),
        # WP-H (PR #2612): lines shifted 184/192/200 -> 186/194/202 by the
        # ``import math``/``import threading`` + VIX overlay helper block added
        # above the lazy provider getters in smc_api.py.
        # 2026-06-19 (timeframe expansion): added 10m/30m map entries,
        # shifting provider-global sites 186/194/202 -> 192/200/208.
        # 2026-07-11 (truth-audit T1): _candle_ts docstring + robust
        # fromisoformat parsing added +14 lines, 192/200/208 -> 206/214/222.
        # 2026-07-13 (_SWEEP_SIDE_MAP pool-side doc-fix, +12 lines above): 206->218, 214->226, 222->234
        ("smc_tv_bridge/smc_api.py", 218, ("_candle_provider",)),
        ("smc_tv_bridge/smc_api.py", 226, ("_regime_provider",)),
        ("smc_tv_bridge/smc_api.py", 234, ("_tech_provider",)),
        (
            "streamlit_terminal.py",
            589,  # 2026-07-21 (TV chart links imports): 587->589
            ("btc_available", "databento_available", "ensure_rt_engine_running", "newsapi_available"),
        ),
        # F-V8-perf-3.5 (2026-05-19): opt-in cache probe log for the sharded
        # producer. The singleton stays disabled (`None`) until the workflow
        # sets DATABENTO_CACHE_PROBE_LOG and the producer explicitly enables it.
        # F-002 (PR #2295): extracted enable/reset helpers; the original
        # 5601-site relocated to enable_cache_probe_log()/reset_cache_probe_log().
        ("databento_volatility_screener.py", 94, ("_CACHE_PROBE_LOG",)),  # 2026-07-12 (re-export import): 87->94
        ("databento_volatility_screener.py", 101, ("_CACHE_PROBE_LOG",)),  # 2026-07-12 (re-export import): 94->101
        ("terminal_bitcoin.py", 81, ("_client",)),  # 2026-07-20: retire unused technical-adapter state
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
            624,  # 2026-07-12: +5 by the 429 rate-limit telemetry insert above
            (
                "_consecutive_429_count",
                "_rate_limit_backoff_until",
                "_social_sentiment_blocked",
            ),
        ),
        ("terminal_spike_scanner.py", 97, ("_YF_UNIVERSE_CACHE",)),
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
        # 2026-07-08 (fix/cache-eviction-log-flood): throttled eviction-log state
        # (_EvictSummary class + summary block in _evict_n_stale_symbols_locked)
        # shifted cache.py globals 49/71/148/218 -> 70/92/185/255. The throttle
        # uses in-place attribute mutation, NOT a new `global`, so the inventory
        # count is unchanged.
        ("services/live_overlay_daemon/cache.py", 70, ("_max_symbols", "_rolling_bars_cap")),
        ("services/live_overlay_daemon/cache.py", 92, ("_last_eviction_at",)),
        ("services/live_overlay_daemon/cache.py", 185, ("_overlay_computed_at",)),
        ("services/live_overlay_daemon/cache.py", 259, ("_vix_level",)),
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
        # 2026-06-26 (feat/overlay-consume-signals-service, PR #2962):
        # producer-first signal loader + http://*.railway.internal guard shifted
        # the news/signals/credential/experiment/experiment_history anchors.
        # 2026-07-03 correctness lane: _load_news_snapshot_with_stamp() returns
        # snapshot + loaded_at atomically for the ticker index TOCTOU fix.
        # 2026-07-03 PR #3136 follow-up: cache-key metadata shifted anchors.
        # 2026-07-19 (mesh semantic-contract docs): explicit unknown event
        # fields added above the cache loaders shifted this anchor 288 -> 291.
        ("services/live_overlay_daemon/compute.py", 291, ("_news_cache", "_news_checked_at", "_news_loaded_at")),
        # 2026-07-03 (audit P3 HIGH): ticker->scores news index cache built once
        # per snapshot load; new module-global pair.
        # 2026-07-03 PR #3136 follow-up: _news_index_cache_key prevents stale
        # index reuse when tests monkeypatch the public news loader directly.
        # 2026-07-05 (live-overlay parser fixes): _history_sort_key plus
        # URL-parsing helpers shifted this anchor to 829.
        # 2026-07-06 (bug-hunt B1/B2): _has_captured_at helper + expanded
        # _parse_history_lines shifted this anchor to 853.
        # 2026-07-19 (mesh semantic-contract docs): explicit unknown event
        # fields added above the cache loaders shifted this anchor 857 -> 860.
        ("services/live_overlay_daemon/compute.py", 860, ("_news_index", "_news_index_built_at", "_news_index_cache_key")),
        # 2026-06-23 (feat/grafana-trading-signals): realtime trading-signals
        # snapshot loader mirrors the news snapshot caching pattern.
        # 2026-06-26 (PR #2962): shifted by producer client code.
        # 2026-07-19 (mesh semantic-contract docs): explicit unknown event
        # fields added above the cache loaders shifted this anchor 473 -> 476.
        ("services/live_overlay_daemon/compute.py", 476, ("_signals_cache", "_signals_checked_at", "_signals_loaded_at")),
        # 2026-06-23 (feat/grafana-tv-credential-age): credential-health report
        # loader mirrors the same snapshot caching pattern.
        # 2026-06-26 (PR #2962): shifted by producer client code.
        # 2026-07-19 (mesh semantic-contract docs): explicit unknown event
        # fields added above the cache loaders shifted this anchor 560 -> 563.
        ("services/live_overlay_daemon/compute.py", 563, ("_tradingview_credential_cache", "_tradingview_credential_checked_at", "_tradingview_credential_loaded_at")),
        # 2026-06-23 (feat/grafana-experiment-timeline): daily experiment rollup
        # + per-day history loaders mirror the same snapshot caching pattern.
        # 2026-06-24 (feat/live-overlay-credential-health): +5 lines for
        # _load_credential_health_snapshot alias shifted globals to 520/568.
        # 2026-06-26 (PR #2962): shifted by producer client code.
        # 2026-07-05 (live-overlay parser fixes): _history_sort_key plus
        # URL-parsing helpers shifted these anchors to 692/740.
        # 2026-07-06 (bug-hunt B1/B2): _has_captured_at helper + expanded
        # _parse_history_lines shifted these anchors to 716/764.
        # 2026-07-19 (mesh semantic-contract docs): explicit unknown event
        # fields added above the cache loaders shifted these anchors 720/768
        # -> 723/771.
        ("services/live_overlay_daemon/compute.py", 723, ("_experiment_cache", "_experiment_checked_at", "_experiment_loaded_at")),
        ("services/live_overlay_daemon/compute.py", 771, ("_experiment_history_cache", "_experiment_history_checked_at", "_experiment_history_loaded_at")),
        # 2026-06-21 (provider/bridge + queue backpressure follow-ups):
        # feed.py gained additional helper/config blocks, shifting global
        # statements to 362/420/496.
        # 2026-06-22 follow-ups shifted these anchors to 365/423/512.
        # Post-merge sync with main shifted these anchors to 374/432/521.
        # WP1 supervisor self-heal (active-client tracking + supervisor block)
        # shifted these anchors to 398/549/651.
        # 2026-07-03 correctness lane: _feed_connected_at tracks connected-but-
        # never-first-bar stalls; reset_lifecycle_for_restart shifted start/stop.
        # 2026-07-12 (VIX wire via FMP): dead bar-based _maybe_cache_vix replaced
        # by the larger _poll_vix_from_fmp helper (+20 lines) shifted these anchors
        # 209->229, 402->421, 566->586, 665->685 (no new global; loader in _runtime).
        # 2026-07-15 (fix/feed-ready-race): _feed_ready arming moved out of the
        # ingest loop into the feed loop (F2.1). The +3-line arming block in the
        # feed loop shifted every anchor below it: 421->427 (the ingest-side
        # swap was net-zero), 586->589, 685->688. 229 is above the edit.
        ("services/live_overlay_daemon/feed.py", 231, ("_feed_connected_at",)),
        ("services/live_overlay_daemon/feed.py", 483, ("_last_bar_at",)),
        ("services/live_overlay_daemon/feed.py", 646, ("_feed_thread", "_flow_refresh_thread", "_refresh_thread")),
        ("services/live_overlay_daemon/feed.py", 745, ("_feed_thread", "_flow_refresh_thread", "_refresh_thread")),
        # 2026-06-21: optional external bridge snapshot caches are guarded by
        # module locks and cached via module-level singleton snapshots.
        # 2026-06-23: workflow bridge hardening (status/conclusion semantics,
        # owner/repo encoding and pagination note) shifted this global anchor.
        # 2026-06-28 monitoring follow-up: lines shifted by one because of last_success_fetched_at_unix setdefault.
        # 2026-06-30 bridge contract duration family shifted these anchors by one.
        ("services/live_overlay_daemon/github_workflow_bridge.py", 251, ("_cached_at_monotonic", "_cached_snapshot")),
        ("services/live_overlay_daemon/uptimerobot_bridge.py", 142, ("_cached_at_monotonic", "_cached_snapshot")),
        # 2026-07-06 (feat/evidence-freshness-monitoring): evidence bridge mirrors
        # the github_workflow_bridge snapshot-cache singleton (same TTL pattern).
        # 2026-07-09 (fix/c8-deploy-robust): submit_failed + submitter fields in
        # _empty/_coerce shifted this global anchor +8: 188->196.
        ("services/live_overlay_daemon/evidence_freshness_bridge.py", 203, ("_cached", "_cached_at_monotonic")),  # 2026-07-16 (last-good cache docstring): 198->203
        # 2026-07-11 (feat/sweep-trap-shadow-grafana): WS4a sweep-trap shadow
        # snapshot bridge — same TTL-cache singleton pattern (snapshot() +
        # _reset_cache_for_tests()).
        ("services/live_overlay_daemon/sweep_trap_shadow_bridge.py", 153, ("_cached", "_cached_at_monotonic")),  # 2026-07-16 (last-good cache docstring): 142->146; (ruff format): 146->153
        ("services/live_overlay_daemon/sweep_trap_shadow_bridge.py", 167, ("_cached", "_cached_at_monotonic")),  # 2026-07-16 (last-good cache docstring): 155->160; (ruff format): 160->167
        ("services/live_overlay_daemon/provider_usage_bridge.py", 136, ("_cached", "_cached_at_monotonic")),  # 2026-07-13 (snapshot age-recompute docstring +6): 130->136
        # 2026-07-13 (feat/pine-library-version-monitor, #3599/#3603 follow-up):
        # repo↔TradingView Pine-library version snapshot bridge — same TTL-cache
        # singleton pattern (snapshot() + _cached/_cached_at_monotonic).
        ("services/live_overlay_daemon/pine_library_version_bridge.py", 180, ("_cached", "_cached_at_monotonic")),  # 2026-07-21 (library ASOF_DATE fields): 176->180
        # 2026-06-24 (feat/railway-metrics): Railway GraphQL bridge for container
        # metrics exposes a lazily-refreshed TTL cache (mirroring uptimerobot).
        # 2026-06-25 (fix/live-overlay-bridge-contract-followup): added
        # _failed_snapshot helper shifted snapshot() and reset_cache() globals.
        # 2026-06-28 (fix/live-overlay-monitoring-followup): added
        # last_success_fetched_at_unix tracking shifted snapshot() and
        # reset_cache() globals by three lines.
        # 2026-06-30 bridge contract duration family shifted reset_cache().
        # 2026-06-30 Railway metrics error-classification cleanup moved helper
        # code below reset_cache(), shifting only the reset_cache() anchor.
        # 2026-07-07 non-finite guard in _latest_value (+ import math) shifted
        # snapshot() and reset_cache() globals by seven lines (229->236, 267->274).
        # 2026-07-07 determinism + last-success rationale comments in _latest_value
        # / _failed_snapshot shifted both globals by four more (236->240, 274->278).
        # 2026-07-07 str(id) sort-key rationale comment in _build_services shifted
        # both globals by three more (240->243, 278->281).
        ("services/live_overlay_daemon/railway_metrics.py", 245, ("_CACHE", "_CACHE_EXPIRES_AT")),  # +2 (2026-07-09): snapshot() docstring truth-fix
        ("services/live_overlay_daemon/railway_metrics.py", 290, ("_CACHE", "_CACHE_EXPIRES_AT")),  # 2026-07-22 failure-backoff cache write shifted site: 283->290
        # 2026-06-19 (fix/live-overlay-post-merge-bugs): added non-finite JSON
        # sanitization helper and related imports, shifting _startup_ts line.
        # 2026-06-19 (Copilot follow-up): _VALID_TFS contract alignment shifted
        # surrounding code; 2026-06-20 (liveness/readiness split +
        # basic-auth endpoint updates) shifted _startup_ts to line 71.
        # 2026-06-21 (auth decode hardening): binascii import shifted
        # _startup_ts to line 72.
        # WP2 epoch clock added `global _startup_ts, _startup_epoch` (line 73).
        # 2026-07-22 (stale-flag data-freshness docstring): 73->74
        ("services/live_overlay_daemon/main.py", 74, ("_startup_epoch", "_startup_ts")),
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

# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed (2026-03-02)

- **Streamlit Cloud inotify crash:** Added `fileWatcherType = "none"` to `.streamlit/config.toml` to prevent `OSError: [Errno 24] inotify instance limit reached` on shared Linux hosts. Streamlit's default `watchdog`-based file watcher exhausted the low inotify limit, cascading to EMFILE errors on all network connections (Benzinga, FMP).
- **EMFILE resilience in `load_jsonl_feed`:** Catch `OSError` during JSONL file read so the app degrades gracefully (returns partial data) instead of crashing if file descriptors are exhausted.

### Changed (2026-03-02)

- **Documentation refresh (README):**
  - Updated tab count from 17 → 18 (AI Insights tab added).
  - Updated module count from 14 → 16 (added `terminal_ai_insights.py` and `terminal_tabs/`).
  - Rewrote Tabs Overview table with current tab order (AI Insights #2, Bitcoin #5, Outlook replaces Tomorrow Outlook).
  - Updated architecture diagram with `terminal_ai_insights` and `terminal_tabs/` directory.
  - Updated test count 1 674 → 1 681.
  - Updated Streamlit config section with `fileWatcherType = "none"` and local override instructions.
  - Updated project structure tree with `terminal_ai_insights.py` and `terminal_tabs/` directory.

### Changed (2026-03-01)

- **Documentation refresh (README):**
  - Added a dedicated **Live Feed Score Badge Semantics** section describing sentiment-aware color mapping, thresholds (`0.80` / `0.50`), directional prefixes (`+`, `−`, `n`), and WIIM (`🔍`) marker meaning.
  - Expanded **Open-Prep Streamlit Monitor** docs with operational behavior details: minimum auto-refresh floor, rate-limit cooldown handling, cache-vs-live fetch strategy, stale-cache auto-recovery, stage-progress status panel, UTC/Berlin timestamp display, and extended-hours Benzinga quote overlay behavior.
  - Added **Open-Prep Realtime Engine operations quickstart** (start/verify/restart) and clarified that RT engine is a separate long-running process from Streamlit.
- **Ops runbook refresh (`docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`):**
  - Updated document date to `01.03.2026`.
  - Added copy/paste sections for RT engine **Start / Verify / Restart** including process and artifact freshness checks.

### Changed (2026-02-28)

- **README.md rewritten:** Comprehensive GitHub-ready documentation covering Streamlit News Terminal (17-tab architecture, module map, data sources, configuration, background poller, notifications, export), Open-Prep Pipeline (Streamlit monitor, macro explainability), Pine Script (Outlook/Forecast, signal modes, key features), and Developer Guide (tests, linting, project structure, documentation index).

### Removed (2026-02-28)

- **Dead code removal (~680 lines across 6 files):**
  - `terminal_poller.py`: Removed 21 unused fetch functions — `fetch_treasury_rates`, `fetch_house_trading`, `fetch_congress_trading`, 15× `fetch_finnhub_*` (insider sentiment, peers, market status, FDA calendar, lobbying, USA spending, patents, social sentiment, pattern recognition, support/resistance, aggregate indicators, supply chain, earnings quality, news sentiment, ESG), 3× `fetch_alpaca_*` (news, most active, top movers). File reduced from ~1 865 to ~1 329 lines.
  - `terminal_newsapi.py`: Removed `concept_type_icon` (unused icon mapper) and `fetch_market_articles` (unreferenced ad-hoc article query wrapper).
  - `newsstack_fmp/scoring.py`: Removed `headline_jaccard`, `_headline_tokens`, `_TOKEN_RX`, `_STOP_WORDS` (unused Jaccard-similarity helpers).
  - `open_prep/realtime_signals.py`: Removed `get_a0_signals` and `get_a1_signals` (unused filter methods).
  - `open_prep/streamlit_monitor.py`: Removed `_cached_ind_perf_op`, `_cached_bz_profile_op`, `_cached_bz_detail_op` (uncalled cached wrappers) and their dead imports (`_fetch_ind_perf`, `_fetch_bz_profile`, `_fetch_bz_detail`).
  - `newsstack_fmp/ingest_benzinga_financial.py`: Removed `_extract_dict` (unused extraction method).

### Fixed (2026-02-28)

- **Race condition** in `terminal_notifications.py`: `_last_notified` dict now protected by `threading.Lock()` to prevent concurrent access from background poller and main Streamlit thread.
- **API key leak** in `terminal_bitcoin.py` and `terminal_newsapi.py`: `httpx` exception strings containing full URLs with `apikey=` parameters are now sanitized via `_APIKEY_RE` regex before logging.
- **Silent exception swallowers** in `streamlit_terminal.py`: Added `logger.warning()` to 3 bare `except` handlers (alert rules JSON load, extended-hours quotes, BG extended-hours quotes).
- **SSRF vulnerability** in `streamlit_terminal.py`: Webhook URL input now validated with `_is_safe_webhook_url()` — blocks private IP ranges (127.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x, localhost, 0.0.0.0) and requires http/https scheme.
- **State desync** in `streamlit_terminal.py`: Feed lifecycle cursor reset now propagates to background poller session state, preventing cursor drift after auto-recovery.
- **Unbounded memory** in `terminal_spike_detector.py`: Stale symbols in `_price_buf` and `_last_spike_ts` are now pruned every 100 polls when newest snapshot exceeds `max_event_age_s`.
- **Narrow exception** in `newsstack_fmp/ingest_benzinga.py`: WebSocket JSON parse now catches `(json.JSONDecodeError, ValueError)` instead of bare `Exception`.
- **Pre-existing test failure** in `tests/test_production_gatekeeper.py`: `test_valid_quote_produces_signal` now patches `_is_within_market_hours` and `_expected_cumulative_volume_fraction` to pass regardless of time-of-day.

### Added (2026-02-28)

- **Finnhub + Alpaca Multi-Provider Integration (Phase 1–3):**
  - **`FinnhubClient`** in `open_prep/macro.py` — 15 methods across 3 tiers:
    - Phase 1 FREE (8 endpoints): `get_insider_sentiment` (MSPR score), `get_peers`, `get_market_status`, `get_market_holiday`, `get_fda_calendar`, `get_lobbying`, `get_usa_spending`, `get_patents`
    - Phase 2 PREMIUM (8 endpoints): `get_social_sentiment` (Reddit+Twitter), `get_pattern_recognition`, `get_support_resistance`, `get_aggregate_indicators`, `get_supply_chain`, `get_earnings_quality`, `get_news_sentiment`, `get_esg`
    - Auth via `FINNHUB_API_KEY` env var, 30 req/s free tier
  - **`AlpacaClient`** in `open_prep/macro.py` — 4 methods:
    - `get_news` (real-time news with sentiment), `get_most_active` (screener), `get_top_movers` (gainers/losers), `get_option_chain`
    - Auth via `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` headers

- **Pipeline expansion (`open_prep/run_open_prep.py`):**
  - `TOTAL_STAGES` 15 → 17 (2 new Finnhub stages)
  - Stage 12: Finnhub Insider Sentiment + Company Peers + FDA Calendar
  - Stage 13: Finnhub Social Sentiment + Pattern Recognition (PREMIUM)
  - 4 new pipeline helpers: `_fetch_finnhub_insider_sentiment`, `_fetch_finnhub_peers`, `_fetch_finnhub_social_sentiment`, `_fetch_finnhub_patterns`
  - Enriched quotes with: `fh_mspr_avg`, `fh_insider_sentiment_emoji`, `fh_peers`, `fh_social_score`, `fh_social_mentions`, `fh_pattern_label`, `fh_tech_signal`, `fh_support_levels`, `fh_resistance_levels`

- **Streamlit dashboard (`streamlit_terminal.py`) — 5 new tabs (16 → 21 total):**
  - 🧠 Insider Sentiment — Finnhub MSPR scores with color-coded emojis + company peers
  - 📡 Social Sentiment — Reddit/Twitter mention counts and sentiment scores
  - 📐 Patterns & S/R — Chart pattern recognition + support/resistance levels + composite tech signals
  - 💊 FDA Calendar — Upcoming FDA advisory committee meetings
  - 🗞️ Alpaca News — Real-time news feed + Most Active screener + Top Movers (sub-tabs)
  - 14 new `@st.cache_data` cached functions (11 Finnhub + 3 Alpaca)

- **Fetch functions (`terminal_poller.py`) — 18 new functions:**
  - 7 Finnhub FREE: `fetch_finnhub_insider_sentiment`, `fetch_finnhub_peers`, `fetch_finnhub_market_status`, `fetch_finnhub_fda_calendar`, `fetch_finnhub_lobbying`, `fetch_finnhub_usa_spending`, `fetch_finnhub_patents`
  - 8 Finnhub PREMIUM: `fetch_finnhub_social_sentiment`, `fetch_finnhub_pattern_recognition`, `fetch_finnhub_support_resistance`, `fetch_finnhub_aggregate_indicators`, `fetch_finnhub_supply_chain`, `fetch_finnhub_earnings_quality`, `fetch_finnhub_news_sentiment`, `fetch_finnhub_esg`
  - 3 Alpaca: `fetch_alpaca_news`, `fetch_alpaca_most_active`, `fetch_alpaca_top_movers`

- **VisiData export (`terminal_export.py`) — 6 new columns:**
  - `insider_mspr` (MSPR avg score), `insider_sent` (emoji), `social_score` (composite), `social_emoji`, `pattern` (detected chart pattern), `tech_signal` (composite buy/sell/neutral)

- **Provider comparison report (`docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`):**
  - Comprehensive German-language analysis of Finnhub, Twelve Data, and Alpaca APIs
  - Gap analysis against existing FMP + Benzinga coverage
  - Integration roadmap with effort estimates

### Fixed (2026-02-28)

- **Markdown lint (MD060)** in `docs/FMP_ENDPOINT_GAP_ANALYSE.md`: Fixed all table separator spacing
- **Markdown lint (MD060 + MD051)** in `docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`: Fixed table separators and link fragment anchors

### Added (2026-02-27)

- **Auto-recovery mechanism (data freshness self-healing):**
  - **Terminal (`streamlit_terminal.py` + `terminal_feed_lifecycle.py`):** When news feed is >30 min stale during market hours (04:00–20:00 ET), automatically resets API cursor + prunes SQLite dedup to force a fresh poll. 5 min cooldown between attempts. Manual "Reset Cursor" sidebar button as escape hatch. Sidebar shows feed age, cursor age, empty poll count.
  - **Open Prep Streamlit (`open_prep/streamlit_monitor.py`):** When cached pipeline data is >5 min old during market hours, automatically invalidates cache and forces a fresh pipeline run (~68s). 5 min cooldown between attempts. Sidebar shows recovery counter. `_STALE_CACHE_MAX_AGE_MIN = 5`.
  - **VisiData signals (`scripts/vd_signals_live.sh`):** When signal file is >5 min old and engine process is not running, auto-starts `open_prep.realtime_signals` in the background.
  - **VisiData open-prep watch mode (`scripts/vd_open_prep.sh`):** Tracks consecutive pipeline failures; after 3 failures, re-sources `.env` (catches rotated keys) and waits 60s before retrying.
  - **Background poller (`terminal_background_poller.py`):** Same hardened prune + cursor reset pattern as terminal — each prune call independent, cursor reset always executes even if prune fails.

- **Staleness thresholds (all surfaces):**

  | Surface | What is checked | Threshold | Action |
  | --- | --- | --- | --- |
  | Terminal feed | Newest article age | 5 min | Cursor reset + dedup prune |
  | Open Prep cache | Pipeline cache age | 5 min | Cache invalidate + fresh pipeline |
  | RT signals (Streamlit) | Signal file mtime | 5 min | Orange warning banner |
  | VD signals launcher | Signal file mtime | 5 min | Auto-start engine |
  | VD open-prep launcher | JSON file mtime | 5 min | Console warning |
  | Sector performance cache | `@st.cache_data` TTL | 60s (was 300s) | Auto-evict |

- **Hardened failure handling (auto-recovery never crashes):**
  - Each `prune_seen` / `prune_clusters` call has its own try/except — one failing doesn't block the other.
  - Cursor reset moved outside try blocks — the primary recovery action always executes even when SQLite prune fails.
  - `manage()` call site wrapped in try/except — lifecycle errors can never crash the Streamlit page.
  - Individual prune error logging (`prune(seen)` vs `prune(clusters)`) for debugging.

- **Benzinga delayed-quote overlay (extended-hours freshness):**
  - Integrated `fetch_benzinga_delayed_quotes()` into terminal spike scanner, VisiData snapshot, open_prep Streamlit monitor, and all stale FMP price displays.
  - During pre-market/after-hours, `bz_price`/`bz_chg_pct` columns overlay fresher Benzinga quotes on top of stale FMP close data.
  - Market-session aware: `market_session()` in `terminal_spike_scanner.py` detects pre-market, regular, after-hours, and closed states.
  - `SESSION_ICONS` extracted as canonical dict in `terminal_spike_scanner.py`, imported by both Streamlit apps.
  - Rankings tab in `streamlit_terminal.py` accepts `bz_quotes` param with RT > BZ > None price source priority.

- **Benzinga calendar, movers & quotes adapters:**
  - `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py` with typed fetchers (ratings, earnings, economics, conference calls).
  - `fetch_benzinga_movers()` and `fetch_benzinga_delayed_quotes()` via REST endpoints.
  - WIIM article boost in `_classify_item()` for "Why Is It Moving" actionability.
  - 79 tests in `tests/test_benzinga_calendar.py`.

- **Benzinga full API coverage (news + calendar + financial endpoints):**
  - **News endpoints (3 new):** `fetch_benzinga_top_news()` (curated top stories), `fetch_benzinga_channels()` (available channel list), `fetch_benzinga_quantified_news()` (sentiment-scored articles with entity scores) — all added to `newsstack_fmp/ingest_benzinga.py`.
  - **Calendar endpoints (5 new):** `fetch_dividends()`, `fetch_splits()`, `fetch_ipos()`, `fetch_guidance()`, `fetch_retail()` — all added to `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py`.
  - **Financial Data adapter (20+ methods, new file):** `BenzingaFinancialAdapter` in `newsstack_fmp/ingest_benzinga_financial.py` covering fundamentals, financials, valuation ratios, company profiles, price history, charts, auto-complete, security/instruments lookup, logos, ticker detail, options activity. Eight standalone wrapper functions exported.
  - **Channels & topics filtering:** `channels` and `topics` query parameters wired into REST adapter, WebSocket adapter, `Config`, and `terminal_poller.py`. New env var `TERMINAL_TOPICS`.
  - 103 new tests across 4 files: `test_benzinga_news_endpoints.py` (18), `test_benzinga_financial.py` (44), `test_benzinga_calendar_extended.py` (17), `test_vd_bz_enrichment.py` (24).

- **Benzinga Intelligence — Streamlit Terminal (expanded):**
  - Expanded Benzinga Intel tab from 3 to 11 sub-tabs: Ratings, Earnings, Economics, **Dividends**, **Splits**, **IPOs**, **Guidance**, **Retail**, **Top News**, **Quantified News**, **Options Flow**.
  - All new sub-tabs use `@st.cache_data(ttl=120)` wrappers and graceful error handling.

- **Benzinga Intelligence — Open Prep Streamlit:**
  - New "📊 Benzinga Intelligence" section in `open_prep/streamlit_monitor.py` with 8 tabs: Dividends, Splits, IPOs, Guidance, Retail Sentiment, Top News, Quantified News, Options Flow.
  - 10 cached wrapper functions with `@st.cache_data(ttl=120)` TTLs.
  - All imports guarded by `try/except ImportError` for Streamlit Cloud compatibility.

- **VisiData Benzinga enrichment:**
  - `build_vd_snapshot()` and `save_vd_snapshot()` accept `bz_dividends`, `bz_guidance`, `bz_options` parameters.
  - Per-ticker enrichment columns: `div_exdate`, `div_yield` (from dividends), `guid_eps` (from guidance), `options_flow` (from options activity).
  - New `build_vd_bz_calendar()` and `save_vd_bz_calendar()` functions produce a standalone Benzinga Calendar JSONL file with dividends, splits, IPOs, and guidance events.
  - Default export path: `artifacts/vd_bz_calendar.jsonl`.

- **Terminal UI improvements:**
  - Data table headlines are now clickable links to source articles (`LinkColumn`).
  - Ring-buffer eviction replaces queue drop-on-full (maxsize 100 → 500).
  - Optional import guard for `ingest_benzinga_calendar` on Streamlit Cloud.

### Fixed (2026-02-27)

- **Production readiness hardening (3 review cycles, 12 bugs fixed):**
  - **Review #1:** P0 falsy `or` in dict lookup, P1 `bq.get("last", 0)` default, P1 unconditional API calls in non-extended sessions, P2 inner import, P2 source concatenation, P2 duplicate dicts.
  - **Review #2:** P1 cache key thrashing from non-deterministic set iteration → `sorted()`, P2 6× `market_session()` per render → consolidated to single `_current_session`, P1 `_get_bz_quotes_for_symbols` in open_prep had no caching → added `@st.cache_data(ttl=60)` wrapper, P2 unused `timezone` import.
  - **Review #3:** P2 spike symbols not sorted before `join()` for cache key, P2 BZ overlay ran after `_reorder_ranked_columns` so bz columns appeared at tail.
  - **Refactoring:** DRY `SESSION_ICONS` extraction, symbol extraction `g.get("symbol") or g.get("ticker", "")` pattern, loop var rename `l` → `loser`.

- **Pylance/Pyright lint cleanup (0 workspace errors):**
  - Wrapped `json.load`, `getattr`, `round/max/min`, `st.session_state` returns with explicit casts (`float()`, `str()`, `list()`, `# type: ignore[no-any-return]`).
  - Added `# type: ignore[assignment]` for optional import `None` sentinel assignments.
  - Renamed loop var `q` → `quote` in `terminal_spike_scanner.py` to avoid type-narrowing shadow.
  - Imported `ClassifiedItem` at module level + `dict[str, Any]` annotation on defaults in tests.
  - Fixed `Generator` return type for yield fixtures in `tests/test_benzinga_calendar.py`.
  - Used `callable()` check instead of truthiness for `_market_session` function.

### Verification (2026-02-28)

- Full regression suite: **1 674 passed, 34 subtests passed, 0 failures**.
- Pylance/Pyright: **0 workspace errors**.
- Dead code removed: **~680 lines across 6 files** (31 functions).

### Verification (2026-02-27)

- Full regression suite: **1599 passed, 34 subtests passed**.
- Pylance/Pyright: **0 workspace errors** (only external `~/.visidatarc` stub, suppressed).
- Lint (`ruff`): clean.

### Added (2026-02-26)

- **Python quality/documentation baseline (repo-level):**
  - Added centralized `pyproject.toml` configuration for `pytest`, `ruff`, `mypy`, and coverage reporting.
  - Added focused coverage expansion in `tests/test_coverage_gaps.py` for Python runtime modules (`terminal_poller`, `terminal_export`, `newsstack_fmp` adapters/pipeline/store).
  - Improved top-level README developer guidance for reproducible quality checks.

- **VWAP Reclaim expansion (Long/Short/Both):**
  - Added new bidirectional scripts:
    - `VWAP_Reclaim_Indicator.pine`
    - `VWAP_Reclaim_Strategy.pine`
  - Added `Trade Direction` toggle (`Long` / `Short` / `Both`) with mirrored short state machine (`Reclaim → Retest → Go`) and dedicated short entry/exit labeling.
  - Added short-side trend gating parity (`matchedTrendsFilter_short`) and USI bear-stack gate parity in bidirectional variants.

- **Signal filter controls (all VWAP reclaim variants):**
  - Added grouped `🔒 Signal Filters` controls:
    - `Bar Close Only`
    - `Volume Filter`
    - `Min Volume Ratio`
    - `Volume SMA Length`
  - Integrated `barCloseGate` + `volGate` into signal generation and visualization flow.

- **Bloomberg-style terminal integration (workspace):**
  - Added terminal pipeline/runtime modules:
    - `terminal_poller.py`
    - `terminal_export.py`
    - `streamlit_terminal.py`
  - Added coverage in `tests/test_terminal.py` and planning doc `docs/BLOOMBERG_TERMINAL_PLAN.md`.

### Fixed (2026-02-26)

- **VWAP reclaim reliability hardening (indicator/strategy parity):**
  - ATR bootstrap safety: `atr = nz(ta.atr(14), syminfo.mintick * 10)` to avoid early-bar `na` tolerance propagation.
  - Anchor reset hardening: reclaim/position state now resets fully on `isNewPeriod` (including reclaim bar markers), preventing stale sequence carry-over.
  - Strategy reset parity: bidirectional strategy closes all active exposure with unified `strategy.position_size != 0` guard on period reset.
  - Bidirectional strategy concurrency: `pyramiding=2` to allow intended simultaneous long+short behavior in `Both` mode.
  - Long-stop safety: `nz(retestLow, vwapValue)` guard prevents `na` stop propagation in long-only strategy.
  - Debug marker stability: reclaim/retest debug markers now respect `barCloseGate`.
  - UX semantics: long-only USI status now uses `FLAT` (gray) instead of `BEAR` when no bull stack is present.

### Verification (2026-02-26)

- Full regression suite (local): **1028 passed, 34 subtests passed**.

### Verification (2026-02-26, later run)

- Full regression suite (local): **1116 passed, 34 subtests passed**.
- Linting (`ruff`): **All checks passed**.
- Type-checking (`mypy`): **Success, no issues found**.
- Core Python coverage (`newsstack_fmp`, `terminal_poller`, `terminal_export`): **83%**.

### Added (2026-02-25)

- **Open-Prep Streamlit v2: auto-promotion for realtime A0/A1 signals:**
  - Added deterministic promotion logic in `open_prep/streamlit_monitor.py` to lift symbols from
    `filtered_out_v2` into `ranked_v2` when all of the following are true:
    - active realtime level is `A0` or `A1`,
    - symbol is **not** already ranked,
    - pipeline reason is exactly `below_top_n_cutoff`.
  - Promoted rows are flagged with `rt_promoted=true` and include realtime context
    (`rt_level`, `rt_direction`, `rt_pattern`, `rt_change_pct`, `rt_volume_ratio`).
  - Streamlit UI now renders a dedicated **🔥 RT-PROMOTED** block above the normal v2 tiers.
  - Promoted symbols are removed from `filtered_out_v2` display to avoid duplicate listing.
  - Cross-reference panel now reuses preloaded realtime A0/A1 data and excludes already-promoted symbols,
    so “missing from v2” only reflects hard-filtered or non-universe cases.

- **New unit test coverage for promotion behavior:**
  - Added `tests/test_rt_promotion.py` with coverage for:
    - below-cutoff promotion (A0/A1),
    - hard-filter exclusion,
    - no-duplication for already-ranked symbols,
    - case-insensitive symbol matching,
    - fallback semantics for promoted price fields,
    - multi-symbol and no-op edge cases.

### Verification (2026-02-25)

- Targeted suite: **13 passed** (`tests/test_rt_promotion.py`).
- Full regression suite: **985 passed, 34 subtests passed**.

### Added (2026-02-21)

- **Indicator/Strategy parity hardening finalized:**
  - Synced `EXIT` timing state in Strategy with Indicator (`enTime := time`).
  - Kept same-bar reversal/entry gate mapping aligned (`COVER→BUY`, `EXIT→SHORT`) with strict anti-same-direction guard.
  - Added/updated regression coverage to lock parity behavior in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy_pine.py`
    - `tests/test_behavioral.py`
    - `tests/pine_sim.py`

- **REV JSON alert-action parity in Strategy:**
  - Consolidated runtime `alert()` path in `SkippALGO_Strategy.pine` now maps first signal label like Indicator:
    - `BUY`/`REV-BUY` → `buy`
    - `SHORT`/`REV-SHORT` → `sell`
    - `EXIT`/`COVER` → `exit`
  - Prevents action misclassification when reversal labels are emitted.

- **Open-prep robustness and data-output refresh:**
  - Strengthened macro/news processing paths and updated report artifacts in `reports/`.

### Verification (2026-02-21)

- Pine-focused parity suites: **193 passed, 8 subtests passed**.
- Full regression suite: **551 passed, 32 subtests passed**.

### Added (2026-02-20)

- **VWT integration (Volume Weighted Trend) in Indicator + Strategy:**
  - Added configurable VWT filter inputs in both scripts:
    - `useVwtTrendFilter`
    - `vwtPreset` (`Auto`, `Default`, `Fast Response`, `Smooth Trend`, `Custom`)
    - `vwtLengthInput`, `vwtAtrMultInput`
    - `vwtReversalOnly`, `vwtReversalWindowBars`
    - `showVwtTrendBackground`, `vwtBgTransparency`
  - Added effective Auto mapping (`vwtPresetEff`, `vwtReversalWindowEff`) based on `entryPreset`.
  - Added VWT runtime state and entry guards:
    - `vwtTrendDirection`, `vwtTurnedBull/Bear`, `vwtBullRecent/BearRecent`
    - `vwtLongEntryOk` / `vwtShortEntryOk`
  - Wired VWT gates into all entry paths:
    - engine gates (`gateLongNow`, `gateShortNow`),
    - reversal globals (`revBuyGlobal`, `revShortGlobal`),
    - score entries (`scoreBuy`, `scoreShort`).

- **Optional VWT trend background overlay (Indicator + Strategy):**
  - Added regime-based background coloring for bullish/bearish VWT trend state.

- **New regression tests for VWT feature:**
  - `tests/test_skippalgo_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`
  - `tests/test_skippalgo_strategy_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`

### Verification (2026-02-20)

- Full test run completed locally:
  - **478 passed, 16 subtests passed, 0 failed**.

### Added

- **ChoCH fast-mode parity in Strategy (v6.3.13 line):**
  - Added Strategy-side ChoCH runtime controls to match Indicator behavior:
    - `ChoCH signal mode` (`Ping (Fast)`, `Verify (Safer)`, `Ping+Verify`),
    - `Show ChoCH Ping markers`.
  - Added Strategy ChoCH presets:
    - `ChoCH Scalp Fast preset` (forces `Wick` + `Ping (Fast)` + effective `swingR=max(swingR,1)`),
    - `ChoCH Fast+Safer preset` (forces `Wick` + `Ping+Verify` + effective `swingR=max(swingR,1)`).
  - Strategy eval HUD now appends active ChoCH runtime configuration (`preset/mode/source/R`) for on-chart verification.

- **Runtime Success-Rate HUD + Eval mode guidance (indicator + strategy):**
  - Added a lightweight last-bar chart label showing live evaluation success rate and sample count:
    - `Success rate (History+Live): xx% (N=yy)` or
    - `Success rate (LiveOnly): xx% (N=yy)`
  - Added explicit `Evaluation mode` tooltip guidance with practical examples:
    - `History+Live` shows immediate populated values from confirmed history,
    - `LiveOnly` starts at `0% (N=0)` on historical bars and grows only in realtime.

- **Configurable BUY re-entry timing after COVER (indicator + strategy):**
  - Added `allowSameBarBuyAfterCover` (default `false`) to both scripts.
  - `false` keeps legacy one-bar delay after a `COVER` before the next `BUY`.
  - `true` allows immediate same-bar `COVER → BUY` re-entry.

- **Configurable SHORT re-entry timing after EXIT (strategy):**
  - Added `allowSameBarShortAfterExit` (default `false`) to strategy.
  - `false` keeps legacy one-bar delay after an `EXIT` before the next `SHORT`.
  - `true` allows immediate same-bar `EXIT → SHORT` re-entry.

- **Same-bar reversal mapping correction (indicator + strategy):**
  - Corrected cross-directional pairing to match runtime exit semantics:
    - `BUY` same-bar control is now `COVER → BUY` (`allowSameBarBuyAfterCover`),
    - `SHORT` same-bar control is now `EXIT → SHORT` (`allowSameBarShortAfterExit`).
  - Rewired phase-2 guards accordingly (`didCover` for BUY, `didExit` for SHORT).
  - Added regression tests to lock this mapping and prevent future inversion.

- **USI Length 5 lower-bound update (indicator + strategy):**
  - `Length 5 (fastest / Red)` now supports `minval=1` (previously `2`) in both scripts.
  - This allows a more aggressive fast-line configuration for USI Quantum Pulse tuning.

- **USI Aggressive Entry Mode guidance (indicator + strategy):**
  - Compact fast-scalping preset recommendation:
    - `USI Aggressive: same-bar verify = ON`
    - `USI Aggressive: verify 1-of-3 = ON`
    - `USI Aggressive: tight-spread votes = ON` (optional)
    - `Hardened Hold (L5 > L4) = OFF`

- **Scalp Early entry behavior profile (indicator + strategy):**
  - Added `Scalp Early (v6.3.12-fast)` to `Entry behavior profile`.
  - Keeps v6.3.12 structure but biases for earlier entries via:
    - slightly lower score thresholds,
    - slightly lower directional/score probability thresholds,
    - lower ChoCH probability threshold,
    - disabled score confidence hard-gate.

- **Cooldown trigger mode `EntriesOnly` (indicator + strategy):**
  - Added new `cooldownTriggers` option `EntriesOnly` in both scripts.
  - `EntriesOnly` updates cooldown timestamps only on entry signals (`BUY`/`SHORT`).
  - In `EntriesOnly` with `cooldownBars >= 1`, exits are hold-gated by entry bar index to enforce one full bar after entry before `EXIT`/`COVER` can fire.
  - Exception update: `EXIT SL` and `COVER` bypass this hold and may fire immediately after entry.
  - Existing modes remain unchanged:
    - `ExitsOnly` updates on `EXIT`/`COVER`.
    - `AllSignals` updates on all signals.

- **Global directional probability floors (indicator + strategy):**
  - Added `Enforce score min pU/pD on all entries` (default `true`).
  - When enabled, `Score min pU (Long)` / `Score min pD (Short)` are enforced as hard floors across BUY/SHORT entry paths.
  - `REV-BUY` is exempt and keeps its dedicated reversal probability gates (`revMinProb` + reversal/open-window logic).
  - Added `Global floor: bypass in open window` (default `true`) to optionally preserve open-window entry behavior.

- **Dedicated REV alert conditions (indicator + strategy):**
  - Added standalone `REV-BUY` and `REV-SHORT` alert conditions.
  - Consolidated runtime alert text now prioritizes `REV-BUY`/`REV-SHORT` labels over generic `BUY`/`SHORT` when reversal entries fire.

- **Dedicated consolidation alert condition (indicator + strategy):**
  - Added standalone `CONSOLIDATION` alert condition.
  - Trigger is phase-entry based (`sidewaysVisual and not sidewaysVisual[1]`) to avoid repeated alerts on every consolidation bar.

- **Sideways visual hysteresis parity (strategy):**
  - Strategy now uses the same visual consolidation hysteresis model as indicator (`sideEnter`/`sideExit` + latched `sidewaysVisual`).
  - This aligns consolidation alert timing semantics across both scripts without changing engine-side entry gating.

- **Consolidation dot color refinement (indicator):**
  - Consolidation dots are now **reddish** when USI is short (`usiStackDir == -1`).
  - All other consolidation states remain **orange**.

- **Directional consolidation entry veto (indicator + strategy):**
  - `BUY` is blocked during bearish/reddish consolidation.
  - `SHORT` is blocked during bullish/orange consolidation.
  - Veto applies to entries only; exits keep normal behavior.

- **Directional consolidation entry veto removed (indicator + strategy):**
  - Consolidation dot color/state is now informational only.
  - `BUY`/`SHORT` are no longer directly blocked by bearish/bullish consolidation dot state.

- **Intrabar alerts/labels default enabled (indicator + strategy):**
  - `Alerts: bar close only` now defaults to `false`.
  - Runtime alert/label flow is intrabar-first by default for BUY/SHORT/EXIT/COVER and PRE-BUY/PRE-SHORT.
  - Close-confirmed-only behavior remains available by setting `Alerts: bar close only = true`.

- **v6.3.13 parity hardening (indicator + strategy):**
  - restored strict entry gating parity in Strategy (`reliabilityOk`, `evidenceOk`, `evalOk`, `abstainGate/decisionFinal`) while preserving session filtering,
  - added full Strategy-side dynamic TP/SL runtime profile support:
    - Dynamic TP expansion (`useDynamicTpExpansion`, `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`, trend/conf gates),
    - Dynamic SL profile (`useDynamicSlProfile`, widen/tighten phases, trend/conf gates),
    - preset-driven effective dynamic TP mapping (`Manual/Conservative/Balanced/Runner/Super Runner`) aligned with indicator.
- **Structure tag wiring completed:**
  - Strategy now renders BOS/ChoCH structure tags (not only entry/exit labels),
  - Indicator now renders BOS tags alongside existing ChoCH tags.
- **ChoCH volume requirement wired:**
  - `chochReqVol` now actively gates ChoCH-triggered entries in both scripts.

### Verification

- Targeted strict-related suites (local, 2026-02-16): **152 passed, 8 subtests passed**.
- Full regression suite (local, 2026-02-16): **390 passed, 16 subtests passed**.

- **Entry behavior profile toggle (legacy timing fallback):** added `entryBehaviorProfile` in indicator + strategy under **Score Engine (Option C)**:
  - `Current (v6.3.12)` keeps stricter score gating/chop veto behavior.
  - `Legacy (v6.3.9-like)` relaxes entry strictness for earlier signal timing by:
    - disabling score probability and confidence hard-gates,
    - disabling score directional-context hard requirement,
    - disabling hard chop veto in final score merge,
    - disabling Regime Classifier 2 auto-tightening,
    - slightly loosening ChoCH probability threshold.

  ### Changed

  - **Fallback activated by default:** `entryBehaviorProfile` now defaults to `Legacy (v6.3.9-like)` in both indicator and strategy for immediate v6.3.9-like signal timing behavior out of the box.

## [v6.3.13] - 2026-02-16

### Added

- Strategy parity completion for dynamic runtime risk modules:
  - Dynamic TP expansion,
  - Dynamic SL profile (widen/tighten),
  - preset-aware effective dynamic TP mapping.
- Structure visualization parity updates:
  - BOS tags now rendered in indicator,
  - BOS/ChoCH structure tags now rendered in strategy.

### Changed

- Restored strict Strategy entry gating parity with indicator:
  - reliability/evidence/eval/abstain decision checks active again in `allowEntry`.
- Wired `chochReqVol` into ChoCH-triggered entry filtering in both scripts.
- Version sync: bumped visible script versions/titles to `v6.3.13`.

### Verification

- Full regression suite: **386 passed**.

## [v6.3.12] - 2026-02-15

### Added

- **RFC v6.4 Phase-3 quality tuning (regime hysteresis):** added state-stability controls for Regime Classifier 2.0 in both scripts:
  - `regimeMinHoldBars` (minimum hold duration before non-shock regime switches)
  - `regimeShockReleaseDelta` (VOL_SHOCK release threshold hysteresis)
  - latched regime logic via `rawRegime2State`, `regime2State`, `regime2HoldBars`
  - shock persistence rule keeps `VOL_SHOCK` active until ATR percentile cools below release threshold

### Changed

- **Version sync:** bumped visible script versions to `v6.3.12` in indicator and strategy headers/titles.
- **Tests:** added Phase-3 parity lock in `tests/test_score_engine_parity.py` (`test_phase3_regime_hysteresis_parity`).
- **Tests (behavioral):** added simulator snapshot coverage for Phase-3 hysteresis edge cases in `tests/test_functional_features.py` (`TestPhase3RegimeHysteresisBehavior`):
  - regime flapping damping via `regimeMinHoldBars`
  - VOL_SHOCK sticky release via `regimeShockReleaseDelta`

### Verification

- Full regression suite passes after integration: **384 passed**.

## [v6.3.11] - 2026-02-15

### Added

- **RFC v6.4 Phase-2 opt-in wiring (default-safe):** integrated the Phase-1 scaffold into active signal controls when explicitly enabled (`useRegimeClassifier2` + `regimeAutoPreset` + detected regime):
  - new effective tuning variables `cooldownBarsEff`, `chochMinProbEff`, `abstainOverrideConfEff`
  - regime-aware mapping for TREND/RANGE/CHOP/VOL_SHOCK under `regime2TuneOn`
  - trend core activation in signal layer via `trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)` and `trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)`
  - ChoCH gating updated to effective threshold (`chochMinProbEff`) in all relevant entry paths
  - abstain override uses effective threshold (`abstainOverrideConfEff`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.11` in indicator and strategy headers/titles.
- **Tests:**
  - added Phase-2 wiring parity coverage in `tests/test_score_engine_parity.py` (`test_phase2_optin_wiring_parity`)
  - aligned trend-regime presence checks to trend-core wiring in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy.py`

### Verification

- Full regression suite passes after integration: **378 passed**.

## [v6.3.10] - 2026-02-15

### Added

- **RFC v6.4 Phase-1 scaffold (default-off):** added non-invasive foundation in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Zero-Lag Trend Core inputs (`useZeroLagTrendCore`, `trendCoreMode`, `zlTrendLenFast/Slow`, `zlTrendAggressiveness`, `zlTrendNoiseGuard`)
  - Regime Classifier 2.0 inputs (`useRegimeClassifier2`, `regimeLookback`, `regimeAtrShockPct`, `regimeAdxTrendMin`, `regimeHurstRangeMax`, `regimeChopBandMax`, `regimeAutoPreset`)
  - debug visibility toggle `showPhase1Debug` with hidden Data Window plots
  - helper functions `f_zl_trend_core` and `f_hurst_proxy`
  - derived diagnostic state variables (`trendCoreFast/Slow`, `trendCoreDiffNorm`, `regime2State`, `regime2Name`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.10` in indicator and strategy headers/titles.
- **Tests:** expanded parity/functional coverage for Phase-1 scaffold invariants:
  - `tests/test_score_engine_parity.py`
  - `tests/test_functional_features.py`
  - `tests/pine_sim.py` (Phase-1 config surface)

### Verification

- Full regression suite passes after integration: **377 passed**.

## [v6.3.9] - 2026-02-15

### Added

- **Functional behavior test matrix (new):** added simulator-driven feature coverage in `tests/test_functional_features.py` for:
  - gate functionality (`reliabilityOk`, `evidenceOk`, `evalOk`, `decisionFinal`),
  - open-window + strict-mode behavior,
  - engine scenarios (Hybrid/Breakout/Trend+Pullback/Loose),
  - risk/exit behavior,
  - reversal logic,
  - feature-flag matrix,
  - randomized invariants,
  - golden-master snapshots.
- **Label/display regression suite (new):** added `tests/test_label_display_regression.py` to lock label payload/style/color contracts and event→label family mapping (BUY/REV-BUY/SHORT/REV-SHORT/EXIT/COVER).
- **Functional test documentation:** added `docs/FUNCTIONAL_TEST_MATRIX.md` and linked it from `README.md`.

### Changed

- **CI guard hardened:** `.github/workflows/ci.yml` now includes explicit read permissions, concurrency cancel-in-progress, manual dispatch (`workflow_dispatch`), timeout guard, and strict pytest execution (`-q --maxfail=1`).
- **Version sync:** updated script headers/titles and docs references to `v6.3.9` for consistency.

### Verification

- Full regression suite passes after integration: **375 passed**.

### Changed

- **Entry presets (new):** added score presets in indicator + strategy via:
  - `entryPreset = Manual | Intraday | Swing`
  - `presetAutoCooldown` (default `false`)
  Presets now drive effective score variables (`*_Eff`) for thresholds, weights, and score probability floors.
- **Optional preset-driven cooldown:** when `presetAutoCooldown = true` and preset is not `Manual`, cooldown uses effective preset values:
  - mode: `Bars`
  - triggers: `ExitsOnly`
  - minutes: `15` (Intraday) / `45` (Swing)
  With `presetAutoCooldown = false` (default), cooldown remains fully user-input controlled.
- **Score integration mode adjusted (Option C):** restored hybrid signal merge so score can inject entries again while still respecting engine logic context.
- **Score directional context gate (new, default ON):** added `scoreRequireDirectionalContext` so score injection requires directional context:
  - BUY score injection needs bullish context (`trendUp`/USI bull state),
  - SHORT score injection needs bearish context (`trendDn`/USI bear state).
- **Dynamic TP expansion:** outward-only TP mode is active by default (default ON) in indicator + strategy:
  - `useDynamicTpExpansion`
  - `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`
  - optional gates: `dynamicTpRequireTrend`, `dynamicTpRequireConf`, `dynamicTpMinConf`
  TP expands as unrealized $R$ grows and never tightens due to this module.
- **Dynamic SL profile (new, default ON):** added adaptive stop profiling in indicator + strategy:
  - optional early widening window (`dynamicSlWidenUntilR`, `dynamicSlMaxWidenATR`) to reduce noise stopouts,
  - progressive tightening phase (`dynamicSlTightenStartR`, `dynamicSlTightenATRPerR`, `dynamicSlMaxTightenATR`) as $R$ grows,
  - optional gates: `dynamicSlRequireTrend`, `dynamicSlRequireConf`, `dynamicSlMinConf`.
  Widening is disabled once BE was hit or trailing is active.
- **Score hard confidence gate (new):** added optional hard confidence floor for score entries in indicator + strategy:
  - `scoreUseConfGate`
  - `scoreMinConfLong`, `scoreMinConfShort`
  - integrated in final score entry decisions via effective vars (`*_Eff`) for preset parity.
  - **Current defaults:** `scoreUseConfGate = true`, `scoreMinConfLong = 0.50`, `scoreMinConfShort = 0.50`.

### Fixed

- **Chop penalty enforcement:** added explicit chop veto in final score merge path:
  - `chopVeto = isChop and (wChopPenalty < 0)`
  - final merge now blocks BUY/SHORT when chop veto is active.
- **Unified exit trigger (LONG + SHORT):** exit/cover now use one OR-union trigger in both scripts:
  - `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`
  - whichever condition fires first closes the position.
- **Cooldown semantics restored:** when `cooldownTriggers` is `ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events again (indicator + strategy parity).
- **Debug transparency:** score debug panel now prints chop veto status (`veto:0/1`) next to `chop` for faster root-cause diagnosis.
- **Debug blocker clarity:** score debug now shows explicit block reason (for example `BLOCK:IN_POSITION`) and prints last-signal age safely (`LS:...@n/a` instead of `NaN` when unavailable).
- **Debug context visibility:** score debug now prints directional context gate flags:
  - `ctxL:0/1` for long score-context pass/fail,
  - `ctxS:0/1` for short score-context pass/fail.
- **Token-budget hardening (Strategy):** reduced compile-token pressure by compacting debug payloads and removing Strategy table rendering (visual-only) while keeping signal/risk/entry-exit logic intact.
- **Parity:** same logic mirrored in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

## [v6.3.8] - 2026-02-15

### Changed

- **USI Exit/Flip Touch Logic (Tier A Red vs Blue):** refined cross detection to treat visual touch/near-touch transitions as valid flip events, improving practical EXIT timing when Red approaches Blue from above.
- **USI Red De-lag Option (Option 2):** added optional Red-line source de-lag controls:
  - `useUsiZeroLagRed`
  - `usiZlAggressiveness`
  This is applied pre-RSI on Line5 for earlier flips with controllable aggressiveness.

### Fixed

- **Contra-state entries blocked (hard rule):** BUY is now vetoed when USI is bearish, and SHORT is vetoed when USI is bullish (when USI is enabled).
- **Parity hardening:** synchronized logic in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`, including gate-timeframe (`f_usi_30m_calc_raw`) handling for the new Red-line de-lag path.

### Tests

- Extended parity checks in `tests/test_score_engine_parity.py` to verify:
  - presence of new USI Red de-lag inputs,
  - Red-line implementation parity,
  - hard USI state blocking in score decisions.

## [v6.3.7] - 2026-02-14

### Added

- **Exit control flexibility:** `useStrictEmaExit` added to allow relaxed trend exits (wait for full EMA trend flip when disabled), reducing deep-pullback shakeouts.

## [v6.3.4] - 2026-02-14

### Fixed

- **SkippALGO Strategy**: Synchronized fix for `plotchar()` scope (global scope with conditional logic) to resolve "Cannot use plotchar in local scope".
- **Maintenance**: Unified versioning across Indicator (v6.3.3 based) and Strategy.

## [v6.3.3] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Moved `plotchar()` debug calls from local scope (if-block) to global scope with conditional `debugUsiPulse and ...` logic to fix "Cannot use plotchar in local scope" errors.

## [v6.3.2] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Replaced `color.cyan` with `color.aqua` to resolve an undeclared identifier error (Pine v6 standard).

## [v6.3.1] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Removed duplicate/erroneous code block related to `qVerifyBuy` logic that caused a "Mismatched input bool" syntax error.
- **Maintenance**: Parity version bump for Strategy script (no functional changes in Strategy).

## [v6.3.0] - 2026-02-14

### Added (System Hardening)

- **Time-Based Cooldown**: `cooldownMode` input ("Bars" vs "Minutes") allows proper HTF trade management without multi-hour lockouts.
- **Explicit Triggers**: `cooldownTriggers` input ("ExitsOnly" vs "AllSignals") strictly defines what resets the timer. "ExitsOnly" (default) ensures fast add-on entries are possible.

### Changed (Optimization)

- **QuickALGO Logic**: Switched from restrictive "Hard-AND" momentum check to "Score+Verify" weighted approach.
- **QuickALGO MTF Fix**: Added `lookahead=barmerge.lookahead_off` to prevent repainting.
- **Cleanup**: Removed legacy "Deep Upgrade" branding from script headers.

## [2026-02-12]

### Added (Signals & Volatility)

- New input: `REV: Min dir prob` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed (Parity)

- Stabilized script titles to preserve TradingView input settings across updates:
  - `indicator("SkippALGO", ...)`
  - `strategy("SkippALGO Strategy", ...)`
- Consolidated runtime alert dispatch to one `alert()` call per bar per symbol, reducing watchlist alert-rate pressure and TradingView throttling risk.
- EXIT/COVER label text layout split into shorter multi-line rows for better chart readability.
- Open-window directional probability (`pU`/`pD`) bypass behavior applies during configured market-open windows as implemented in current logic.

### Clarified

- `Rescue Mode: Min Probability` (`rescueMinProb`) controls only the rescue fallback path (requires volume + impulse), while `revMinProb` controls the normal REV path.

### Fixed

- Corrected Strategy-side forecast gate indentation/structure parity so open-window bypass behavior is consistently applied.

### Added

- Optional **3-candle engulfing filter** (default OFF) in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Long entries require bullish engulfing after 3 bearish candles.
  - Short entries require bearish engulfing after 3 bullish candles.
  - Optional body-dominance condition (`body > previous body`).
  - Optional engulfing bar coloring (bullish yellow / bearish white).
- Optional **ATR volatility context layer** (default OFF) in both scripts:
  - Regime overlay and label: `COMPRESSION`, `EXPANSION`, `HIGH VOL`, `EXHAUSTION`.
  - ATR ratio to configurable baseline (`SMA`/`EMA`).
  - Optional ATR percentile context (`0..100`) with configurable lookback.

### Changed

- Maintained strict **Indicator ⇄ Strategy parity** for new signal/context features to avoid behavior drift between visual and strategy paths.

---

## Notes

- This changelog tracks user-facing behavior and operational reliability updates.
- Historical items before this file was introduced may still be referenced in commit history and docs.

# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed (2026-03-20)

- **SMC++ long-dip state, alert, and profile consistency:**
  - Fixed overlapping OB/FVG long-dip sequencing so strict reclaim history, arming, and invalidation now track the actual source object instead of the merged long-zone view.
  - Fixed armed-source invalidation to compare against the active zone for the armed source kind, preventing overlap cases from silently surviving on the wrong zone.
  - Fixed long-dip watchlist alerts to be generic again: the watchlist event now triggers only when the generic watchlist becomes active, not when OB/FVG source rotation happens inside an already active watchlist.
  - Fixed priority-mode dynamic lifecycle alerts so `Long Invalidated` can still fire on the same realtime bar after a weaker lifecycle alert was already sent earlier in that bar.
  - Fixed TradingView `alertcondition(...)` lifecycle presets and OB/FVG event presets to use per-bar latched event state, reducing missed intrabar transitions for close-safe users.
  - Fixed volume-quality signaling to distinguish current-bar volume loss from rolling feed degradation, and aligned dashboard messaging with that split.
  - Fixed lower-timeframe confirmation fallback handling by separating price availability from volume availability and by tightening when strict-entry fallback is allowed historically.
  - Fixed OB profile value-area construction to expand from the POC outward and hardened profile alignment against empty or zero-volume profiles.
  - Fixed active long-zone selection to prefer the better overlap candidate instead of relying on a first-match merge.
  - Fixed pivot HH/HL/LH/LL labels, FVG hide cleanup, and symbol-token matching for microstructure/profile overrides.

### Changed (2026-03-20)

- **SMC++ dashboard and workflow documentation:**
  - Documented that the Watchlist tier is a generic context stage, while strict sequencing, backing-zone tracking, and invalidation are source-specific to the active OB or FVG.
  - Documented the new microstructure display behavior where the dashboard shows both the primary profile and active modifiers that can tighten or relax long-dip filters.
  - Documented the degraded-data model for relative volume and lower-timeframe checks so users can see when the engine is operating with price-only or fallback-safe context.

### Fixed (2026-03-19)

- **SMC++ long-dip and object lifecycle hardening:**
  - Fixed swing OB break handling so older blocks are no longer skipped just because the newest tracked block was not broken yet.
  - Fixed bullish and bearish FVG maintenance loops so older filled gaps are still updated and migrated even when newer gaps remain open.
  - Fixed `update(FVG this)` so the close-vs-live fill mode is recalculated per gap instead of leaking through a static `var`, which could silently mis-handle later FVG fills.
  - Fixed OB/FVG reclaim detection so a reclaim can complete on a later bar after the initial zone touch, as long as it stays within the configured long signal window.
  - Fixed a follow-up reclaim regression so OB/FVG reclaims fire only once on the actual crossover bar instead of staying latched true across later bars above the reclaimed zone.
  - Replaced fixed-millisecond OB/FVG projection with exact event timestamps for time-based overlays and index-based drawing for chart-timeframe OB/FVG objects, removing weekend/holiday/DST drift.
  - Wired the existing OB/FVG garbage-collection cycle through the main indicator so insignificant objects can actually be cleaned up on schedule.
  - Fixed HTF FVG retention to respect `Keep filled` history settings instead of using a hardcoded history depth of `2`.
  - Stopped HTF FVG `request.security()` calls from running while the HTF overlay is hidden.
  - Tightened long setup expiry semantics so setups now expire exactly when they reach the configured bar limit.
  - Aligned long-dip preset alerts with the multi-bar setup model by using recent-zone context instead of requiring the current bar to still overlap the pullback zone.
  - De-spammed dynamic long-dip state alerts so watchlist, armed, early, clean, and entry presets now emit only on state transitions.
  - Restored the pre-break OB cutoff semantics for index-based rendering so broken order blocks no longer extend one bar too far to the right.
  - Removed leftover dead code from earlier alert/dashboard iterations, including unused compact trend text, unused HTF state locals, unused intrabar event counting, and unused legacy FVG plotting wrappers.
  - Removed redundant per-bar OB/FVG registry rebuilds from the dashboard count path and switched those counts to direct array sizes.
  - Hardened the premium/discount warning helper to reuse a single warning label instead of creating a new one every bar.
  - Added lower-timeframe guardrails that automatically disable `request.security_lower_tf()` sampling when the chart-to-LTF ratio or estimated intrabar array size exceeds configured safety thresholds.
  - Hardened volume-data quality checks so relative volume, OB profiles, and volume-driven confirmations degrade gracefully on symbols with missing or effectively empty volume.
  - Added optional intraday VWAP/session alignment as an extra long filter for users who want session-aware intraday confirmation.
  - Added a practical risk/exit overlay that exposes trigger, invalidation, ATR-buffered stop, and 1R/2R targets directly on the chart and dashboard.
  - Switched strict HTF trend confirmation to a confirmed-only `request.security()` pattern so live HTF bars can no longer repaint strict long-entry gating.
  - Fixed same-bar OB/FVG dip-and-reclaim detection so valid wick-through reclaim candles no longer get missed when the previous close was already back above the zone.
  - Restored newest-last ordering for broken OB and filled FVG event buffers, and aligned downstream alert level lookups with that ordering.
  - Fixed visible-range filtering to respect the effective rendered right edge of extended OB/FVG objects, including the OB break bar.
  - Aligned TradingView `alertcondition(...)` long-dip presets with the existing one-shot dynamic alerts by exposing the preset states as edge events.
  - Wired the volume-quality guard through the OB profile capture/alignment engine path, not only the profile rendering path.

- **SMC++ live alert and timeframe hardening:**
  - Fixed intrabar OB/FVG live alerts in `SMC++.pine` to prefer exact engine event buffers (`ob_broken_new_*`, `filled_fvgs_new_*`) before scanning active objects, preventing silent misses on the event bar.
  - Fixed FVG fill alert levels to report the correct newest filled gap level by using the engine's event ordering instead of `.last()`.
  - Hardened lower-timeframe and HTF-FVG timeframe validation for non-time-based charts by normalizing timeframe seconds and rejecting unsupported chart/HTF combinations explicitly.
  - Tightened HTF FVG validation so the selected HTF must again be strictly higher than the chart timeframe.
  - Upgraded realtime marker dedupe guards to `varip` so reclaim and long-state markers stay stable on open realtime bars.
  - Made OB/FVG engine execution explicit via hidden `Use OB engine` and `Use FVG engine` inputs, preserving the intended visual-only meaning of `Show` toggles while removing silent ambiguity.

### Added (2026-03-19)

- **SMC++ long-dip alert presets:**
  - Added seven reusable alert preset booleans in `SMC++.pine` for `Watchlist`, `Armed+`, `Early`, `Clean`, `Entry Best`, `Entry Strict`, and `Failed` long-dip states.
  - Added matching `alertcondition(...)` definitions so the presets are available directly in TradingView alerts.
  - Added matching `fire_dynamic_alert(...)` calls so dynamic alerts can emit the same long-dip lifecycle states with level context.
  - Added dedicated German and English documentation for the SMC++ dashboard and long-dip workflow under `docs/`.

### Changed (2026-03-19)

- **SMC++ dashboard layout tightened:**
  - Reworked the `SMC++.pine` dashboard to be narrower and taller by splitting wide aggregate rows into shorter stacked rows.
  - HTF trend, object counts, swing/internal levels, zone levels, and trigger levels now render as compact single-purpose rows instead of wide combined summaries.
  - Shortened dashboard labels and legend text so the panel uses vertical space more efficiently without removing state information.

### Added (2026-03-17)

- **Databento bullish-quality score presets:**
  - Added selectable Bullish-Quality weighting presets in `scripts/bullish_quality_config.py`:
    - `conservative`
    - `balanced` (default)
    - `aggressive`
  - The presets change how strongly market-structure signals influence `window_quality_score` without changing the export contract.
  - Added test coverage for preset resolution in `tests/test_generate_bullish_quality_scanner.py`.
  - Added Streamlit sidebar selection for the Bullish-Quality score profile in `databento_volatility_screener.py`.
  - Added production-export CLI support via `--bullish-score-profile` in `scripts/databento_production_export.py`.

### Changed (2026-03-17)

- **Databento structure-aware scanner ranking and documentation:**
  - Bullish-Quality remains structure-forward by default via the new `balanced` preset.
  - Added dedicated structure-feature documentation in `docs/DATABENTO_STRUCTURE_FEATURES.md`.
  - Extended `docs/RFC_BULLISH_QUALITY_PREMARKET_SCANNER.md` with structure-field and score-profile details.
  - Long-Dip and Bullish-Quality ranking now expose the new structure columns more clearly in the Streamlit UI.

### Added (2026-03-05)

- **USI-CHOCH early-entry upgrade (`USI-CHOCH.pine`):**
  - Added **Same-Bar Verify** for bullish CHoCH (`same-bar OR next-bar`), enabling earlier CHoCH confirmation.
  - Added **Early Signal Inputs** for anticipation and momentum pre-signals:
    - anticipation proximity (%),
    - momentum RSI/divergence window,
    - volume spike multiplier,
    - marker visibility toggles.
  - Added **Anticipation markers** (`A↑`/`A↓`) when price approaches swing levels under matching structure context.
  - Added **Momentum Pre-CHoCH markers** (`M↑`/`M↓`) using RSI divergence + volume spike conditions.
  - Added early-signal alertconditions:
    - `Anticipation Bullish/Bearish`,
    - `Momentum Pre-CHoCH Bullish/Bearish`.

### Changed (2026-03-05)

- **CHoCH fast-signal parity across scripts:**
  - The three “earlier BUY/CHoCH” improvements now exist in both `CHoCH.pine` and `USI-CHOCH.pine`:
    1. Same-Bar Verify,
    2. Anticipation,
    3. Momentum Pre-CHoCH.

### Changed (2026-03-04)

- **� RT Engine auto-start across all entry points:**
  - Added `ensure_rt_engine_running()` helper in `realtime_signals.py` — PID file management + pgrep fallback + `subprocess.Popen` background launch.
  - **streamlit_terminal.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud). Imports `RealtimeEngine` and `ensure_rt_engine_running`.
  - **streamlit_monitor.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud).
  - **vd_signals_live.sh**: Engine now auto-starts by default (previously required `--start-engine`). Added `--no-engine` flag to opt out.
  - **vd_watch.sh**: Auto-starts RT engine before rendering dashboard.
  - **vd_open_prep.sh**: Auto-starts RT engine before pipeline extraction.

- **🏆 Rankings tab enhanced with realtime signals (streamlit_terminal.py):**
  - Rankings composite score updated: **50% price move + 20% news + 15% RT technical + 15% RT signal tier**. Was 70/30 price/news.
  - New columns: **Signal** (A0/A1/A2), **Tech** (weighted indicator score), **RSI** (RSI-14 with color coding), **MACD** (signal direction).
  - Sort order now prioritizes RT signal tier (A0 > A1) within bullish/bearish tiers.
  - Loads full RT signal data from both VisiData JSONL and structured JSON, enriching each ranked symbol with technical scores, RSI, MACD, direction, and volume ratio from the RT engine.

- **�🔭 Realtime Signals — full universe monitoring (900+ symbols):**
  - Removed the fixed `top_n=15` watchlist limit. The engine now monitors **all scored symbols** from the pipeline run (typically 900+), not just the top-ranked candidates.
  - `_load_watchlist()` merges `ranked_v2` (top scored) + `filtered_out_v2` overflow entries (scored but below display cutoff) + `enriched_quotes` (remaining universe symbols) to build the full monitoring universe.
  - `DEFAULT_TOP_N` changed from `15` → `0` (meaning all). The `--top-n` CLI flag still works for backward compatibility (`--top-n 20` limits to 20).
  - `_enrich_watchlist_live()` now uses FMP bulk profile endpoint (`/stable/profile-bulk`) for avgVolume enrichment across 900+ symbols in a single call. Falls back to per-symbol profile calls (capped at 50) when bulk is unavailable.
  - `_fetch_realtime_quotes()` now chunks FMP batch-quote requests into groups of 500 symbols to avoid URL-length limits.
  - CLI help updated to reflect `0 = all` default.

- **🔧 Realtime Signals — TechnicalScorer integration (6 bug fixes):**
  - Added `TechnicalScorer` class integrating TradingView + FMP technical indicators (RSI, MACD, ADX, MA alignment) into signal detection.
  - Fixed CRITICAL bug: VisiData rows used undefined `existing` variable → `sym_signals` (NameError crash).
  - Fixed `_MIN_CALL_SPACING` 3.0 → 13.0s (must exceed TradingView's 12s rate limit).
  - Fixed RSI/tech A1→A0 upgrade bypassing dynamic cooldown anti-spam protection.
  - Fixed cache eviction to fall back to oldest-entries removal when TTL eviction alone doesn't shrink below max.
  - Fixed `_restore_signals_from_disk()` to include `technical_score`, `technical_signal`, `rsi`, `macd_signal` fields.
  - Fixed ADX scoring to be direction-neutral (amplifies existing bias instead of adding unconditional bullish tilt).

### Added (2026-03-02 – 2026-03-02)

- **📊 Actionable / Rankings / Segments tab enrichment:**

- **🧠 AI Insights consolidation & tab reorder:**
  - Removed the old "AI Insights" tab (was using basic TradingView-only context)
  - Renamed "FMP AI" → "AI Insights" (the multi-layer enriched version is now the default)
  - Deleted `terminal_tabs/tab_ai.py` (no longer needed)
  - Reordered tabs: AI Insights → Actionable → Segments → Rankings → Outlook → Live Feed → Bitcoin → Alerts → Data Table

- **📊 Actionable / Rankings / Segments tab enrichment:**
  - **Actionable tab** — now shows 6 new inline columns: `Price`, `Chg%`, `Social` (Finnhub), `Analyst` (FMP consensus + upside%), `NLP` (NewsAPI.ai), `P/E`, `Vol`. Includes column guide popover explaining each data source.
  - **Rankings tab** — added 4 new inline columns: `Tech` (TradingView signal), `Social`, `Analyst`, `P/E`. FMP batch quotes enrich price data when spike data is missing. Social sentiment and analyst forecasts use cached data or fetch fresh.
  - **Segments tab** — added GICS sector performance overlay (expandable metric cards at top). "Top Symbols per Segment" drill-down now shows `Price`, `Chg%`, `Tech`, `Social`, `Analyst`, `P/E` columns per ticker.
  - All three tabs gracefully fall back to cached data or empty columns when APIs are unavailable.

- **🧠 FMP AI multi-layer enrichment (8 new data sources):**
  - FMP AI context now includes **11 data layers** (up from 3) for dramatically richer LLM analysis:
    1. **FMP quotes** (price, change%, volume, P/E, EPS) — *existing*
    2. **FMP profiles** (sector, industry, beta) — *existing*
    3. **TradingView technicals** (RSI, MACD, Stoch, MAs) — *existing*
    4. **Economic calendar** — today's US macro events (GDP, CPI, FOMC, NFP) with estimates vs actuals from FMP
    5. **Sector performance** — 11 GICS sector % changes for rotation analysis from FMP
    6. **Social sentiment** — Reddit + Twitter mention counts and bullish/bearish scores from Finnhub
    7. **Analyst forecasts** — price targets, consensus ratings, EPS estimates, recent upgrades/downgrades from FMP
    8. **Benzinga analyst ratings** — institutional upgrades, downgrades, price target changes (last 7 days)
    9. **Benzinga earnings calendar** — upcoming/recent EPS and revenue estimates vs actuals (±7 days)
    10. **Insider trades** — recent executive buys/sells with transaction values from FMP
    11. **Congressional trades** — Senate + House member stock trades from FMP
  - Each data source has independent caching and graceful fallback if the API is unavailable.
  - UI metadata line now shows `🔗 N data layers` count alongside existing article/ticker/FMP metrics.
  - System prompt upgraded to instruct the LLM to cross-reference ALL available layers and identify disconnects (e.g. bullish news + bearish technicals, insider selling + analyst upgrades).
  - Context expander description updated to list all data sources.
  - `assemble_context()` expanded with 8 new optional keyword parameters — fully backward-compatible.

- **🏦 FMP AI tab (new):**
  - Mirrors the AI Insights tab UI — same 6 preset questions, custom question input, Generate/Regenerate/Clear buttons.
  - Fetches real-time FMP quotes (price, change%, volume, market cap, P/E, EPS) and company profiles (sector, industry, beta) for the top 12 tickers in the feed.
  - Sends FMP-enriched context to OpenAI GPT-4o with a finance-data-aware system prompt that cross-references news sentiment with actual price action.
  - Separate session state keys (`fmp_ai_*`), separate cache, separate save file (`fmp_ai_trade_ideas.txt`).
  - Auto-refresh pauses when FMP AI result is being reviewed (`fmp_ai_pause_auto_refresh`).
  - Requires both `FMP_API_KEY` and `OPENAI_API_KEY`.
  - New files: `terminal_fmp_insights.py` (backend), `terminal_tabs/tab_fmp_ai.py` (UI).
  - Tab count increased 9 → 10.

- **FMP technicals fallback provider:**
  - New `terminal_fmp_technicals.py` module — fetches RSI(14), MACD(12,26), Stochastic(14,3,3), Williams %R(14), ADX(14), SMA & EMA (10, 20, 50, 100, 200) from FMP REST API.
  - Computes Buy/Sell/Neutral signals using standard thresholds (RSI >70/< 30, MACD crossover, Stoch >80/<20, etc.).
  - Returns data in the same `TechnicalResult` format as TradingView — transparent to all callers.
  - 3-minute in-memory cache with thread-safe locking and auto-eviction.
  - FMP has 3,000 calls/min rate limit — no 429 risk.

### Fixed (2026-03-02 – 2026-03-02)

- **TradingView 429 spam — proper cooldown escalation (`51a84e6`):**
  - `_tv_register_success()` was resetting the consecutive 429 counter while a cooldown was still active, preventing escalation (120s → 240s → 480s). Now only resets when cooldown has fully expired.
  - Cooldown early-return in `fetch_technicals()` now caches its result so repeated calls during cooldown skip immediately.
  - Cooldown `RuntimeError`s from `_tv_throttle()` are now distinguished from actual TradingView 429 responses — they no longer re-register as new 429s, which was artificially escalating cooldown timers.
  - Cooldown-block log messages downgraded from WARNING to DEBUG to reduce noise.

- **AI Insights infinite spinner — 30s time budget (`d98aa25`):**
  - The AI tab was hanging at "Fetching technicals for 8 tickers…" because each TradingView call has a 12s minimum spacing (anti-429 throttle). 8 tickers × up to 3 exchanges × 12s = up to 288 seconds of blocking.
  - Added a 30-second time budget to the technicals fetch loop — breaks out early and uses whatever was collected.
  - Falls back to previously cached technicals from session state if the time budget expires before any fresh data is fetched.
  - Spinner now shows "≤30 s" hint so users know it won't hang indefinitely.

- **AI tabs blocked during TradingView cooldown (`bb61050`, `caf082d`):**
  - AI Insights and FMP AI tabs now check `_tv_is_cooling_down()` before the technicals fetch loop and skip entirely when TradingView is rate-limited.
  - Shows a visible caption with remaining cooldown time (e.g., "⏳ TradingView rate-limited — cooldown 120s remaining. Using cached technicals.").
  - Both tabs proceed straight to the LLM query with whatever data is available.
  - Technical Data expander widgets in `streamlit_terminal.py` and `_shared.py` also had redundant cooldown guards that were removed after fallback integration.

- **FMP as automatic TradingView fallback (`cbee41f`):**
  - `fetch_technicals()` cooldown path now calls `_fmp_fallback()` which imports `fetch_fmp_technicals` and converts its dict result to a `TechnicalResult`.
  - When TradingView is in 429 cooldown (120–900s), all callers transparently receive FMP-sourced technicals instead of error results.
  - FMP results are cached in the TradingView cache so subsequent calls return instantly.
  - Redundant widget-level cooldown guards removed from `streamlit_terminal.py` and `terminal_tabs/_shared.py` since `fetch_technicals()` now handles fallback internally.

- **Deprecated `use_container_width` warnings (`836e223`, `72385f0`):**
  - Replaced all 7 occurrences of `use_container_width=True` with `width='stretch'` across `streamlit_terminal.py` (3), `terminal_tabs/tab_ai.py` (3), and `terminal_tabs/tab_heatmap.py` (1).

- **Rankings tab empty during off-hours (`f592850`):**
  - Rankings tab was empty because it only sourced from `SpikeDetector.events` (empty outside market hours).
  - Added feed items as a fallback data source so Rankings populates whenever there is feed data.

- **Sector performance chart styling (`b32de5f`):**
  - Restored original vertical bar chart with red-yellow-green gradient (`#FF1744`, `#FFC107`, `#00C853`), dark background, and angled labels — matching the pre-refactor appearance.

### Changed (2026-03-02 – 2026-03-02)

- **API budget optimization (`fc477c6`):**
  - Removed 10 low-value tabs (~1,500 lines of UI code) to reduce API call volume and rendering overhead.
  - Poll interval changed from 5s → 10s during market hours.
  - Added 30-second periodic dedup reset to prevent feed staleness from accumulating duplicate filters.
  - Slowed Bitcoin-related TTLs to reduce FMP bandwidth consumption.
  - Refactored Rankings tab to use only feed + RT spike data (removed extra API calls).
  - Removed 7 orphaned cached functions that were no longer called after tab removal.
  - Added Sector Performance chart above the tab bar.
  - Created `docs/API_BUDGET_CALCULATIONS.md` with detailed FMP budget analysis (150 GB/30d bandwidth, 3,000 calls/min rate limit).

- **Feed staleness bypass fix (`6d9732e`):**
  - `notify_ingest()` now only fires when the feed actually grows, preventing false staleness resets.

### Added (2026-03-03)

- **Live technicals wired into AI Insights:**
  - `tab_ai.py` now fetches real TradingView technical analysis (RSI, MACD, ADX, oscillators, MAs) for the top 8 tickers by |news_score| on each AI query, using the 15m interval.
  - Previously `_cached_technicals` was referenced but never populated — LLM context only included news headlines. The LLM now receives technicals summaries alongside news, dramatically improving Trade Ideas and Market Pulse quality.
  - Results cached in `st.session_state["_cached_technicals"]` for reuse across tabs.

- **Tech badge column in dashboard tabs:**
  - Top Movers, Actionable, and Defense & Aerospace tabs now display a **Tech** column showing TradingView summary signals (🟢 Buy, 🔴 Sell, ⚪ Neutral, etc.) for each symbol.
  - Added `_get_tech_summary()` helper in `streamlit_terminal.py` reads cached technicals from session state.

- **🎯 Actionable tab (new — tab #4):**
  - Curated view of high-conviction trade setups ranked by composite news + technical score.
  - Includes Tech badge column and news score overlay.
  - Tab count increased 18 → 19.

- **Today Outlook in Outlook tab:**
  - Outlook tab now shows both **Today** and **Next-Trading-Day** outlooks side by side.
  - `compute_today_outlook()` function added to `terminal_poller.py` — uses shared `_compute_outlook_for_date()` core with the current trading day (returns "MARKET CLOSED" on non-trading days).
  - Tomorrow outlook refactored into shared core (`_compute_outlook_for_date()`) with backward-compatible aliases.

- **CHOCH-Indicator.pine alertcondition() calls:**
  - Added 4 `alertcondition()` calls — **Buy**, **Short**, **Exit** (close long), **Cover** (close short) — enabling TradingView "Create Alert" directly from the CHOCH indicator.

- **Leveraged ETF skip-list in terminal_forecast.py:**
  - Added `_NO_FUNDAMENTALS_SYMBOLS` set (~45 tickers: SOXL, TQQQ, UVXY, TSLL, etc.) to skip yfinance fundamental lookups that always 404.
  - Added 30-min negative-TTL cache (`_CACHE_NO_DATA_TTL_S`) to avoid re-fetching symbols with no data.
  - Silenced yfinance internal logger (set to CRITICAL) to stop noisy 404 ERRORs flooding the console.

### Fixed (2026-03-03)

- **Race condition in BackgroundPoller:** `wake_event.set()` now properly interrupts `stop_event.wait()` — replaced `stop_event.wait()` with `wake_event.wait()` inside the poll loop and checking `stop_event.is_set()` explicitly.
- **BackgroundPoller stop_and_join():** Added `stop_and_join()` method for clean thread shutdown in tests and session teardown; previous code called `stop_event.set()` but never joined the thread.
- **Feed stuck on exception:** Empty-poll counter now increments on exception paths too, preventing infinite exception loops that kept the poller alive without producing data.
- **Auto-prune oscillation:** Changed auto-prune `keep=250` → `keep=0` to fully clear the dedup gate and unblock fresh fetches instead of partially pruning.
- **SQLite corruption resilience:** `store_sqlite.py` now runs `PRAGMA quick_check` on init; if the database is corrupt, it auto-renames the file and creates a fresh database instead of crashing.
- **Movers KeyError guards:** Added `.get()` guards for Benzinga movers response fields (`symbol`, `change`, `price`) that could be missing, preventing uncaught KeyError crashes.
- **Feed staleness churn loop:** Feed lifecycle recovery now tracks `last_ingest_ts` (time of most recent successful ingest) with a configurable grace period, preventing the recovery loop from firing repeatedly when published timestamps are old but the feed is actually active.
- **AI Insights "Clear AI result" button:** Added `st.rerun()` after clearing session state so the UI immediately reflects the cleared state.
- **AI Insights preset button switching:** Added `st.rerun()` after preset button clicks (e.g., switching from "Market Pulse" to "Trade Ideas") to ensure the new question is processed immediately instead of requiring a second click.

### Changed (2026-03-03)

- **Technicals cache TTL reduced:** `terminal_technicals.py` `_CACHE_TTL_S` changed from 900s (15 min) → 180s (3 min) for fresher intraday data.
- **"News Score" column rename:** "Score" column in Movers tab renamed to "News Score" for clarity, avoiding confusion with technical/composite scores.
- **CHOCH-Base_Indikator.pine defaults aligned:** `ms_logic` default changed "Standard" → "SMC+Sweep", `ms_mode` default changed "Verify" → "Ping" to match strategy defaults.
- **SkippALGO_Strategy.pine cooldown sync:** Added `presetAutoCooldown` input and synchronized `cooldownTriggersEff`/`ModeEff`/`MinutesEff`/`BarsEff` to respect preset-driven cooldown overrides.
- **VWAP_Reclaim_Indicator.pine alert rename:** Alert titles renamed from "Long Entry / Exit Long / Short Entry / Exit Short" to "Buy / Exit / Short / Cover" for consistency with CHOCH and SkippALGO conventions.
- **Outlook tab refactored:** Renamed from "Tomorrow Outlook" to "Today & Next-Trading-Day Outlook", with `_compute_outlook_for_date()` shared core eliminating code duplication.
- **Outlook return keys normalized:** Generic keys (`target_date`, `earnings_count`, `high_impact_events`) with backward-compatible aliases for existing consumers.

### Fixed (2026-03-02)

- **Streamlit Cloud inotify crash:** Added `fileWatcherType = "none"` to `.streamlit/config.toml` to prevent `OSError: [Errno 24] inotify instance limit reached` on shared Linux hosts. Streamlit's default `watchdog`-based file watcher exhausted the low inotify limit, cascading to EMFILE errors on all network connections (Benzinga, FMP).
- **EMFILE resilience in `load_jsonl_feed`:** Catch `OSError` during JSONL file read so the app degrades gracefully (returns partial data) instead of crashing if file descriptors are exhausted.
- **Sidebar API key detection:** Re-reads `os.environ` directly instead of stale cached `TerminalConfig`, so keys added to `.env` after session start are detected.
- **Streamlit Cloud secrets bridge:** Added `_load_streamlit_secrets()` to both `streamlit_terminal.py` and `open_prep/streamlit_monitor.py` — copies `st.secrets` into `os.environ` for Cloud deployments where `.env` is gitignored.
- **RT Engine path resolution:** VD signals JSONL path now resolved as absolute (`PROJECT_ROOT`-relative) so CWD doesn't matter.

### Changed (2026-03-02)

- **Rebranding: "Real-Time News Intelligence Dashboard — AI supported":**
  - Replaced all "Bloomberg-style" / "News Terminal" branding references across README, docstrings, LLM system prompt, changelog, requirements.txt, and docs/BLOOMBERG_TERMINAL_PLAN.md.
  - Page title and main heading in `streamlit_terminal.py` updated.
  - Added AI Insights anchor link directly below the main heading.
  - Kept factual references to Bloomberg as a news source (source tier classification in playbook.py, FMP endpoint docs) — only product branding was neutralized.
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
  - Added explicit product positioning language (**Research & Monitoring Terminal**, **News Intelligence + Alerting**, **Workflow/Decision Support**) and clear compliance disclaimers (no personalized recommendations, no order execution).
- **Ops runbook refresh (`docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`):**
  - Updated document date to `01.03.2026`.
  - Added copy/paste sections for RT engine **Start / Verify / Restart** including process and artifact freshness checks.
  - Added the same positioning/compliance framing to align operations documentation with README messaging.

### Changed (2026-02-28)

- **README.md rewritten:** Comprehensive GitHub-ready documentation covering Real-Time News Intelligence Dashboard (17-tab architecture, module map, data sources, configuration, background poller, notifications, export), Open-Prep Pipeline (Streamlit monitor, macro explainability), Pine Script (Outlook/Forecast, signal modes, key features), and Developer Guide (tests, linting, project structure, documentation index).

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

- **News Intelligence Dashboard integration (workspace):**
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

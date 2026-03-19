# SkippALGO

**Pine Script v6 Signal Engine · Real-Time News Intelligence Dashboard · Pre-Open Briefing Pipeline**

SkippALGO is a modular trading intelligence platform combining three core systems:

1. **SkippALGO Pine Script** — non-repainting signal engine with multi-timeframe Outlook/Forecast dashboard for TradingView.
2. **Real-Time News Intelligence Dashboard** — an AI-supported **Research & Monitoring Terminal** with 19 tabs for **News Intelligence + Alerting** and operational market monitoring.
3. **Open-Prep Pipeline** — automated pre-open briefing system with ranked candidates, macro context, and structured trade cards.

## Product Positioning & Compliance Notes

- SkippALGO is positioned as a **Research & Monitoring Terminal**.
- Core value proposition: **News Intelligence + Alerting**.
- Primary use case: **Workflow/Decision Support** — not direct “Buy/Sell” instructions.

### Important Disclaimer

- This project provides market data aggregation, analytics, alerts, and workflow support.
- It does **not** provide personalized investment recommendations.
- The main dashboard and Pine components do **not** auto-execute trades by default.
- Optional local scripts may generate or submit user-authorized broker orders only when they are explicitly invoked from the command line.
- Users remain solely responsible for their own investment decisions, risk management, and regulatory compliance.

---

## Table of Contents

- [Real-Time News Intelligence Dashboard](#real-time-news-intelligence-dashboard)
- [Open-Prep Pipeline](#open-prep-pipeline)
- [Databento Volatility Suite](#databento-volatility-suite)
- [SkippALGO Pine Script](#skippalgo-pine-script)
- [Developer Guide](#developer-guide)
- [Documentation Index](#documentation-index)

---

## Real-Time News Intelligence Dashboard

A self-hosted, AI-supported financial intelligence dashboard built with Streamlit. It serves as a **Research & Monitoring Terminal** for **News Intelligence + Alerting** and **Workflow/Decision Support**. It aggregates news, market data, sentiment, and technical analysis from multiple providers into a single unified interface.

### Architecture

The terminal is composed of 16 Python modules organized around a central UI driver:

```
┌──────────────────────────────────────────────────────────────────┐
│                    streamlit_terminal.py                          │
│                  (4 700+ lines · 19 tabs · main UI)              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ terminal_poller  │  │ terminal_bitcoin │  │ terminal_      │  │
│  │  poll_and_       │  │  10 fetch fns    │  │  newsapi       │  │
│  │  classify()      │  │  FMP+yfinance+   │  │  NewsAPI.ai    │  │
│  │  FMP+Benzinga    │  │  TradingView     │  │  breaking/     │  │
│  │  scoring engine  │  │  Finnhub         │  │  trending/NLP  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
│           │                     │                     │          │
│  ┌────────┴─────────┐  ┌───────┴──────────┐  ┌───────┴────────┐ │
│  │ terminal_spike_  │  │ terminal_        │  │ terminal_      │ │
│  │  scanner         │  │  technicals      │  │  forecast      │ │
│  │  + spike_        │  │  TradingView TA  │  │  FMP analyst   │ │
│  │  detector (RT)   │  │  oscillators/MA  │  │  targets/EPS   │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │ terminal_        │  │ terminal_feed_   │  │ terminal_      │ │
│  │  notifications   │  │  lifecycle       │  │  background_   │ │
│  │  Telegram/       │  │  staleness       │  │  poller        │ │
│  │  Discord/        │  │  detection &     │  │  async poll    │ │
│  │  Pushover        │  │  auto-recovery   │  │  loop          │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │ terminal_export  │  │ terminal_ui_     │  │ terminal_ai_   │ │
│  │  JSONL/VisiData  │  │  helpers         │  │  insights      │ │
│  │  webhook fire    │  │  sentiment fmt   │  │  LLM reasoning │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ terminal_tabs/  (18 tab modules — ~2 300 lines)             │ │
│  │  tab_feed · tab_ai · tab_rankings · tab_segments · ...      │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                       newsstack_fmp/                             │
│  ingest_benzinga.py · ingest_fmp.py · scoring.py · store_sqlite │
│  ingest_benzinga_calendar.py · ingest_benzinga_financial.py      │
│  pipeline.py · normalize.py · enrich.py · config.py              │
└──────────────────────────────────────────────────────────────────┘
```

### Module Map

| Module | Lines | Purpose |
|--------|-------|---------|
| `streamlit_terminal.py` | ~4 700 | Main Streamlit UI — 19 tabs, sidebar, polling orchestration, alert evaluation |
| `terminal_poller.py` | ~1 300 | Polling engine — REST/FMP ingestion, dedup, classification, sector perf, defense watchlist, tomorrow outlook, power gaps |
| `terminal_bitcoin.py` | ~950 | Bitcoin data — 10 fetch functions (quote, OHLCV, technicals, news, social, F&G, movers, exchange listings) |
| `terminal_newsapi.py` | ~1 150 | NewsAPI.ai — breaking events, trending concepts, NLP sentiment, event-clustered news, social score ranking |
| `terminal_spike_scanner.py` | ~500 | FMP spike scanner — gainers/losers/actives with Benzinga extended-hours overlay |
| `terminal_spike_detector.py` | ~320 | RT spike detector — sub-minute price delta tracking with rolling buffer |
| `terminal_technicals.py` | ~480 | TradingView TA — oscillator/MA summaries, cached per (symbol, interval), 3-min TTL |
| `terminal_forecast.py` | ~430 | Analyst forecasts — price targets, ratings, EPS estimates via FMP + yfinance |
| `terminal_notifications.py` | ~410 | Push notifications — Telegram, Discord, Pushover dispatch with per-symbol throttling |
| `terminal_export.py` | ~730 | Export — JSONL append/rotate, VisiData snapshots, webhook fire, RT quote loading |
| `terminal_feed_lifecycle.py` | ~320 | Feed health — staleness detection, auto-recovery (cursor reset + SQLite dedup prune) |
| `terminal_background_poller.py` | ~270 | Background poller — threaded async poll loop for Streamlit session state |
| `terminal_ui_helpers.py` | ~490 | UI formatting — sentiment badges, Streamlit column utilities |
| `terminal_ai_insights.py` | ~285 | AI Insights engine — LLM-powered market reasoning over live feed data |
| `terminal_tabs/` | ~2 300 | Tab rendering modules — one module per tab (feed, AI, rankings, etc.) |
| `newsstack_fmp/` | ~2 500 | News pipeline — Benzinga adapters (REST, WS, calendar, financial), FMP adapter, SQLite store, scoring, enrichment |

### Tabs Overview

| # | Tab | Description |
|---|-----|-------------|
| 1 | 📰 **Live Feed** | Real-time Benzinga + FMP news with 16-category NLP classifier, full-text search, and date filters |
| 2 | 🤖 **AI Insights** | LLM-powered market analysis — structured reasoning over live feed + TradingView technicals with cached responses |
| 3 | 🏆 **Rankings** | Symbol-level news scoring with aggregated sentiment, volume signals, and RT quote overlay |
| 4 | � **Actionable** | High-conviction trade setups ranked by composite news + technical score with Tech badges |
| 5 | �🏗️ **Segments** | News items grouped by 16 event categories (earnings, M&A, FDA, macro, etc.) |
| 6 | ₿ **Bitcoin** | BTC dashboard: price, chart, technicals, Fear & Greed, news, social sentiment, crypto movers |
| 7 | ⚡ **RT Spikes** | Sub-minute real-time price spike detection from consecutive quote snapshots |
| 8 | 🚨 **Spikes** | FMP biggest gainers/losers/most-actives with batch-quote enrichment |
| 9 | 🗺️ **Heatmap** | Plotly treemap sector heatmap of market performance |
| 10 | 📅 **Calendar** | FMP economic calendar with impact filters |
| 11 | 🔮 **Outlook** | Today & next-trading-day composite forecast (traffic light system) |
| 12 | 🔥 **Top Movers** | FMP gainers/losers enriched with Benzinga delayed quotes during extended hours |
| 13 | 💹 **Movers** | Benzinga movers with gainers/losers sub-tabs + Tech badges |
| 14 | 🛡️ **Defense & Aerospace** | A&D watchlist quotes + industry performance screen + Tech badges |
| 15 | 🔴 **Breaking** | NewsAPI.ai breaking events with article counts, sentiment, social scores |
| 16 | 📈 **Trending** | NewsAPI.ai trending concepts and entities across global news |
| 17 | 🔥 **Social** | Social sentiment scoring and viral article detection |
| 18 | ⚡ **Alerts** | Compound alert builder with configurable rules and webhook dispatch |
| 19 | 📊 **Data Table** | Full data export table with all enrichment columns |

### Live Feed Score Badge Semantics

The **Score** column in `📰 Live Feed` combines impact strength and directional sentiment:

- High-impact bullish: green bold (`🟢`, score ≥ `0.80`)
- High-impact bearish: red bold (`🔴`, score ≥ `0.80`)
- Moderate bullish: yellow (`🟡`, score ≥ `0.50`)
- Moderate bearish: orange (`🟠`, score ≥ `0.50`)
- Low impact: plain text (`score < 0.50`)

Directional prefixes in the badge are:

- `+` bullish
- `−` bearish
- `n` neutral

The `🔍` badge marks **WIIM** (“Why It Matters”) enriched items.

### Data Sources

| Provider | API Key Env Var | Coverage |
|----------|-----------------|----------|
| **Benzinga** | `BENZINGA_API_KEY` | News (REST + WebSocket), calendar (ratings, earnings, economics, dividends, splits, IPOs, guidance, retail), financial data, delayed quotes, movers |
| **FMP** | `FMP_API_KEY` | Quotes, sector performance, economic calendar, gainers/losers/actives, crypto, fear & greed, analyst targets, company profiles |
| **NewsAPI.ai** | `NEWSAPI_AI_KEY` | Breaking events, trending concepts, NLP sentiment scoring |
| **TradingView** | *(none — scraper)* | Technical analysis (oscillators, moving averages) for equities and crypto |
| **yfinance** | *(none — free)* | Fallback historical OHLCV, market cap, company info |
| **Finnhub** | `FINNHUB_API_KEY` | Social sentiment for crypto |

### Quick Start (Terminal)

```bash
# 1. Clone and install
git clone https://github.com/skipp-dev/skipp-algo.git
cd skipp-algo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env   # or create .env manually
# Required:
#   BENZINGA_API_KEY=your_key
# Optional (enables more tabs):
#   FMP_API_KEY=your_key
#   NEWSAPI_AI_KEY=your_key
#   FINNHUB_API_KEY=your_key

# 3. Run
streamlit run streamlit_terminal.py
```

The dashboard opens at `http://localhost:8501` with a dark theme.

### Configuration

**Environment variables** (`.env` file or shell):

| Variable | Required | Description |
|----------|----------|-------------|
| `BENZINGA_API_KEY` | Yes | Benzinga API key for primary news feed |
| `FMP_API_KEY` | No | FMP key for quotes, calendar, sector data, crypto |
| `NEWSAPI_AI_KEY` | No | NewsAPI.ai key for breaking/trending/NLP tabs |
| `FINNHUB_API_KEY` | No | Finnhub key for crypto social sentiment |
| `TERMINAL_NOTIFY_ENABLED` | No | `1` to enable push notifications |
| `TERMINAL_NOTIFY_MIN_SCORE` | No | Minimum news score for notification (default: `0.85`) |
| `TERMINAL_NOTIFY_THROTTLE_S` | No | Throttle window in seconds (default: `600`) |
| `TERMINAL_WEBHOOK_URL` | No | Webhook URL for alert dispatch |
| `TERMINAL_POLL_INTERVAL` | No | Poll interval in seconds (default: `15`) |
| `TERMINAL_TOPICS` | No | Comma-separated topic filter for Benzinga |

**Streamlit config** (`.streamlit/config.toml`):

```toml
[server]
headless = true
address = "0.0.0.0"
port = 8501
# Disable inotify-based file watcher to prevent EMFILE crashes
# on Streamlit Cloud (shared Linux hosts with low inotify limits).
# For local development, override with:
#   streamlit run --server.fileWatcherType watchdog streamlit_terminal.py
fileWatcherType = "none"

[theme]
base = "dark"
```

### Background Poller

The terminal supports a threaded background poller that fetches new data between Streamlit reruns. This prevents data gaps when the browser tab is inactive:

- Poller runs continuously in a background thread
- Results are stored in `st.session_state` and merged on next rerun
- Feed lifecycle manager detects staleness (>5 min) and auto-recovers via cursor reset + SQLite dedup prune
- Manual "Reset Cursor" button in sidebar as escape hatch

### Notifications

High-score news items can trigger push notifications to:

- **Telegram** (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`)
- **Discord** (`DISCORD_WEBHOOK_URL`)
- **Pushover** (`PUSHOVER_USER_KEY` + `PUSHOVER_APP_TOKEN`)

Notifications are throttled per symbol (default: 10 min) and thread-safe.

### Export & VisiData

- **JSONL** — continuous append to `artifacts/*.jsonl` with automatic rotation
- **VisiData snapshots** — `artifacts/vd_snapshot.jsonl` for `vd --reload` live monitoring
- **Webhook** — fire classified items to external endpoints (SSRF-protected)
- **Benzinga Calendar JSONL** — standalone export of dividends, splits, IPOs, guidance events

---

## Open-Prep Pipeline

`open_prep/` generates reproducible pre-open briefings for a symbol universe:

- Quotes enriched with gap metadata (mode, availability, evidence timestamps)
- Macro context (economic indicators, earnings, institutional data) merged into candidate ranking
- Optional news catalyst scores via Benzinga + NLP
- Top-N candidates exported with structured trade cards and ATR-based stop/trail profiles
- Score-driven and setup-oriented (ORB, VWAP-hold patterns)

### Open-Prep Streamlit Monitor

A companion Streamlit app for live pre-open monitoring:

```bash
streamlit run open_prep/streamlit_monitor.py
```

- Auto-refresh with a hard minimum interval of 5 seconds (`MIN_AUTO_REFRESH_SECONDS`)
- Built-in rate-limit cooldown handling (`429`/rate-limit warnings trigger temporary backoff)
- Sidebar: symbols, gap mode, ATR settings, pre-open filters
- Benzinga Intelligence tabs (dividends, splits, IPOs, guidance, retail, top news, options flow)
- Realtime auto-promotion: A0/A1 signal symbols promoted from below-cutoff into displayed candidates
- Smart cache strategy: UI refresh can run from cache while live fetches are throttled to reduce API pressure
- Staleness detection with auto-recovery (cache invalidation when stale >5 min during market hours)
- Per-run pipeline status panel with stage progress and elapsed runtime
- UTC + Berlin dual timestamp display for operational clarity
- Session-aware pricing: during pre/after-hours, Benzinga delayed quotes are overlaid on stale close-based prices where available

### Open-Prep Realtime Engine (A0/A1) — Operations Quickstart

`open_prep/streamlit_monitor.py` reads realtime signals from disk. The engine is a
**separate long-running process** and does not auto-start with the Streamlit page.

```bash
# Start engine (recommended for active monitoring)
source .venv/bin/activate
PYTHONPATH="$PWD" python -m open_prep.realtime_signals --ultra

# Alternative: lower API pressure
PYTHONPATH="$PWD" python -m open_prep.realtime_signals --interval 15
```

Health check (without opening UI internals):

```bash
PYTHONPATH="$PWD" python - <<'PY'
from open_prep.realtime_signals import RealtimeEngine
d = RealtimeEngine.load_signals_from_disk()
signals = d.get("signals") or []
print("updated_at:", d.get("updated_at"))
print("stale:", bool(d.get("stale")), "stale_age_s:", int(d.get("stale_age_s") or 0))
print("signals:", len(signals), "A0:", sum(1 for s in signals if s.get("level") == "A0"), "A1:", sum(1 for s in signals if s.get("level") == "A1"))
PY
```

If Monitor shows *"RT Engine not running"*:

1. Ensure process exists: `pgrep -fal "open_prep.realtime_signals"`
2. Check signal artifact freshness: `artifacts/open_prep/latest/latest_realtime_signals.json`
3. Restart cleanly if needed: `pkill -f "open_prep.realtime_signals"` then start again.

For runbook-style incident handling, see: `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`.

### Macro Explainability

Each candidate includes:

- `macro_score_components[]` with canonical event, consensus, surprise, weight, contribution, data quality flags
- `ranked_candidates[]` with allowed setups, max trades, data sufficiency, no-trade reason, score breakdown
- Risk-off regime handling: long setups degraded to `vwap_reclaim` with `max_trades=1`

---

## Databento Volatility Suite

The repository now includes a dedicated Databento-driven screening and execution workflow for full-universe US equities.

It is split into four layers:

1. `databento_volatility_screener.py` for the core data model, caching, window logic, export helpers, and Streamlit UI.
2. `scripts/databento_production_export.py` for the production export pipeline that materializes full-universe feature bundles.
3. `scripts/generate_databento_watchlist.py` for Long-Dip watchlist generation from export bundles.
4. `scripts/execute_ibkr_watchlist.py` for IBKR dry-run previews and optional live order submission.

### What It Produces

- Full-universe daily feature tables based on Databento daily and 1-second bars
- Premarket feature tables for gap and volume-driven filtering
- Ranked pre-open watchlists with three laddered entry levels, take-profit, stop-loss, and trailing-stop anchors
- Export bundles with manifest metadata, Parquet artifacts, and formatted Excel workbooks
- Optional IBKR order previews or live bracket-order execution

### What The Script And UI Actually Do

The Databento workflow has two distinct roles:

- `scripts/databento_production_export.py` is the batch pipeline. It fetches the universe, daily bars, and 1-second data, computes symbol-day features, ranks the universe, and writes the reusable export bundle.
- `streamlit_databento_volatility_screener.py` launches the operator UI. The UI does not invent a separate model; it orchestrates refresh runs, reads the latest exported bundle, generates the watchlist, and explains the current state of the data basis.

In practical terms:

- the batch script is what creates the data foundation,
- the UI is what lets you inspect freshness, trigger the right pipeline mode, generate the watchlist, and review per-symbol trade-plan outputs.

### What Gets Calculated

For each `(trade_date, symbol)` the pipeline builds a symbol-day feature row from Databento daily and `ohlcv-1s` data.

Core open-window metrics:

- `window_return_pct = ((window_end_price / window_start_price) - 1) * 100`
- `window_range_pct = ((window_high - window_low) / window_start_price) * 100`
- `realized_vol_pct = sqrt(sum(log-return^2)) * 100` across the 1-second series inside the screening window
- `prev_close_to_premarket_pct = ((premarket_last / previous_close) - 1) * 100`
- `premarket_to_open_pct = ((market_open_price / premarket_last) - 1) * 100`
- `open_to_current_pct = ((window_end_price / market_open_price) - 1) * 100`

Additional open-drive and early-behavior metrics:

- `open_30s_volume`, `open_1m_volume`, `open_5m_volume`
- `early_dip_low_10s`, `early_dip_pct_10s`, `early_dip_second`
- `reclaimed_start_price_within_30s`, `reclaim_second_30s`
- rolling relative-volume features such as `open_1m_rvol_20d`, `open_5m_rvol_20d`, and `day_volume_rvol_20d`

Selection and ranking logic:

- each symbol-day is marked `is_eligible` only if required reference, daily, and intraday inputs exist and the row is supported by Databento
- eligible rows are ranked within each trade date by `window_range_pct` descending, ties by symbol ascending
- `take_n_for_trade_date = ceil(eligible_count_for_trade_date * top_fraction)`
- `selected_top20pct = rank_within_trade_date <= take_n_for_trade_date`

This means the exported bundle contains both the raw feature values and the selection state that later drives the reduced-scope fast refresh and the watchlist layer.

### Watchlist Logic

The watchlist generator is downstream of the export bundle. It filters the latest symbol-day rows using premarket liquidity and gap rules, then assigns a ranking and builds a Long-Dip entry plan.

Candidate filtering focuses on:

- `has_premarket_data == True`
- positive and sufficiently large `prev_close_to_premarket_pct`
- minimum previous close
- minimum premarket dollar volume, share volume, and optionally trade count

Candidate ranking is then based on:

- `watchlist_score = gap_component + 0.75 * volume_component + 0.50 * trade_component`
- `research_score = watchlist_score + 0.25 * window_range_pct + 0.10 * realized_vol_pct`

For each selected symbol, the watchlist layer calculates three laddered entry levels and the corresponding take-profit, stop-loss, and trailing-stop anchor prices.

### UI Workflow

The standalone Streamlit UI is an operations console for this workflow.

Main sidebar inputs:

- Databento API key
- optional FMP API key
- export directory
- dataset
- lookback days
- Top-N watchlist size
- fast-scope-days override
- force refresh toggle

Main actions:

- `Fast Pre-Open Refresh`: refreshes the reduced near-open scope from the latest full-history baseline
- `Full History Refresh`: rebuilds the broad baseline bundle across the configured lookback window
- `Generate Watchlist`: reads the latest exports and rebuilds the ranked Long-Dip watchlist
- `Fast Pre-Open Pipeline`: runs fast refresh and watchlist generation in one step

What the UI shows:

- data freshness and manifest-derived status
- latest runtime durations
- active config snapshot
- Top-N watchlist in latest-date or full-history mode
- filter-profile diagnostics when liquidity rules are relaxed or when no candidates survive
- per-entry plan fields such as ladder prices, stop-losses, take-profit targets, and trailing-stop anchors

### Output Artifacts And Meaning

The production export pipeline writes both manifest-backed bundle artifacts and exact-named Parquet files. The most important downstream files are:

- `daily_symbol_features_full_universe.parquet`: one row per symbol-day with reference data, open-window metrics, eligibility, ranking, and `selected_top20pct`
- `premarket_features_full_universe.parquet`: one row per symbol-day with premarket OHLCV-style summary fields such as `premarket_last`, `premarket_vwap`, volume, dollar volume, and trade count
- `full_universe_second_detail_open.parquet`: per-second open-window detail with `session`, OHLCV, `second_delta_pct`, `from_previous_close_pct`, and `from_open_pct`
- `symbol_day_diagnostics.parquet`: row-level inclusion and exclusion diagnostics explaining where a symbol-day dropped out of the pipeline
- `databento_volatility_production_*_manifest.json`: machine-readable provenance, formulas, timestamps, row counts, datasets, and selection rules
- `databento_volatility_production_*.xlsx`: human-readable workbook for review and sharing

The watchlist layer can additionally emit:

- ranked watchlist CSV files
- Markdown reports
- TradingView watchlist text exports
- optional IBKR preview JSON or live-order execution inputs

### Main Entry Points

```bash
# Interactive Streamlit app
streamlit run streamlit_databento_volatility_screener.py

# Measured ops wrapper: full-history baseline outside pre-open
python scripts/measure_databento_ops_run.py --run-profile full_history --top-n 10

# Measured ops wrapper: fast reduced-scope refresh near the open
python scripts/measure_databento_ops_run.py --run-profile preopen_fast --top-n 10

# Production export bundle
python scripts/databento_production_export.py

# Watchlist generation from latest exact-named exports or a bundle
python scripts/generate_databento_watchlist.py --export-dir ~/Downloads

# Inspect latest bundle and tables
python scripts/load_databento_export_bundle.py ~/Downloads --head 3

# IBKR dry run from an existing watchlist
python scripts/execute_ibkr_watchlist.py --watchlist-csv reports/databento_watchlist_top5_pre1530.csv
```

### Required / Optional Inputs

- `DATABENTO_API_KEY` is required for the screener and production export pipeline.
- `FMP_API_KEY` is optional and used for fundamentals enrichment and fallback universe-related flows.
- `ib_insync` plus a reachable TWS or IB Gateway session are required only for `scripts/execute_ibkr_watchlist.py`.

### Default Operating Model

- Display timezone: `Europe/Berlin`
- Premarket anchor: `08:00:00 ET`
- Intraday screening window: ET-relative defaults from `databento_volatility_screener.py`
- Production open-window detail export: `15:29:00` through `15:35:59` Europe/Berlin
- Watchlist strategy: `strategy_config.py` Long-Dip defaults (`top_n=5`, laddered entries, fixed TP/SL, trailing stop)

### Recommended Ops Sequence

1. Run `full_history` outside the US pre-open window to rebuild the full-universe 30-day baseline bundle.
2. Let that baseline define the historical `selected_top20pct` symbol-day set per trade date.
3. Run `preopen_fast` near the open to reuse the latest full-history baseline and refresh only the reduced current premarket scope.
4. Generate the watchlist from the latest exports after the fast refresh, or use the Streamlit `Fast Pre-Open Pipeline` button.

Important behavior of `scripts/measure_databento_ops_run.py`:

- `--run-profile full_history` now skips immediate watchlist generation by default.
- This is intentional: the outside-pre-open baseline run is about rebuilding the heavy full-universe export, not loading the exact-named full-history Parquets back into the same process.
- If you explicitly want the wrapper to build the watchlist right after `full_history`, pass `--full-history-with-watchlist`.

### Output Artifacts

The production export pipeline writes both manifest-backed bundle artifacts and exact-named Parquet files. The most important downstream files are:

- `daily_symbol_features_full_universe.parquet`
- `premarket_features_full_universe.parquet`
- `full_universe_second_detail_open.parquet`
- `symbol_day_diagnostics.parquet`
- `databento_volatility_production_*_manifest.json`
- `databento_volatility_production_*.xlsx`

The watchlist layer can load either:

- the exact-named Parquet files in an export directory, or
- the latest manifest-backed bundle when the exact-named files are missing or corrupt.

### Related Documentation

For the full operational and technical workflow, see `docs/DATABENTO_VOLATILITY_SUITE.md`.

---

## SkippALGO Pine Script

- **Latest (v6.3.13 — Pine Script v6)**

Pine Script v6 signal engine with non-repainting core logic and intrabar alerts/labels.

### Outlook vs Forecast

| Layer | What it shows | Predictive? |
|-------|---------------|-------------|
| **Outlook (State)** | Current regime/bias snapshot per timeframe | No — descriptive |
| **Forecast (Probability)** | Calibrated probability of a defined forward outcome | Yes — gated by sample sufficiency |

### Quick Start (Pine)

1. Add `SkippALGO.pine` to your TradingView chart.
2. Start with default horizons (1m–1d) and `predBins=3`.
3. Let calibration warm up (watch sample sufficiency in Forecast rows).
4. Read **Outlook first**, then confirm with **Forecast** probabilities.

### Signal Modes

- **Intrabar (default):** `Alerts: bar close only = false` — preview alerts/labels before candle close
- **Bar-close only:** `Alerts: bar close only = true` — confirmed signals only
- **Entry presets:** Manual, Intraday, Swing — drive effective score thresholds/weights
- **Engines:** Hybrid, Breakout, Trend+Pullback, Loose
- **Score Engine (Option C):** High-quality setup scoring independent of rigid engine logic

### Key Features

- Multi-timeframe Outlook with bias, score, components (Trend/Momentum/Location)
- Forecast block with Pred(N)/Pred(1) plus calibrated P(Up)
- USI (Ultimate Stacking Indicator) trend state and entry gating
- ChoCH (Change of Character) structure detection
- Same-bar ChoCH verification (fast confirmation path)
- Early CHoCH context signals (Anticipation + Momentum Pre-CHoCH)
- Dynamic TP expansion and SL profiling
- Regime Classifier 2.0 with hysteresis (optional)
- VWT (Volume Weighted Trend) filter (optional)
- Drawdown hard gate, macro guards, MTF confirmation
- Consolidated alert dispatch (one `alert()` per bar per symbol)

### Additional Pine Scripts

| Script | Description |
|--------|-------------|
| `SkippALGO_Strategy.pine` | Strategy version with backtesting |
| `SkippALGO_Lite.pine` | Lightweight variant |
| `SkippALGO_Mid.pine` / `SkippALGO_Mid_Strategy.pine` | Mid-tier variants |
| `QuickALGO.pine` | Score+Verify optimized logic |
| `VWAP_Long_Reclaim_*.pine` | VWAP reclaim strategies (BUY/EXIT/SHORT/COVER alerts) |
| `CHOCH-*.pine` | Change-of-Character variants (fast mode with Same-Bar Verify + early context markers) |
| `USI-CHOCH.pine` | USI + CHoCH hybrid with VWAP context, BEST Bullish CHoCH, Anticipation (A↑/A↓), Momentum Pre-CHoCH (M↑/M↓), and dedicated early-signal alerts |
| `BTC 3m EV Scalper BALANCED (Harmonized).pine` | BTC scalper |

---

## Developer Guide

### Tests

```bash
# Full test suite (1 681 tests)
python -m pytest tests/ -q

# Single test
python -m pytest tests/test_production_gatekeeper.py -q

# With coverage
python -m pytest tests/ -q \
  --cov=newsstack_fmp --cov=terminal_poller --cov=terminal_export \
  --cov-report=term-missing
```

### Linting & Type Checking

```bash
# Ruff lint
ruff check newsstack_fmp/ open_prep/ terminal_*.py streamlit_terminal.py

# Mypy
mypy newsstack_fmp/ terminal_poller.py terminal_export.py

# Pylance/Pyright: 0 workspace errors (verified 28 Feb 2026)
```

Configuration is centralized in `pyproject.toml`.

### Project Structure

```
skipp-algo/
├── streamlit_terminal.py          # Real-Time News Intelligence Dashboard (19 tabs)
├── terminal_poller.py             # Polling engine (news + FMP + classification)
├── terminal_bitcoin.py            # Bitcoin data (10 sources)
├── terminal_newsapi.py            # NewsAPI.ai integration
├── terminal_spike_scanner.py      # FMP spike scanner
├── terminal_spike_detector.py     # RT spike detector
├── terminal_technicals.py         # TradingView TA
├── terminal_forecast.py           # Analyst forecasts (FMP + yfinance)
├── terminal_notifications.py      # Push notifications (Telegram/Discord/Pushover)
├── terminal_export.py             # JSONL/VisiData export + webhooks
├── terminal_feed_lifecycle.py     # Feed staleness detection + auto-recovery
├── terminal_background_poller.py  # Threaded background poll loop
├── terminal_ai_insights.py        # AI Insights engine (LLM reasoning)
├── terminal_ui_helpers.py         # UI formatting + sentiment helpers
│
├── terminal_tabs/                 # Tab rendering modules (19 tabs)
│   ├── tab_feed.py                # 📰 Live Feed tab
│   ├── tab_ai.py                  # 🤖 AI Insights tab
│   ├── tab_rankings.py            # 🏆 Rankings tab
│   ├── tab_bitcoin.py             # ₿ Bitcoin tab
│   ├── tab_*.py                   # … remaining 14 tabs
│   └── _shared.py                 # Shared tab utilities
│
├── newsstack_fmp/                 # News pipeline library
│   ├── ingest_benzinga.py         # Benzinga REST + WebSocket adapter
│   ├── ingest_benzinga_calendar.py # Benzinga calendar adapter
│   ├── ingest_benzinga_financial.py # Benzinga financial data adapter
│   ├── ingest_fmp.py              # FMP news adapter
│   ├── scoring.py                 # Impact/clarity/polarity scoring
│   ├── store_sqlite.py            # SQLite dedup store
│   ├── pipeline.py                # Ingestion pipeline orchestrator
│   ├── normalize.py               # Article normalization
│   ├── enrich.py                  # Entity + ticker enrichment
│   └── config.py                  # Pipeline configuration
│
├── open_prep/                     # Pre-open briefing pipeline
│   ├── streamlit_monitor.py       # Open-Prep Streamlit monitor
│   ├── run_open_prep.py           # Pipeline runner (17 stages)
│   ├── macro.py                   # FMP + Finnhub macro data
│   ├── news.py                    # News scoring
│   ├── realtime_signals.py        # RT signal engine
│   ├── playbook.py                # Setup classification
│   ├── outcomes.py                # Outcome tracking
│   ├── alerts.py                  # Alert configuration
│   └── watchlist.py               # Symbol watchlist management
│
├── databento_volatility_screener.py      # Core Databento screener engine + exports + Streamlit UI logic
├── streamlit_databento_volatility_screener.py # Standalone Streamlit launcher for the Databento screener
├── terminal_databento.py                 # Databento quote helpers for the main terminal and Open-Prep monitor
├── strategy_config.py                    # Long-Dip watchlist and execution defaults
│
├── tests/                         # 1 681 tests
├── scripts/                       # Automation, export, watchlist, and IBKR execution scripts
│   ├── databento_production_export.py    # Full-universe export pipeline
│   ├── databento_smoke_test.py           # Minimal end-to-end Databento smoke run
│   ├── generate_databento_watchlist.py   # Long-Dip watchlist generator
│   ├── load_databento_export_bundle.py   # Bundle/manifest loader and inspector
│   ├── execute_ibkr_watchlist.py         # IBKR dry-run / live execution bridge
│   └── run_ibkr_open_execution.py        # Higher-level runner for execution workflows
├── docs/                          # Technical docs, reviews, runbooks
├── *.pine                         # TradingView Pine Script v6
├── pyproject.toml                 # Centralized config (pytest/ruff/mypy)
├── requirements.txt               # Python dependencies
└── CHANGELOG.md                   # Full changelog
```

---

## Documentation Index

### Terminal & Operations

- [Terminal Architecture Plan](docs/BLOOMBERG_TERMINAL_PLAN.md)
- [Databento Volatility Suite Guide](docs/DATABENTO_VOLATILITY_SUITE.md)
- [Open Prep Suite — Technical Reference](docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md)
- [Open Prep Suite — Ops Quick Reference](docs/OPEN_PREP_OPS_QUICK_REFERENCE.md)
- [Open Prep Suite — Incident Runbook Matrix](docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md)
- [Open Prep Suite — Incident Runbook (One-Page)](docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md)
- [TradersPost Integration](docs/TRADERSPOST_INTEGRATION.md)
- [TradingView Strategy Guide](docs/TRADINGVIEW_STRATEGY_GUIDE.md)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md)

### Pine Script

- [Deep Technical Documentation](docs/SkippALGO_Deep_Technical_Documentation.md)
- [Deep Technical Documentation (v6.2.22)](docs/SkippALGO_Deep_Technical_Documentation_v6.2.22.md)
- [Market Structure Guide](docs/SkippALGO_Market_Structure.md)
- [SMC++ Dashboard Guide (DE)](docs/SMC_Dashboard_Long_Dip_Guide_DE.md)
- [SMC++ Dashboard Guide (EN)](docs/SMC_Dashboard_Long_Dip_Guide_EN.md)
- [Tuning Guide](docs/SkippALGO_Tuning_Guide.md)
- [Kurzfassung für Nutzer](docs/SkippALGO_Kurzfassung_Fuer_Nutzer.md)

*** Add File: /Users/steffenpreuss/Downloads/skipp-algo/docs/SMC_Dashboard_Long_Dip_Guide_DE.md
# SMC++ Dashboard Guide fuer Long-Dip Setups (DE)

## Zweck

Dieses Dokument erklaert das SMC++-Dashboard in einfachem Deutsch.
Es ist als Arbeits- und Interpretationshilfe gedacht, nicht als alleinstehendes Kaufsignal.

Wichtige Grundregel:

- Das Dashboard ist eine Ampel und Checkliste.
- Je mehr Felder zusammenpassen, desto sauberer ist ein Long-Dip-Setup.
- Eine Zone allein ist kein Einstieg.

## Kerngedanke

Das Dashboard beantwortet im Kern vier Fragen:

1. Ist der Markt strukturell eher bullish oder bearish?
2. Ist der Preis gerade in einer sinnvollen Pullback-Zone?
3. Gibt es schon Rueckeroberung und Bestätigung?
4. Sprechen Momentum, Close, EMA, ADX und Volumen eher fuer oder gegen einen Long?

## Begriffe im Dashboard

### SMC++

Der Name des Skripts.

### Trend

Die aktuelle Marktstruktur des aktiven Charts.

- Bullish: Struktur eher aufwaerts
- Bearish: Struktur eher abwaerts
- Neutral: kein sauberer Strukturvorteil

### HTF Trend

HTF steht fuer Higher Time Frame.
Das Feld zeigt, ob hoehere Zeitebenen den Trade unterstuetzen.

Beispiel:

`3:Bearish | 10:Bullish | 30:Bearish`

Das ist gemischt und fuer einen konservativen Long-Dip eher unguenstig.

### Pullback Zone

Zeigt, ob der Preis in einer Zone angekommen ist, aus der ein Dip-Bounce entstehen koennte.

Typische Zustande:

- In OB Zone
- In FVG Zone
- In OB + FVG Zone
- No Long Zone

Wichtig: Eine Zone bedeutet Beobachten, nicht Kaufen.

### Reclaim

Reclaim bedeutet, dass der Markt ein relevantes Level oder eine Zone zurueckerobert.
Fuer Longs ist das wichtig, weil es zeigt, dass Kaeufer wieder Kontrolle uebernehmen.

Positive Beispiele:

- OB Reclaimed
- FVG Reclaimed
- Internal Low Reclaimed
- Swing Low Reclaimed

Warnsignal:

- No Reclaim

### Long Setup

Der operative Zustand des Long-Setups.

Typische Stufen:

- In Zone: interessanter Bereich, aber noch kein Entry
- Armed: Setup ist vorgemerkt
- Building: Struktur baut sich auf
- Confirmed: wichtige Bestätigung liegt vor
- Ready: sauberes, fortgeschrittenes Long-Setup
- Blocked oder Invalidated: Setup ist kaputt oder unbrauchbar

### Setup Age

Wie alt ein bewaffnetes oder bestaetigtes Setup ist.

Beispiele:

- armed 2
- confirmed 1

Frische Signale sind meist interessanter als alte Signale.

### Long Visual

Die farbliche Kurzfassung des Long-Zustands.
Das Feld dient als schnelle Ampel fuer den visuellen Setup-Status.

### Close Strength

Zeigt, wie stark die aktuelle Kerze schliesst.

- Strong Close: bullischer Schluss nahe dem oberen Bereich der Range
- Weak Close: kein ueberzeugender Schluss

Fuer Long-Dips ist ein starker Schluss meist deutlich besser.

### EMA Support

Prueft, ob Preis und EMAs das Long-Setup unterstuetzen.

- OK: sauberer Rueckenwind durch EMAs
- No: kein sauberer Trend-Rueckenwind

### ADX

Der ADX misst Trendstaerke, nicht nur Richtung.
Mit der Zusatzinfo aus +DI und -DI sieht man, wer Druck macht.

Beispiel:

`30 | Bearish pressure`

Das bedeutet:

- die Bewegung hat Kraft
- aber der Druck kommt eher von der Verkaeuferseite

Das ist fuer Longs negativ.

### Rel Volume

Das relative Volumen im Vergleich zum Durchschnitt.

Beispiele:

- 1.2x: mehr Teilnahme als normal
- 0.5x: unterdurchschnittliche Teilnahme
- 0.01x: extrem schwach

Sehr niedriges Volumen macht Signale oft unzuverlaessiger.

### LTF Bias

LTF steht fuer Lower Time Frame.
Das Feld misst die Tendenz der kleineren Unterstruktur.

- hoher Wert: eher bullish
- niedriger Wert: eher bearish

### LTF Delta

Kurzfristiger Druck bzw. Volumenunterschied auf Unterzeitebene.

- positiv: eher Kaeuferdruck
- negativ: eher Verkaeuferdruck
- n/a: keine brauchbare Datenbasis

### Objects

Zeigt, wie viele OB- und FVG-Objekte sichtbar sind.

Beispiel:

`OB 19/9 | FVG 34/29`

Das ist eher Orientierung als Entry-Signal.

### Swing H/L

Zeigt Haupt- und interne Struktur-Hochs und -Tiefs.

Beispiel:

`Swing 8.23/7.89 | Int 8.03/7.92`

Die internen Levels sind oft fruehere Trigger, die Swing-Level eher die groesseren Strukturmarken.

### Long Zones

Die aktuell relevanten Long-Zonen.

Beispiel:

`OB 7.68/7.64 | FVG 7.95/7.84`

### Long Triggers

Die Rueckeroberungs- oder Bestaetigungsmarken fuer das Setup.

Beispiel:

`OB mid 7.66 | FVG fill 7.88`

### Legend

Die Farblegende des Dashboards.

- Aqua: Zone
- Orange: Armed
- Gold: Building
- Lime: Confirmed
- Green: Ready
- Red: Fail

## Beispielinterpretation eines Snapshots

Beispielwerte:

- Trend = Bullish
- HTF Trend = 3:Bearish | 10:Bullish | 30:Bearish
- Pullback Zone = In FVG Zone
- Reclaim = No Reclaim
- Setup Age = n/a
- Long Visual = In Zone
- Close Strength = Weak Close
- EMA Support = No
- ADX = 30 | Bearish pressure
- Rel Volume = 0.01x
- LTF Bias = 0%
- LTF Delta = n/a

Einfache Lesart:

- Positiv: Der Preis ist in einer moeglichen Reaktionszone.
- Negativ: Reclaim fehlt, Schluss ist schwach, EMA-Support fehlt, der Druck ist bearish, Volumen ist fast nicht vorhanden.

Kurzfazit:

> Interessante Long-Zone ja, aber noch keine saubere Long-Bestaetigung. Eher warten als einsteigen.

## Was man mit diesem Zustand nicht tun sollte

- Nicht nur wegen `In FVG Zone` oder `In OB Zone` kaufen.
- Nicht gegen klaren Verkaeuferdruck blind long gehen.
- Nicht `Trend = Bullish` ueberbewerten, wenn HTF, Reclaim, Close und EMA nicht mitziehen.
- Nicht bei extrem schwachem Volumen aggressiv einsteigen.
- Nicht ohne klares Invalidations-Level handeln.
- Nicht den Live-Eindruck einer Zone mit einer bestaetigten Struktur verwechseln.

## Worauf man fuer einen Long-Dip warten sollte

Die saubere Reihenfolge ist meistens:

1. Preis kommt in eine sinnvolle Zone.
2. Ein Reclaim erscheint.
3. Das Long Setup wird Armed oder Building.
4. Spaeter folgt Confirmed oder Ready.
5. Close, EMA, ADX und Volumen sprechen nicht mehr klar dagegen.

## Drei Stufen fuer das Dashboard

### 1. Beobachten

Typisches Bild:

- Trend bullish oder wenigstens nicht bearish
- Preis in OB- oder FVG-Zone
- Reclaim noch nicht vorhanden
- Long Visual noch In Zone

Bedeutung:

> Interessanter Bereich, aber noch kein Beweis fuer uebernehmende Kaeufer.

### 2. Vorbereiten

Typisches Bild:

- Reclaim ist vorhanden
- Long Setup wird Armed oder Building
- Close Strength verbessert sich
- EMA Support wird besser
- LTF Bias kippt nach oben

Bedeutung:

> Das Setup wird brauchbar, aber ist noch nicht maximal sauber.

### 3. Einstieg

Typisches Bild:

- Trend bullish
- Reclaim vorhanden
- Long Setup ist Confirmed oder Ready
- Long Visual ist Confirmed oder Long Ready
- Strong Close
- EMA Support OK
- ADX nicht bearish pressure
- Rel Volume nicht tot

Bedeutung:

> Zone, Rueckeroberung, Struktur und Filter passen jetzt deutlich besser zusammen.

## Ampel fuer den Long-Dip

### Gruen

- Trend bullish
- HTF mehrheitlich bullish oder mindestens nicht klar gegen den Trade
- Pullback Zone aktiv
- Reclaim vorhanden
- Long Setup Confirmed oder Ready
- Strong Close
- EMA Support OK
- ADX nicht bearish pressure
- Rel Volume mindestens brauchbar
- LTF Bias und LTF Delta positiv oder neutral-stuetzend

### Gelb

- Trend neutral bis leicht bullish
- Zone aktiv
- erster Reclaim oder frueher Strukturwechsel sichtbar
- Long Setup Armed oder Building
- Volumen und LTF-Daten noch nicht ideal

### Rot

- No Reclaim
- Weak Close
- EMA Support No
- ADX bearish pressure
- Volumen extrem schwach
- HTF klar gegen den Trade
- nur In Zone, aber noch keine Bestätigung

## Fuenf-Punkte-Checkliste vor einem Long-Dip

1. Trend bullish?
2. Preis in einer sinnvollen OB- oder FVG-Zone?
3. Reclaim vorhanden?
4. Long Setup Confirmed oder Ready?
5. Close, EMA, ADX und Volumen sprechen nicht dagegen?

Wenn davon nur ein oder zwei Punkte passen, ist es meist zu frueh.

## Einfache Wenn-Dann-Regel

### Kein Long

Wenn:

- Reclaim = No Reclaim
- oder Close Strength = Weak Close
- oder EMA Support = No
- oder ADX = Bearish pressure

Dann:

- kein sauberer Long-Dip-Entry

### Interessant, aber noch frueh

Wenn:

- Preis in Zone
- Reclaim vorhanden
- Long Setup = Armed oder Building

Dann:

- Setup beobachten und Trigger planen, aber nicht hetzen

### Sauberer Long-Dip

Wenn:

- Trend bullish
- Zone aktiv
- Reclaim vorhanden
- Long Setup = Confirmed oder Ready
- Close Strength = Strong Close
- EMA Support = OK

Dann:

- wird der Long-Dip deutlich interessanter

## 1-Zeilen-Regel

Long-Dip nur traden, wenn:

**Trend bullish + Preis in OB/FVG-Zone + Reclaim da + Long Setup Confirmed oder Ready + Strong Close + EMA Support OK**

## Kurzform fuer den Bildschirm

- Zone da?
- Reclaim da?
- Setup Confirmed oder Ready?
- Strong Close?
- EMA, ADX und Volumen nicht gegen dich?

Wenn mehrere Antworten Nein sind, ist Warten oft die bessere Entscheidung.

*** Add File: /Users/steffenpreuss/Downloads/skipp-algo/docs/SMC_Dashboard_Long_Dip_Guide_EN.md
# SMC++ Dashboard Guide for Long-Dip Setups (EN)

## Purpose

This document explains the SMC++ dashboard in plain English.
It is meant as an interpretation and workflow guide, not as a standalone buy signal.

Core rule:

- The dashboard is a traffic light and checklist.
- The more fields align, the cleaner the long-dip setup.
- A zone by itself is not an entry.

## Core Idea

The dashboard mainly answers four questions:

1. Is the market structure currently bullish or bearish?
2. Is price sitting inside a meaningful pullback zone?
3. Do we already have reclaim and confirmation?
4. Are close quality, EMA support, ADX, volume, and lower-timeframe pressure helping or hurting the long?

## Dashboard Terms

### SMC++

The name of the script.

### Trend

The active market structure on the current chart.

- Bullish: structure leans upward
- Bearish: structure leans downward
- Neutral: no clear structural edge yet

### HTF Trend

HTF means Higher Time Frame.
This field checks whether larger timeframes support the trade.

Example:

`3:Bearish | 10:Bullish | 30:Bearish`

That is mixed and not ideal for a conservative long-dip.

### Pullback Zone

Shows whether price has reached an area where a dip-bounce could develop.

Typical states:

- In OB Zone
- In FVG Zone
- In OB + FVG Zone
- No Long Zone

Important: a zone means watch, not buy.

### Reclaim

Reclaim means price has recovered an important level or zone.
For longs, this matters because it shows buyers are taking control back.

Positive examples:

- OB Reclaimed
- FVG Reclaimed
- Internal Low Reclaimed
- Swing Low Reclaimed

Warning sign:

- No Reclaim

### Long Setup

The operating state of the long setup.

Typical stages:

- In Zone: interesting area, but not an entry yet
- Armed: setup is being tracked
- Building: structure is improving
- Confirmed: key confirmation is in place
- Ready: clean, advanced long setup
- Blocked or Invalidated: setup is broken or unusable

### Setup Age

How old an armed or confirmed setup is.

Examples:

- armed 2
- confirmed 1

Fresh setups are usually better than old ones.

### Long Visual

The visual summary of the long-state.
This is the quick traffic-light version of the setup status.

### Close Strength

Shows how strong the current candle closed.

- Strong Close: bullish close near the upper part of the range
- Weak Close: not convincing

For long-dips, a strong close is usually much better.

### EMA Support

Checks whether price and EMAs support the long idea.

- OK: clean EMA tailwind
- No: no clean trend support

### ADX

ADX measures trend strength, not only direction.
Combined with +DI and -DI, it also shows who is applying pressure.

Example:

`30 | Bearish pressure`

This means:

- the move has strength
- but the pressure currently comes from sellers

That is negative for longs.

### Rel Volume

Relative volume compared to average volume.

Examples:

- 1.2x: more participation than normal
- 0.5x: below-average participation
- 0.01x: extremely weak

Very low volume often makes signals less reliable.

### LTF Bias

LTF means Lower Time Frame.
This field measures the tendency of the smaller internal structure.

- higher value: more bullish
- lower value: more bearish

### LTF Delta

Short-term pressure or volume imbalance on the lower timeframe.

- positive: buyer pressure
- negative: seller pressure
- n/a: no useful data base

### Objects

Shows how many OB and FVG objects are visible.

Example:

`OB 19/9 | FVG 34/29`

This is more orientation than entry logic.

### Swing H/L

Shows major and internal structure highs and lows.

Example:

`Swing 8.23/7.89 | Int 8.03/7.92`

Internal levels are often earlier triggers, while swing levels are the larger structural references.

### Long Zones

The currently relevant long zones.

Example:

`OB 7.68/7.64 | FVG 7.95/7.84`

### Long Triggers

The reclaim or confirmation levels for the setup.

Example:

`OB mid 7.66 | FVG fill 7.88`

### Legend

The dashboard color legend.

- Aqua: Zone
- Orange: Armed
- Gold: Building
- Lime: Confirmed
- Green: Ready
- Red: Fail

## Example Snapshot Interpretation

Example values:

- Trend = Bullish
- HTF Trend = 3:Bearish | 10:Bullish | 30:Bearish
- Pullback Zone = In FVG Zone
- Reclaim = No Reclaim
- Setup Age = n/a
- Long Visual = In Zone
- Close Strength = Weak Close
- EMA Support = No
- ADX = 30 | Bearish pressure
- Rel Volume = 0.01x
- LTF Bias = 0%
- LTF Delta = n/a

Simple read:

- Positive: price is inside a potential reaction zone.
- Negative: no reclaim, weak close, no EMA support, bearish pressure, and almost no volume.

Short conclusion:

> Interesting long zone, but not a clean long confirmation yet. Waiting is better than entering.

## What You Should Not Do in This State

- Do not buy only because price is inside an FVG or OB zone.
- Do not blindly go long into clear seller pressure.
- Do not overrate `Trend = Bullish` when HTF, reclaim, close, and EMA do not agree.
- Do not enter aggressively on extremely weak volume.
- Do not trade without a clear invalidation level.
- Do not confuse a live zone touch with confirmed structure.

## What to Wait For in a Long-Dip

The cleaner sequence is usually:

1. Price reaches a meaningful zone.
2. A reclaim appears.
3. The long setup becomes Armed or Building.
4. Later it becomes Confirmed or Ready.
5. Close, EMA, ADX, and volume stop arguing against the trade.

## Three Dashboard Phases

### 1. Watch

Typical picture:

- Trend bullish or at least not bearish
- Price in an OB or FVG zone
- No reclaim yet
- Long Visual still In Zone

Meaning:

> Interesting area, but no proof yet that buyers are taking control.

### 2. Prepare

Typical picture:

- Reclaim appears
- Long Setup becomes Armed or Building
- Close Strength improves
- EMA Support improves
- LTF Bias starts turning up

Meaning:

> The setup is becoming usable, but it is not fully clean yet.

### 3. Entry

Typical picture:

- Trend bullish
- Reclaim present
- Long Setup is Confirmed or Ready
- Long Visual is Confirmed or Long Ready
- Strong Close
- EMA Support OK
- ADX is not bearish pressure
- Relative volume is not dead

Meaning:

> Zone, reclaim, structure, and filters now align much better.

## Traffic-Light View for Long-Dips

### Green

- Trend bullish
- HTF mostly bullish or at least not clearly against the trade
- Pullback Zone active
- Reclaim present
- Long Setup Confirmed or Ready
- Strong Close
- EMA Support OK
- ADX not bearish pressure
- Relative volume at least acceptable
- LTF Bias and LTF Delta positive or neutral-supportive

### Yellow

- Trend neutral to mildly bullish
- Zone active
- first reclaim or early internal shift visible
- Long Setup Armed or Building
- volume and LTF data not ideal yet

### Red

- No Reclaim
- Weak Close
- EMA Support No
- ADX bearish pressure
- extremely weak volume
- HTF clearly against the trade
- only In Zone, but no confirmation yet

## Five-Point Checklist Before a Long-Dip

1. Is trend bullish?
2. Is price inside a meaningful OB or FVG zone?
3. Is reclaim present?
4. Is the long setup Confirmed or Ready?
5. Are close, EMA, ADX, and volume not fighting the trade?

If only one or two of these are true, it is usually too early.

## Simple If-Then Rule

### No Long

If:

- Reclaim = No Reclaim
- or Close Strength = Weak Close
- or EMA Support = No
- or ADX = Bearish pressure

Then:

- it is not a clean long-dip entry

### Interesting, But Early

If:

- price is in the zone
- reclaim is present
- Long Setup = Armed or Building

Then:

- watch the setup and define triggers, but do not rush

### Clean Long-Dip

If:

- Trend bullish
- zone active
- reclaim present
- Long Setup = Confirmed or Ready
- Close Strength = Strong Close
- EMA Support = OK

Then:

- the long-dip becomes much more attractive

## One-Line Rule

Only trade a long-dip when:

**Trend is bullish + price is in an OB/FVG zone + reclaim is present + Long Setup is Confirmed or Ready + Close is strong + EMA Support is OK**

## Screen-Side Short Version

- Zone active?
- Reclaim present?
- Setup Confirmed or Ready?
- Strong Close?
- EMA, ADX, and volume not against you?

If several answers are No, waiting is often the better choice.

### Architecture & Planning

- [RFC v6.4 — Adaptive Zero-Lag + Regime Classifier](docs/RFC_v6.4_AdaptiveZeroLag_RegimeClassifier.md)
- [Roadmap Enhancements](docs/SkippALGO_Roadmap_Enhancements.md)

### Reviews & Reports

- [Comprehensive Audit Report](docs/AUDIT_REPORT_Comprehensive.md)
- [Functional Test Matrix](docs/FUNCTIONAL_TEST_MATRIX.md)
- [TradingView Test Checklist](docs/TRADINGVIEW_TEST_CHECKLIST.md)

### Changelog

- [Full Changelog](CHANGELOG.md)

---

## License

This project is distributed under the Mozilla Public License 2.0 (see source headers).

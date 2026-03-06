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
- It does **not** execute orders or place trades on behalf of users.
- Users remain solely responsible for their own investment decisions, risk management, and regulatory compliance.

---

## Table of Contents

- [Real-Time News Intelligence Dashboard](#real-time-news-intelligence-dashboard)
- [Open-Prep Pipeline](#open-prep-pipeline)
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
├── tests/                         # 1 681 tests
├── scripts/                       # VisiData launchers, export scripts
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
- [Tuning Guide](docs/SkippALGO_Tuning_Guide.md)
- [Kurzfassung für Nutzer](docs/SkippALGO_Kurzfassung_Fuer_Nutzer.md)

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

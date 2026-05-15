# SkippALGO

Pine Script v6 Signal Engine · Real-Time News Intelligence Dashboard · Pre-Open Briefing Pipeline

SkippALGO is a modular trading intelligence platform combining three operator-facing systems plus two implementation layers:

1. **SkippALGO Pine Script** — non-repainting signal engine with a decision-first HUD plus Lite Outlook and Forecast panels for TradingView.
2. **Real-Time News Intelligence Dashboard** — an AI-supported **Research & Monitoring Terminal** with 11 active top-level tabs for **News Intelligence + Alerting** and operational market monitoring.
3. **Open-Prep Pipeline** — automated pre-open briefing system with ranked candidates, macro context, and structured trade cards.
4. **ML Layer (C10)** — probability, calibration, stacking, and drift scaffolding for family-level setup prediction.
5. **RL Execution Layer (C12)** — execution/sizing scaffolding with deterministic baselines, safety rails, and optional PPO/SAC backends.

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

## Local Python setup

Use a repo-local `.venv` so VS Code tasks, the Testing panel, and the Python
extension all resolve the same interpreter.

Supported bootstrap paths:

```bash
# macOS / Linux (and Git Bash on Windows)
SKIPP_VENV=.venv ./scripts/bootstrap_venv.sh

# Windows PowerShell (manual fallback; no tracked bootstrap_venv.ps1 is shipped)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The tracked shell bootstrap script creates (or reuses) a venv, installs every
runtime + test dependency from `requirements.txt`, and verifies that the
provider modules used by the terminal (`databento`, `tradingview_ta`, `httpx`,
…) are importable. The PowerShell fallback above gives Windows users the same
repo-local `.venv` layout even though there is no tracked `bootstrap_venv.ps1`
in this repository.

Optional GPU acceleration for the Open-Prep feature-importance loop is kept in
`requirements-gpu.txt`. On a CUDA-capable self-hosted runner (for example the
local RTX-based Actions runner), install that file and set
`OPEN_PREP_FI_BACKEND=gpu` to force the CuPy backend.

If you use VS Code, point the Python extension and the Testing panel at the
repo-local `.venv` interpreter so the editor, tasks, and terminal runs stay in
sync.

> **Why a script and not `pip install -e .`?** `pyproject.toml` only declares
> the optional `vol-regime` extra; runtime dependencies live exclusively in
> `requirements.txt`. A venv created via `pip install -e .` is silently
> incomplete and you will discover missing packages at import time.

### TradingView Automation

This repo now includes a small Playwright-based TradingView automation layer under `automation/tradingview/` for repeatable script open, save, publish, and settings validation flows.

Setup:

```bash
npm install
npx playwright install chromium
```

Create a reusable authenticated storage state:

```bash
npx tsx scripts/create_tradingview_storage_state.ts \
  --out automation/tradingview/auth/storage-state.json
```

The capture step now validates that the saved state actually looks authenticated and that the active page is a TradingView chart. If it still detects an anonymous session or sign-in page, it fails instead of writing a misleading storage-state file. In non-interactive runs it waits and polls for a real logged-in chart session instead of immediately failing on the old Enter prompt path.

If TradingView still does not persist enough auth state into `storage-state.json`, use a persistent Chromium profile instead:

```bash
npm run tv:profile-login
TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile" npm run tv:preflight
TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile" npm run tv:publish-micro-library
```

In that mode the automation reuses the browser profile directory directly instead of relying only on exported storage-state heuristics.

Run the shared validation and release jobs:

```bash
npm run tv:preflight
npm run tv:preflight:smc-mainline
npm run tv:preflight:decision-first
npm run tv:publish-micro-library
```

The canonical SMC TradingView gate is `npm run tv:preflight:smc-mainline`.
It validates the active mainline path `SMC_Core_Engine.pine` +
`SMC_Dashboard.pine` + `SMC_Long_Strategy.pine` against the product-cut
manifest.
Automation evidence snapshots live under `automation/tradingview/reports/`.
Regenerate fresh mainline evidence locally with
`npm run tv:preflight:smc-mainline` before relying on a stored report.

Product-cut reference docs:

- `docs/smc-mainline-setup-runbook.md` — canonical setup path for Core + Dashboard + Strategy
- `docs/smc-lite-pro-product-cut.md`
- `docs/TRADINGVIEW_STRATEGY_GUIDE.md`
- `docs/smc-validation-status.md`

The TradingView publish flow is fail-closed: reopening the published script must resolve the exact script identity from canonical editor context, version evidence must come from exact script-bound version context, and body-level version text is retained only as diagnostic fallback. The local publish contract also requires the generated contiguous alias block to appear exactly once in the core consumer. The legacy `scripts/99_full_release.ts` path is intentionally blocked.

Required environment variables for automation jobs:

- `TV_STORAGE_STATE`
- `TV_PERSISTENT_PROFILE_DIR` (optional alternative to `TV_STORAGE_STATE`)
- `TV_CHART_URL` (optional, defaults to TradingView chart)
- `TV_LOGIN_URL` (optional, defaults to TradingView sign-in)
- `TV_HEADLESS` (optional)
- `TV_TIMEOUT_MS` (optional)

---

## Academic Grounding

The SMC stack builds on published evidence for ICT / Smart-Money methods —
not on anecdotal YouTube claims. The following peer-reviewed works are
required reading for contributors and are consulted whenever scorer
weights, calibration logic, or family priorities change:

- **Friday et al. (2026)** — *FVG + Order Blocks + Hurst-Exponent
  classifier* → 94.97% entry accuracy on BTC/USDT.
  [IEEE Access, DOI 10.1109/ACCESS.2026.3517233](https://ieeexplore.ieee.org/document/11389759/).
  Relevance: motivates our OB and FVG prioritization; basis for the
  Hurst-augmented FVG quality filter on the Q3 backlog.
- **Parekh & Heller (2026)** — *ICT concepts in Pine Script v5* →
  +11pp win-rate improvement vs. baseline.
  [JSE DOI 10.64804/y4pjsg07](https://j.snerds.org/index.php/jse/article/view/132).
  Relevance: direct precursor to the `SMC_Core_Engine` architecture.
- **Hammer & Patel (2025)** — *ICT session filters (RTH / ETH)* →
  significant drawdown reduction in equity markets.
  [JSE DOI 10.64804/37pe1x85](https://34.172.72.90/index.php/jse/article/view/77).
  Relevance: justifies the session-aware calibration planned in
  measurement Phase F2. The HTF trend stack follows the ICT-standard
  3-layer hierarchy (4H / 1D / 1W) with an adaptive IPDA range,
  consistent with Hammer & Patel's session-filter findings
  (see `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`).

**Our contribution on top:** calibration (Brier / smECE), Bayesian
smoothing of family weights, and an explicit Trust Tier — none of which
appear in the works above, but all of which are state-of-the-art for
*honest uncertainty communication* (cf.
[Rossellini et al. 2025, arXiv:2502.19851](https://arxiv.org/abs/2502.19851)
and [Błasiok & Nakkiran 2023, smECE, arXiv:2309.12236](https://arxiv.org/abs/2309.12236)).

We intentionally do **not** claim the headline accuracies from these
papers as our own — our numbers are reported live in the calibration
report and the Pine dashboard, on US-equity intraday data.

> **See also:** the public-facing summary of this section lives on the
> [Landing v0 draft](marketing/landing_v0.md) (rendered:
> [`marketing/landing_v0.html`](marketing/landing_v0.html)) and the
> three curated input bundles in
> [`marketing/tradingview_indicator_templates.md`](marketing/tradingview_indicator_templates.md).
> The Landing page is **not yet public** — pricing must land in Q4 first
> (Plan §3.4).

---

## Table of Contents

- [Academic Grounding](#academic-grounding)
- [Real-Time News Intelligence Dashboard](#real-time-news-intelligence-dashboard)
- [Open-Prep Pipeline](#open-prep-pipeline)
- [Databento Volatility Suite](#databento-volatility-suite)
- [Machine Learning Layer](#machine-learning-layer-c10)
- [RL Execution Layer](#rl-execution-layer-c12)
- [SkippALGO Pine Script](#skippalgo-pine-script)
- [Developer Guide](#developer-guide)
- [Documentation Index](#documentation-index)

---

## Real-Time News Intelligence Dashboard

A self-hosted, AI-supported financial intelligence dashboard built with Streamlit. It serves as a **Research & Monitoring Terminal** for **News Intelligence + Alerting** and **Workflow/Decision Support**. It aggregates news, market data, sentiment, and technical analysis from multiple providers into a single unified interface.

### Architecture

The terminal is composed of a central UI driver plus dedicated provider,
polling, export, and tab-rendering modules:

```text
┌──────────────────────────────────────────────────────────────────┐
│                    streamlit_terminal.py                         │
│              (main UI driver · 11 top-level tabs)                │
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
│  │ terminal_tabs/  (tab modules + subordinate views)           │ │
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
| ------ | ----- | ------- |
| `streamlit_terminal.py` | ~4 700 | Main Streamlit UI — 11 top-level tabs, sidebar, polling orchestration, alert evaluation |
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
| `terminal_tabs/` | ~2 300 | Tab rendering modules plus subordinate / shared tab views |
| `newsstack_fmp/` | ~2 500 | News pipeline — Benzinga adapters (REST, WS, calendar, financial), FMP adapter, SQLite store, scoring, enrichment |

### Tabs Overview (11 active top-level tabs)

| # | Tab | Description |
| - | --- | ----------- |
| 1 | 🏆 **Rankings** | Symbol-level ranking and cross-signal prioritization across the current feed |
| 2 | 🎯 **Actionable** | High-conviction items filtered from the live feed for operator review |
| 3 | 🧠 **AI Insights** | LLM-supported reasoning over live feed and enrichment context |
| 4 | 🏗️ **Segments** | News grouped by event category with drill-down by segment |
| 5 | 🔮 **Outlook** | Today and next-trading-day macro / regime summary |
| 6 | 📰 **Live Feed** | Real-time Benzinga + FMP news with search, filters, and badge semantics |
| 7 | ₿ **Bitcoin** | BTC quote, technicals, sentiment, and crypto-mover surfaces |
| 8 | ⚡ **Alerts** | Alert builder, firing log, and operational alert controls |
| 9 | 📊 **Data Table** | Export-oriented full feed table with enrichment columns |
| 10 | 📜 **Signal Replay** | Historical replay / outcome inspection for signal review |
| 11 | 🩺 **Provider Health** | Provider status, freshness, and health diagnostics |

Some legacy surfaces such as movers, spikes, and provider-specific diagnostics
now live as sections or subordinate views inside these active top-level tabs
instead of separate primary tabs.

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
| -------- | --------------- | -------- |
| **Benzinga** | `BENZINGA_API_KEY` | News (REST + WebSocket), calendar (ratings, earnings, economics, dividends, splits, IPOs, guidance, retail), financial data, delayed quotes, movers |
| **FMP** | `FMP_API_KEY` | Quotes, sector performance, economic calendar, gainers/losers/actives, crypto, analyst targets, company profiles, insider transactions (US) |
| **Unusual Whales** *(DEPRECATED 2026-05-12; sunset 2026-Q3)* | `UNUSUAL_WHALES_API_KEY` | **Decommissioned** — UOA flow replaced by self-hosted Databento OPRA UOA detector (`newsstack_fmp/opra_uoa.py`); remaining adapters (darkpool, spot-GEX, market-tide, insider-transactions, news-headlines) are dormant (return `[]` after 401). Safe to remove from prod secrets after `2026-Q3-uw-review` (deadline 2026-08-31, owner: ops). See `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` §13. |
| **NewsAPI.ai** | `NEWSAPI_AI_KEY` | Event Registry article search, live article feed, event search, breaking events, trending concepts, NLP sentiment scoring |
| **TradingView** | *(none — scraper)* | Technical analysis (oscillators, moving averages) for equities and crypto |
| **Databento** | `DATABENTO_API_KEY` | Historical + reference market data (OHLCV, corporate actions, identifier state) |
| **yfinance** | *(none — free)* | Fallback historical OHLCV, market cap, company info |
| **Finnhub** | `FINNHUB_API_KEY` | Social sentiment for crypto |

> **Removed providers / paths** (v3 audit 2026-04-30): FMP `fear-and-greed`
> and FMP `short-interest` enrichment paths have been retired (PRs #1962,
> #1964); the monitor insider-feed has been swapped from Benzinga onto
> FMP + Unusual Whales (#1966).

### Quick Start (Terminal)

```bash
# 1. Clone and install
git clone https://github.com/skippALGO/skipp-algo.git
cd skipp-algo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Create `.env` manually
# (the repo does not currently ship a tracked `.env.example`)
# Required:
#   BENZINGA_API_KEY=your_key
# Optional (enables more tabs / surfaces):
#   FMP_API_KEY=your_key
#   NEWSAPI_AI_KEY=your_key
#   UNUSUAL_WHALES_API_KEY=your_key   # DEPRECATED 2026-05-12 (UOA replaced by Databento OPRA, sunset 2026-Q3 — see CHANGELOG)
#   FINNHUB_API_KEY=your_key
#   DATABENTO_API_KEY=your_key        # historical + reference market data

# 3. Run
streamlit run streamlit_terminal.py
```

The dashboard opens at `http://localhost:8501` with a dark theme.

### Configuration

**Environment variables** (`.env` file or shell):

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `BENZINGA_API_KEY` | Yes | Benzinga API key for primary news feed |
| `FMP_API_KEY` | No | FMP key for quotes, calendar, sector data, crypto, insider transactions |
| `UNUSUAL_WHALES_API_KEY` | No | **DEPRECATED 2026-05-12** — Unusual Whales Bearer token. UOA flow replaced by self-hosted Databento OPRA UOA detector (PRs #2155/#2157/#2163); remaining adapters dormant. Sunset target: 2026-Q3 (deadline 2026-08-31, owner: ops). Safe to leave unset; see `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` §13. |
| `NEWSAPI_AI_KEY` | No | NewsAPI.ai key for Event Registry search/feed fallback, breaking/trending/NLP tabs |
| `DATABENTO_API_KEY` | No | Databento API key for historical OHLCV + reference market data (corporate actions, identifier state) |
| `FINNHUB_API_KEY` | No | Finnhub key for crypto social sentiment |
| `TERMINAL_NOTIFY_ENABLED` | No | `1` to enable push notifications |
| `TERMINAL_NOTIFY_MIN_SCORE` | No | Minimum news score for notification (default: `0.85`) |
| `TERMINAL_NOTIFY_THROTTLE_S` | No | Throttle window in seconds (default: `600`) |
| `TERMINAL_WEBHOOK_URL` | No | Webhook URL for alert dispatch |
| `TERMINAL_POLL_INTERVAL` | No | Poll interval in seconds (default: `15`) |
| `TERMINAL_TOPICS` | No | Comma-separated topic filter for Benzinga |

> **Live NewsAPI.ai behavior**: the pollers and generator snapshot prefer
> `minuteStreamArticles`, persist `recentActivityArticlesNewsUpdatesAfterUri`
> when available, and fall back to timestamp/search polling when the cursor
> is older than the stream window. The shared `httpx` timeout was bumped
> from 20s to 45s in v3 P-7 (#1961) to reduce false-negative timeouts on
> Event Registry feeds.

**Optional Databento Reference Knobs**:

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `DATABENTO_REFERENCE_CACHE_DIR` | No | Cache directory for corporate-actions alias and identifier state |
| `DATABENTO_REFERENCE_CACHE_TTL_SECONDS` | No | Success TTL for cached Databento reference state (default: `21600`) |
| `DATABENTO_REFERENCE_FAILURE_TTL_SECONDS` | No | Backoff TTL after reference subscription / transport failures (default: `86400`) |
| `DATABENTO_REFERENCE_EVENT_RISK_WINDOW_DAYS` | No | Lookback window for folding recent identifier changes into `event_risk` (default: `14`) |

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
- `ib_async` plus a reachable TWS or IB Gateway session are required only for `scripts/execute_ibkr_watchlist.py`. The repo migrated from the unmaintained `ib_insync` to `ib_async` in v3 P-8 (#1955) — the import surface is a drop-in swap, but new contributors must depend on `ib_async>=2.1.0` (already pinned in `requirements.txt`).

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

## Machine Learning Layer (C10)

`ml/` contains the family-level probability layer that sits downstream of the
SMC scoring vocabulary. The always-on path is pure NumPy
(`LogisticBaseline`), while heavier backends are optional and live behind
`requirements-ml.txt`.

Current implemented surfaces include:

- calibration (`PlattCalibrator`, `IsotonicCalibrator`, conformal wrappers)
- constrained stacking (`ml/stacking/meta_learner.py`)
- probability drift evaluation (`MLDriftDetector`, PSI trend helpers)
- thread-safe inference registry (`ml/inference/family_predictor.py`)

Start here:

- `ml/README.md`
- `docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`
- `tests/test_ml_layer_smoke.py`
- `tests/test_conformal_coverage.py`
- `tests/test_meta_learner_smoke.py`

Optional heavy backends:

```bash
pip install -r requirements-ml.txt
```

---

## RL Execution Layer (C12)

`rl/` contains execution/sizing scaffolding that sits downstream of the
signal + ML stack. The deterministic baseline path is NumPy-first
(TWAP/VWAP slicers, Almgren-Chriss calibrator, execution simulator,
hard-constraint safety layer); PPO/SAC agents are optional and gated behind
`requirements-rl.txt`.

Current implemented surfaces include:

- deterministic baselines (`rl/baselines/twap.py`, `rl/baselines/vwap.py`)
- optional agents (`rl/agents/ppo_slicer.py`, `rl/agents/sac_sizer.py`)
- safety guardrails (`rl/safety.HardConstraintLayer`)
- C12.1 extensions (`rl/extensions.py` for CVaR, adversarial replay,
  walk-forward, and constraint-hit logs)

Start here:

- `rl/README.md`
- `docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md`
- `scripts/check_c12_trigger.py`
- `tests/test_rl_execution_smoke.py`
- `tests/test_rl_extensions_c12_1.py`

Optional heavy backends:

```bash
pip install -r requirements-rl.txt
```

---

## SkippALGO Pine Script

- **Latest (v6.3.13 — Pine Script v6)**

Pine Script v6 signal engine with non-repainting core logic and intrabar alerts/labels.

### Outlook vs Forecast

| Layer | What it shows | Predictive? |
| ----- | ------------- | ----------- |
| **Outlook (State)** | Current regime/bias snapshot per timeframe | No — descriptive |
| **Forecast (Probability)** | Calibrated probability of a defined forward outcome | Yes — gated by sample sufficiency |

### Quick Start (Pine)

1. Add the canonical SMC mainline stack to your TradingView chart:
  - `SMC_Core_Engine.pine`
  - `SMC_Dashboard.pine`
  - `SMC_Long_Strategy.pine`
2. Start with default horizons (1m–1d) and `predBins=3`.
3. Let calibration warm up (watch sample sufficiency in Forecast rows).
4. Read **Outlook first**, then confirm with **Forecast** probabilities.

For the reproducible setup and publish path, see
`docs/smc-mainline-setup-runbook.md` and `docs/README.md`.

### Signal Modes

- **Realtime (default):** `Alert mode = Realtime` — preview alerts and labels before candle close
- **Bar-close only:** `Alert mode = Bar Close` — confirmed signals only
- **Entry presets:** Manual, Intraday, Swing — drive effective score thresholds/weights
- **Engines:** Hybrid, Breakout, Trend+Pullback, Loose
- **Score Engine (Option C):** High-quality setup scoring independent of rigid engine logic

### Repaint / Backtest Note

- HTF `request.security()` reads in the SMC core use `lookahead = barmerge.lookahead_off` so higher-timeframe context stays bound to completed HTF bars.
- The non-aggressive lifecycle path in the core advances on confirmed bars, and [SMC_Long_Strategy.pine](SMC_Long_Strategy.pine) stages orders with `process_orders_on_close = true`.
- In practice that means the default backtest path is bar-close driven; only the explicit aggressive live mode can consume realtime preview behavior.

### Key Features

- Decision header with Action, Trade Threshold, Position, Last Action, Why now, and Main risk
- Lite Outlook panel with TF, Bias, Strength, and State note
- Lite Forecast panel with Stable Forecast, Early Forecast, Evidence, and Risk Hint
- USI (Ultimate Stacking Indicator) trend state and entry gating
- ChoCH (Change of Character) structure detection
- Same-bar ChoCH verification (fast confirmation path)
- Early CHoCH context signals (Anticipation + Momentum Pre-CHoCH)
- Dynamic TP expansion and SL profiling
- Regime Classifier 2.0 with hysteresis (optional)
- VWT (Volume Weighted Trend) filter (optional)
- Drawdown hard gate, macro guards, MTF confirmation
- Consolidated alert dispatch (one `alert()` per bar per symbol)

### Recent SMC++ Changes

- Long-dip watchlist, strict-flow sequencing, and invalidation were hardened so overlapping OB/FVG setups keep a generic watchlist stage but source-specific reclaim, backing-zone tracking, and invalidation.
- TradingView lifecycle presets now use latched event states for better live-bar reliability, and priority-mode dynamic alerts no longer let weaker lifecycle messages suppress same-bar invalidation.
- Volume and lower-timeframe quality handling now degrade more explicitly by separating current-bar volume health, feed quality, LTF price context, and LTF volume context.
- OB profile alignment, value-area logic, and empty-profile handling were tightened, and the dashboard now exposes the active microstructure profile plus stacked modifiers more clearly.

### SMC++ Long-Dip Layer Model

The long-dip engine now uses a four-layer model so the same confluence is not counted multiple times across lifecycle, gates, scores, and upgrade tiers.

1. Lifecycle
  `Armed -> Building -> Confirmed -> Ready -> Entry Best -> Entry Strict`
2. Hard Gates
  `setup_hard_gate_ok` for touch hygiene, `trade_hard_gate_ok` for session or microstructure or headroom release, and `environment_hard_gate_ok` for market plus volatility regime.
3. Quality
  `context_quality_score` and `context_quality_gate_ok` provide the context axis. `Quality Clean` stays diagnostic and does not advance lifecycle.
4. Upgrade Modules
  Acceleration, SD, volatility context, stretch context, DDVI, and strict HTF or LTF modules only upgrade a setup that is already Ready.

This keeps Ready as the main handoff point: lifecycle must be valid, hard gates must release, context quality must pass, and only then can Best or Strict add their own upgrade modules.

### Representative tracked Pine entry points

| Script | Description |
| ------ | ----------- |
| `SMC_Core_Engine.pine` | Canonical core consumer for the active SMC mainline |
| `SMC_Dashboard.pine` | Decision-first dashboard / HUD surface |
| `SMC_Long_Strategy.pine` | Strategy / staging layer for the SMC mainline |
| `SMC_Hold_Manager.pine` | Hold-management companion surface |
| `SMC_Breakout_Overlay.pine` | Breakout visualization overlay |
| `SMC_Imbalance_Context.pine` | Imbalance-context visualization |
| `SMC_Orderflow_Overlay.pine` | Orderflow / microstructure overlay |
| `SMC_TV_Bridge.pine` | TradingView bridge surface |
| `SkippALGO_Confluence.pine` | Legacy confluence-oriented Pine surface kept in-tree |

---

## Developer Guide

### Tests

```bash
# Focused file (repo default is xdist `-n 4 --dist=loadfile`)
python -m pytest tests/test_production_gatekeeper.py -q

# Interactive debugging / breakpoints
python -m pytest tests/test_production_gatekeeper.py -q -n0

# Local fast sweep (explicit parallelism)
python -m pytest tests/ -q --maxfail=1 -n 8 --dist=worksteal

# CI parity for PR-like local runs
python -m pytest tests/ -q --maxfail=1 -n auto --dist=worksteal

# Push-like local run with coverage (slower, mirrors CI push mode)
python -m pytest tests/ -q --maxfail=1 -n auto --dist=worksteal \
  --cov --cov-report=term-missing:skip-covered
```

Local default pytest addopts are pinned in `pyproject.toml` to
`-n 4 --dist=loadfile`. That gives fast local parallelism while keeping each
test file on a single worker. For interactive debugging (`pdb`, breakpoints,
single-worker determinism), override with `-n0`. CI still overrides to
`-n auto` explicitly on the workflow command line.

The repository does not currently ship tracked VS Code task definitions, so
any local tasks you use for pytest/bootstrap should be treated as
workspace-specific helpers rather than canonical repo interfaces.

For GPU validation of the Open-Prep feature-importance path, install
`requirements-gpu.txt` into `.venv` and run the recurring report with
`OPEN_PREP_FI_BACKEND=gpu python -m open_prep.feature_importance_report --lookback 30`.

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

```text
skipp-algo/
├── streamlit_terminal.py          # Real-Time News Intelligence Dashboard (11 top-level tabs)
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
├── terminal_tabs/                 # Tab rendering modules + shared helpers
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
├── ml/                            # C10 ML layer (calibration / stacking / drift)
├── rl/                            # C12 RL execution layer (baselines / simulator / safety)
│
├── databento_volatility_screener.py      # Core Databento screener engine + exports + Streamlit UI logic
├── streamlit_databento_volatility_screener.py # Standalone Streamlit launcher for the Databento screener
├── terminal_databento.py                 # Databento quote helpers for the main terminal and Open-Prep monitor
├── strategy_config.py                    # Long-Dip watchlist and execution defaults
│
├── tests/                         # Contract, regression, workflow, and smoke suites
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
├── requirements-ml.txt            # Optional heavy ML backends
├── requirements-rl.txt            # Optional heavy RL backends
├── requirements.txt               # Python dependencies
└── CHANGELOG.md                   # Full changelog
```

---

## Documentation Index

### Repo Entry Points

- [Root README](README.md)
- [Docs Index (`docs/README.md`)](docs/README.md)

### ML & RL

- [ML Layer README](ml/README.md)
- [RL Layer README](rl/README.md)
- [Sprint Plan C10 — ML Layer](docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md)
- [Sprint Plan C12 — RL Execution](docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md)

### Terminal & Operations

- [Terminal Architecture Plan](docs/BLOOMBERG_TERMINAL_PLAN.md)
- [Databento Volatility Suite Guide](docs/DATABENTO_VOLATILITY_SUITE.md)
- [Open Prep Suite — Technical Reference](docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md)
- [Open Prep Suite — Ops Quick Reference](docs/OPEN_PREP_OPS_QUICK_REFERENCE.md)
- [Open Prep Suite — Incident Runbook Matrix](docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md)
- [Open Prep Suite — Incident Runbook (One-Page)](docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md)
- [Open Prep Feature-Importance Samples](artifacts/open_prep/outcomes/feature_importance/README.md)
- [TradersPost Integration](docs/TRADERSPOST_INTEGRATION.md)
- [TradingView Strategy Guide](docs/TRADINGVIEW_STRATEGY_GUIDE.md)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md)

### Pine Script

- [Deep Technical Documentation](docs/SkippALGO_Deep_Technical_Documentation.md)
- [Deep Technical Documentation (v6.2.22, archive)](docs/archive/SkippALGO_Deep_Technical_Documentation_v6.2.22.md)
- [Market Structure Guide](docs/SkippALGO_Market_Structure.md)
- [SMC++ Dashboard Guide (DE)](docs/SMC_Dashboard_Long_Dip_Guide_DE.md)
- [SMC Decision-First UX PRD](docs/smc-tradingview-decision-first-prd.md)
- [SMC Decision-First UX Backlog](docs/smc-tradingview-decision-first-backlog.md)
- [SMC Screen Specification](docs/smc-tradingview-screen-spec.md)
- [SMC First-Release Ticketset](docs/smc-tradingview-first-release-ticketset.md)
- [SMC R1.2 Ticketset](docs/smc-tradingview-r1-2-ticketset.md)
- [SMC First UI Cut Implementation Preparation](docs/smc-tradingview-first-ui-cut-implementation.md)
- [SMC R1.1 Migration and Operator Guide](docs/smc-tradingview-r1-1-migration-and-operator-guide.md)
- [SMC Product Rescue Playbook](docs/smc-product-rescue-playbook.md)

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

# Bloomberg Terminal — Architecture & Implementation

## Summary

Real-time news terminal powered by **Benzinga REST polling** + **FMP market data** +
existing open\_prep intelligence classifiers.  Runs as a standalone Streamlit app
(`streamlit_terminal.py`), separate from the batch-oriented `streamlit_monitor.py`.

**Status:** Fully implemented and operational (Feb 2026).

---

## 1. Data Sources

### Benzinga REST API

| Item | Value |
| --- | --- |
| **News** | `GET https://api.benzinga.com/api/v2/news` |
| **Top News** | `GET https://api.benzinga.com/api/v2/news` (sort=mostPopular) |
| **Channels** | `GET https://api.benzinga.com/api/v2/news/channels` |
| **Quantified News** | `GET https://api.benzinga.com/api/v2/news/quantified` |
| **Calendar (Ratings)** | `GET https://api.benzinga.com/api/v2.1/calendar/ratings` |
| **Calendar (Earnings)** | `GET https://api.benzinga.com/api/v2.1/calendar/earnings` |
| **Calendar (Economics)** | `GET https://api.benzinga.com/api/v2.1/calendar/economics` |
| **Calendar (Conference Calls)** | `GET https://api.benzinga.com/api/v2.1/calendar/conference-calls` |
| **Calendar (Dividends)** | `GET https://api.benzinga.com/api/v2.1/calendar/dividends` |
| **Calendar (Splits)** | `GET https://api.benzinga.com/api/v2.1/calendar/splits` |
| **Calendar (IPOs)** | `GET https://api.benzinga.com/api/v2.1/calendar/ipos` |
| **Calendar (Guidance)** | `GET https://api.benzinga.com/api/v2.1/calendar/guidance` |
| **Calendar (Retail)** | `GET https://api.benzinga.com/api/v2.1/calendar/retail` |
| **Movers** | `GET https://api.benzinga.com/api/v1/market/movers` |
| **Delayed Quotes** | `GET https://api.benzinga.com/api/v1/quoteDelayed` |
| **Fundamentals** | `GET https://api.benzinga.com/api/v2.1/fundamentals` |
| **Financials** | `GET https://api.benzinga.com/api/v2.1/fundamentals/financials` |
| **Valuation Ratios** | `GET https://api.benzinga.com/api/v2.1/fundamentals/valuationRatios` |
| **Company Profiles** | `GET https://api.benzinga.com/api/v2.1/fundamentals/companyProfile` |
| **Price History** | `GET https://api.benzinga.com/api/v2.1/stock/priceHistory` |
| **Chart** | `GET https://api.benzinga.com/api/v2.1/stock/chart` |
| **Auto-Complete** | `GET https://api.benzinga.com/api/v2.1/search/autocomplete` |
| **Security (Lookup)** | `GET https://api.benzinga.com/api/v2.1/security` |
| **Instruments** | `GET https://api.benzinga.com/api/v2.1/instruments` |
| **Logos** | `GET https://api.benzinga.com/api/v2.1/logos` |
| **Ticker Detail** | `GET https://api.benzinga.com/api/v2.1/tickerDetail` |
| **Options Activity** | `GET https://api.benzinga.com/api/v2.1/calendar/options_activity` |
| **Auth** | `?token=<API_KEY>` query parameter |
| **Delta sync** | `updatedSince=<unix_epoch>` for news polling |
| **Filtering** | `channels=` and `topics=` params for news + WebSocket |

### FMP API

| Item | Value |
| --- | --- |
| **Spike Scanner** | Pre-market/after-hours price & volume screening |
| **Sector Performance** | Sector heatmap data |
| **Auth** | `?apikey=<API_KEY>` query parameter |

### News response fields per item

| Field | Type | Notes |
| --- | --- | --- |
| `id` | int | Unique article ID |
| `author` | str | Journalist name |
| `created` | str | RFC 2822 datetime |
| `updated` | str | RFC 2822 datetime (changes on edits) |
| `title` | str | Plain-text headline |
| `teaser` | str | Short context, may contain HTML |
| `url` | str | benzinga.com link |
| `channels` | list[{name}] | Categories: Equities, WIIM, Top Stories, Tech… |
| `stocks` | list[{name, isin, exchange}] | Tickers referenced |
| `tags` | list[{name}] | Themes, people, events |

---

## 2. Architecture

```text
 ┌───────────────────────────────┐  ┌────────────────────────────┐
 │  BENZINGA REST                │  │  FMP API                   │
 │  • /api/v2/news (poll)        │  │  • Spike Scanner           │
 │  • /api/v2.1/calendar/*       │  │  • Sector Performance      │
 │  • /api/v1/market/movers      │  │                            │
 │  • /api/v1/quoteDelayed       │  │                            │
 └──────────────┬────────────────┘  └─────────────┬──────────────┘
                │ List[NewsItem]                   │ Quotes/Sectors
                ▼                                  ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  CLASSIFY & SCORE                                            │
 │  • newsstack_fmp.scoring.classify_and_score()                │
 │  • open_prep.news.classify_article_sentiment()               │
 │  • WIIM boost (_classify_item)                               │
 │  • terminal_spike_scanner.classify_spikes()                  │
 │  • terminal_spike_scanner.overlay_extended_hours_quotes()     │
 └──────────────────────────┬───────────────────────────────────┘
                            │ List[ClassifiedItem] + Spikes
                            ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  STATE (SQLite)                                              │
 │  • Dedup: seen(provider, item_id)                            │
 │  • Novelty: clusters(hash) + count                           │
 │  • Cursor: kv(terminal_cursor, epoch)                        │
 └──────────────────────────┬───────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
  ┌────────────┐    ┌────────────┐    ┌──────────────────┐
  │ Streamlit  │    │ JSONL      │    │ Background       │
  │ Terminal   │    │ Export     │    │ Poller           │
  │ (auto-ref) │    │ (VisiData) │    │ (feed lifecycle) │
  └────────────┘    └────────────┘    └──────────────────┘
```

---

## 3. Implemented Components

### A) `streamlit_terminal.py` — Main Terminal App

- Streamlit page with `st.set_page_config(layout="wide")`
- Sidebar: API key inputs (Benzinga + FMP), poll interval slider, channel filter
- Auto-refresh via `st.rerun()` timer (configurable)
- Tabs:
  - **Live Feed** — scrolling table with color-coded sentiment, clickable headline links
  - **Rankings** — top-scored items per ticker with BZ delayed-quote overlay
  - **Spike Scanner** — pre-market/after-hours price & volume spikes (FMP)
  - **Top Movers** — Benzinga market movers (gainers/losers)
  - **Heatmap** — channel activity visualization
  - **Data Table** — full searchable table with article links
  - **Stats** — items/min, unique tickers, poll timestamp

### B) `terminal_poller.py` — Polling Engine

- `poll_and_classify(adapter, store, cursor) → (items, new_cursor)`
- Each `ClassifiedItem` (NamedTuple) carries:
  - `category`, `impact`, `news_score` (from `classify_and_score`)
  - `sentiment_label`, `sentiment_score` (from `classify_article_sentiment`)
  - `event_class`, `event_label`, `materiality` (from `classify_news_event`)
  - `recency_bucket`, `age_minutes` (from `classify_recency`)
  - `source_tier`, `source_rank` (from `classify_source_quality`)
  - `is_wiim` flag for WIIM-boosted articles
  - `channels`, `tags` (raw from Benzinga)

### C) `terminal_export.py` — JSONL + Webhook

- `append_jsonl(item, path)` — one item per line for VisiData tailing
- `rotate_jsonl(path, max_lines)` — trim old entries
- `fire_webhook(item, url, secret)` — POST to TradersPost (guarded by min score + URL)

### D) `terminal_spike_scanner.py` — Spike Detection & BZ Overlay

- `classify_spikes(quotes, thresholds)` — detect pre-market/after-hours price/volume spikes
- `market_session()` — detect current US market session (pre-market, regular, after-hours, closed)
- `overlay_extended_hours_quotes(rows, quotes)` — overlay Benzinga delayed quotes on stale FMP data
- `build_vd_snapshot(items, spikes, bz_quotes)` — VisiData-ready snapshot with RT > BZ > FMP price priority
- `SESSION_ICONS` — canonical session label dict, imported by both Streamlit apps

### E) `terminal_background_poller.py` — Background Polling Thread

- `BackgroundPoller` — background thread for continuous polling with configurable interval
- Thread-safe adapter/store access with `_lock`
- Dynamic interval override via `_interval_override`

### F) `terminal_feed_lifecycle.py` — Feed State Management

- Ring-buffer eviction (maxsize 500, replaces queue drop-on-full)
- Feed lifecycle: items → dedup → classify → store → export

### G) `terminal_notifications.py` — Push Notifications

- Desktop notification dispatch for high-score items
- Configurable score threshold for notification trigger

### H) `terminal_ui_helpers.py` — UI Helper Functions

- Sentiment coloring, ticker extraction, channel heatmap computation
- Top movers aggregation, segment rendering

### I) `newsstack_fmp/ingest_benzinga_calendar.py` — Calendar Adapters

- `BenzingaCalendarAdapter` with typed fetchers:
  - `fetch_ratings()`, `fetch_earnings()`, `fetch_economics()`, `fetch_conference_calls()`
  - `fetch_dividends()`, `fetch_splits()`, `fetch_ipos()`, `fetch_guidance()`, `fetch_retail()`
- `fetch_benzinga_movers(api_key)` — top gainers/losers
- `fetch_benzinga_delayed_quotes(api_key, symbols)` — delayed price quotes
- WIIM boost in `_classify_item()` for "Why Is It Moving" articles

### J) `newsstack_fmp/ingest_benzinga.py` — News Adapters (Extended)

- `fetch_benzinga_top_news(api_key)` — curated top/most-popular stories
- `fetch_benzinga_channels(api_key)` — available channel list for filtering
- `fetch_benzinga_quantified_news(api_key)` — sentiment-scored articles with entity-level scores
- REST + WebSocket adapters support `channels` and `topics` query params for server-side filtering

### K) `newsstack_fmp/ingest_benzinga_financial.py` — Financial Data Adapter (NEW)

- `BenzingaFinancialAdapter` with 20+ methods:
  - `fetch_fundamentals()`, `fetch_financials()`, `fetch_valuation_ratios()`, `fetch_company_profiles()`
  - `fetch_price_history()`, `fetch_chart()`, `fetch_auto_complete()`, `fetch_security()`
  - `fetch_instruments()`, `fetch_logos()`, `fetch_ticker_detail()`, `fetch_options_activity()`
- Eight standalone wrapper functions for direct use: `fetch_benzinga_fundamentals()`, `fetch_benzinga_financials()`, `fetch_benzinga_ratios()`, `fetch_benzinga_profiles()`, `fetch_benzinga_options_activity()`, `fetch_benzinga_price_history()`, `fetch_benzinga_logos()`, `fetch_benzinga_ticker_detail()`
- Full retry/backoff via httpx, consistent error handling

### L) Open Prep Benzinga Intelligence

- `open_prep/streamlit_monitor.py` — 8-tab Benzinga Intelligence section:
  - Dividends, Splits, IPOs, Guidance, Retail Sentiment, Top News, Quantified News, Options Flow
- 10 cached wrapper functions with `@st.cache_data(ttl=120)` TTLs
- Import-guarded for Streamlit Cloud compatibility

### M) VisiData Benzinga Enrichment

- `terminal_export.py` — per-ticker enrichment columns:
  - `div_exdate`, `div_yield` (from dividends calendar)
  - `guid_eps` (from guidance calendar)
  - `options_flow` (from options activity)
- `build_vd_bz_calendar()` / `save_vd_bz_calendar()` — standalone Benzinga Calendar JSONL
- Default export path: `artifacts/vd_bz_calendar.jsonl`

---

## 4. Reused Components

| Component | Import Path | What it does |
| --- | --- | --- |
| `BenzingaRestAdapter` | `newsstack_fmp.ingest_benzinga` | REST polling with retry/backoff |
| `BenzingaCalendarAdapter` | `newsstack_fmp.ingest_benzinga_calendar` | Calendar/movers/quotes (ratings, earnings, economics, dividends, splits, IPOs, guidance, retail) |
| `BenzingaFinancialAdapter` | `newsstack_fmp.ingest_benzinga_financial` | Fundamentals, financials, ratios, profiles, price history, options activity |
| `normalize_benzinga_rest` | `newsstack_fmp.normalize` | Raw Benzinga → `NewsItem` |
| `NewsItem` | `newsstack_fmp.common_types` | Unified internal schema |
| `classify_and_score` | `newsstack_fmp.scoring` | Category + impact + novelty score |
| `cluster_hash` | `newsstack_fmp.scoring` | Cross-provider dedup hash |
| `SqliteStore` | `newsstack_fmp.store_sqlite` | Dedup + novelty + cursor persistence |
| `Config` | `newsstack_fmp.config` | Env-var-driven configuration |
| `classify_article_sentiment` | `open_prep.news` | Negation-aware sentiment classifier |
| `classify_news_event` | `open_prep.playbook` | Event class / label / materiality |
| `classify_recency` | `open_prep.playbook` | Age buckets: ULTRA_FRESH → STALE |
| `classify_source_quality` | `open_prep.playbook` | Source tier 1-4 ranking |
| `market_session` | `terminal_spike_scanner` | US market session detection |
| `SESSION_ICONS` | `terminal_spike_scanner` | Session label dict |

---

## 5. File Layout

```text
streamlit_terminal.py                  ← Streamlit app (streamlit run streamlit_terminal.py)
terminal_poller.py                     ← Poll engine + ClassifiedItem + classifier orchestration
terminal_export.py                     ← JSONL writer + TradersPost webhook + VisiData BZ enrichment
terminal_spike_scanner.py              ← Spike detection, market session, BZ overlay
terminal_background_poller.py          ← Background polling thread
terminal_feed_lifecycle.py             ← Ring-buffer feed state management
terminal_notifications.py              ← Desktop push notifications
terminal_ui_helpers.py                 ← Sentiment coloring, heatmap, movers aggregation
newsstack_fmp/ingest_benzinga.py       ← REST/WS news adapter + top news, channels, quantified
newsstack_fmp/ingest_benzinga_calendar.py ← Calendar adapters (ratings, earnings, dividends, splits, IPOs, guidance, retail) + movers/quotes
newsstack_fmp/ingest_benzinga_financial.py ← Financial data adapter (fundamentals, ratios, profiles, options, charts)
open_prep/streamlit_monitor.py         ← Open Prep Streamlit app with Benzinga Intelligence section
tests/test_terminal.py                 ← Core terminal tests
tests/test_terminal_spike_scanner.py   ← Spike scanner + BZ overlay tests
tests/test_terminal_background_poller.py ← Background poller tests
tests/test_terminal_feed_lifecycle.py  ← Feed lifecycle tests
tests/test_terminal_notifications.py   ← Notification tests
tests/test_terminal_ui_helpers.py      ← UI helper tests
tests/test_benzinga_calendar.py        ← Calendar/movers/quotes adapter tests (79 tests)
tests/test_benzinga_news_endpoints.py  ← Top news, channels, quantified news tests (18 tests)
tests/test_benzinga_financial.py       ← Financial data adapter tests (44 tests)
tests/test_benzinga_calendar_extended.py ← Extended calendar tests (dividends, splits, IPOs, guidance, retail — 17 tests)
tests/test_vd_bz_enrichment.py        ← VisiData Benzinga enrichment tests (24 tests)
docs/BLOOMBERG_TERMINAL_PLAN.md        ← This document
```

---

## 6. Environment Variables

| Var | Default | Purpose |
| --- | --- | --- |
| `BENZINGA_API_KEY` | *(required for BZ features)* | API token for news, calendar, movers, quotes |
| `FMP_API_KEY` | *(required for FMP features)* | API token for spike scanner, sectors |
| `TERMINAL_POLL_INTERVAL_S` | `5.0` | Seconds between polls |
| `TERMINAL_SQLITE_PATH` | `newsstack_fmp/terminal_state.db` | Separate state DB |
| `TERMINAL_JSONL_PATH` | `artifacts/terminal_feed.jsonl` | JSONL export for VisiData |
| `TERMINAL_WEBHOOK_URL` | *(empty = disabled)* | TradersPost webhook URL |
| `TERMINAL_WEBHOOK_SECRET` | *(empty)* | HMAC secret for webhook signing |
| `TERMINAL_MAX_ITEMS` | `500` | Max items to keep in live feed (ring-buffer) |
| `TERMINAL_CHANNELS` | *(empty = all)* | Comma-separated channel filter |
| `TERMINAL_TOPICS` | *(empty = all)* | Comma-separated topics filter |

---

## 7. Test Coverage

- 34 test files, **1599 tests** total (as of 27 Feb 2026)
- Terminal-specific: `test_terminal.py`, `test_terminal_spike_scanner.py`, `test_terminal_background_poller.py`, `test_terminal_feed_lifecycle.py`, `test_terminal_notifications.py`, `test_terminal_ui_helpers.py`, `test_benzinga_calendar.py`
- Benzinga API coverage: `test_benzinga_news_endpoints.py`, `test_benzinga_financial.py`, `test_benzinga_calendar_extended.py`
- VisiData enrichment: `test_vd_bz_enrichment.py`
- All Pylance/Pyright lint errors resolved (0 workspace errors)

---

## 8. VisiData Integration

Tail the JSONL file with:

```bash
vd --filetype jsonl artifacts/terminal_feed.jsonl
```

Each line is a self-contained JSON object with all classifications.
VisiData auto-reloads on file change.

The `build_vd_snapshot()` function in `terminal_spike_scanner.py` produces
VisiData-ready rows with price priority: RT (realtime) > BZ (Benzinga delayed) > FMP (close).

### Benzinga Enrichment Columns

When Benzinga calendar/financial data is available, `build_vd_snapshot()` and
`save_vd_snapshot()` in `terminal_export.py` enrich each ticker row with:

| Column | Source | Description |
| --- | --- | --- |
| `div_exdate` | Dividends calendar | Next ex-dividend date |
| `div_yield` | Dividends calendar | Dividend yield |
| `guid_eps` | Guidance calendar | EPS guidance estimate |
| `options_flow` | Options activity | Unusual options activity summary |

### Benzinga Calendar JSONL

`build_vd_bz_calendar()` / `save_vd_bz_calendar()` in `terminal_export.py` produce
a standalone calendar export combining dividends, splits, IPOs, and guidance events:

```bash
vd --filetype jsonl artifacts/vd_bz_calendar.jsonl
```

---

## 9. Benzinga Delayed-Quote Overlay

During pre-market and after-hours sessions, FMP data reflects the previous close.
The terminal overlays Benzinga delayed quotes for fresher price/change data:

- **Detection:** `market_session()` checks current US time against session boundaries
- **Overlay:** `overlay_extended_hours_quotes()` patches `bz_price`/`bz_chg_pct` onto rows
- **Session icons:** `SESSION_ICONS` dict provides user-facing labels (🌅 Pre-Market, 🟢 Regular, 🌙 After-Hours, ⚫ Closed)
- **Caching:** `@st.cache_data(ttl=60)` prevents redundant API calls
- **Consumers:** `streamlit_terminal.py`, `open_prep/streamlit_monitor.py`, VisiData snapshots

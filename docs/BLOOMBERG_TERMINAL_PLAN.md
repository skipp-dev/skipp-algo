# Bloomberg Terminal — Implementation Plan

## Summary

Real-time news terminal powered by **Benzinga REST polling** + existing
open\_prep intelligence classifiers.  Runs as a standalone Streamlit app
(`streamlit_terminal.py`), separate from the batch-oriented `streamlit_monitor.py`.

---

## 1. Benzinga API Findings

### Endpoint we use

| Item | Value |
|---|---|
| **URL** | `GET https://api.benzinga.com/api/v2/news` |
| **Auth** | `?token=<API_KEY>` query parameter |
| **Pagination** | `page=0`, `pageSize` max **100** |
| **Delta sync** | `updatedSince=<unix_epoch>` — recommended for polling |
| **Ticker filter** | `tickers=AAPL,NVDA,TSLA` (csv, max 50) |
| **Channel filter** | `channels=Earnings,WIIM,Equities` |
| **Display modes** | `displayOutput=headline|abstract|full` |
| **Removed items** | `GET /api/v2/news-removed` → `{"removed":[{"id":…}]}` |

### Response fields per item

| Field | Type | Notes |
|---|---|---|
| `id` | int | Unique article ID |
| `author` | str | Journalist name |
| `created` | str | RFC 2822 datetime |
| `updated` | str | RFC 2822 datetime (changes on edits) |
| `title` | str | Plain-text headline |
| `teaser` | str | Short context, may contain HTML |
| `body` | str | Full HTML (only with `displayOutput=full`) |
| `url` | str | benzinga.com link |
| `channels` | list[{name}] | Categories: Equities, WIIM, Top Stories, Tech… |
| `stocks` | list[{name, isin, exchange}] | Tickers referenced |
| `tags` | list[{name}] | Themes, people, events |
| `image` | list[{size, url}] | Featured images |

### What our existing `BenzingaRestAdapter` already does

- ✅ Polls `/api/v2/news` with `updatedSince` + `pageSize`
- ✅ Handles retries (429, 5xx) with exponential backoff
- ✅ Parses JSON list or `{articles:[…]}` wrapper
- ✅ Normalizes via `normalize_benzinga_rest()` → `NewsItem`

### What we add for the terminal

- **`channels` parameter** — filter to actionable channels (WIIM, Earnings, Movers)
- **`displayOutput=abstract`** — get teasers without full HTML body
- **No `tickers` filter** — poll broad market, then classify client-side
- **Polling interval: 5-10 seconds** — within rate limits for trial key

---

## 2. Architecture

```
 ┌─────────────────────────────────────────────────┐
 │  BENZINGA REST  /api/v2/news                    │
 │  (poll every N seconds via updatedSince)        │
 └───────────────────┬─────────────────────────────┘
                     │ List[NewsItem]
                     ▼
 ┌─────────────────────────────────────────────────┐
 │  CLASSIFY & SCORE                               │
 │  • newsstack_fmp.scoring.classify_and_score()   │
 │  • open_prep.news.classify_article_sentiment()  │
 │  • open_prep.playbook.classify_news_event()     │
 │  • open_prep.playbook.classify_recency()        │
 │  • open_prep.playbook.classify_source_quality() │
 └───────────────────┬─────────────────────────────┘
                     │ List[EnrichedItem]
                     ▼
 ┌─────────────────────────────────────────────────┐
 │  STATE (SQLite)                                 │
 │  • Dedup: seen(provider, item_id)               │
 │  • Novelty: clusters(hash) + count              │
 │  • Cursor: kv(terminal_cursor, epoch)           │
 └───────────────────┬─────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
   ┌───────────┐ ┌────────┐ ┌──────────────┐
   │ Streamlit │ │ JSONL  │ │ TradersPost  │
   │ Terminal  │ │ Export │ │ Webhook Stub │
   │ (2s auto) │ │(VisiD.)│ │              │
   └───────────┘ └────────┘ └──────────────┘
```

---

## 3. Components to Build

### A) `streamlit_terminal.py` (new — main app)

- Streamlit page with `st.set_page_config(layout="wide")`
- Sidebar: API key input, poll interval slider, channel filter checkboxes
- Auto-refresh via `st.rerun()` timer (configurable, default 5s)
- Main panel:
  - **Live Feed** — scrolling table of latest N items, color-coded by sentiment
  - **Top Movers** — best-scored items per ticker (last 30 min)
  - **Stats bar** — items/min, unique tickers, last poll timestamp
- Uses `newsstack_fmp.ingest_benzinga.BenzingaRestAdapter` for fetching
- Uses `newsstack_fmp.store_sqlite.SqliteStore` for dedup/novelty
- Imports classifiers directly from `open_prep` as standalone functions

### B) `terminal_poller.py` (new — polling engine)

Thin wrapper around `BenzingaRestAdapter` + classifiers:

- `poll_and_classify(adapter, store, cursor) → (items, new_cursor)`
- Each item gets enriched with:
  - `category`, `impact`, `score` (from `classify_and_score`)
  - `sentiment_label`, `sentiment_score` (from `classify_article_sentiment`)
  - `event_class`, `event_label`, `materiality` (from `classify_news_event`)
  - `recency_bucket`, `age_minutes` (from `classify_recency`)
  - `source_tier`, `source_rank` (from `classify_source_quality`)
  - `channels` (raw from Benzinga response)

### C) `terminal_export.py` (new — JSONL + webhook)

- `append_jsonl(item, path)` — append one item per line for VisiData tailing
- `fire_webhook(item, url, secret)` — POST to TradersPost (stub, guarded by feature flag)

### D) `tests/test_terminal.py` (new — unit tests)

- Test `poll_and_classify` with mock adapter responses
- Test JSONL export round-trip
- Test webhook stub (mock httpx)
- Test classifier integration (sentiment + event + recency combined)

---

## 4. Reused Components (zero refactoring needed)

| Component | Import Path | What it does |
|---|---|---|
| `BenzingaRestAdapter` | `newsstack_fmp.ingest_benzinga` | REST polling with retry/backoff |
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

---

## 5. File Layout

```
streamlit_terminal.py     ← Streamlit app (entry point: streamlit run streamlit_terminal.py)
terminal_poller.py        ← Poll engine + classifier orchestration
terminal_export.py        ← JSONL writer + TradersPost webhook stub
tests/test_terminal.py    ← Unit tests
docs/BLOOMBERG_TERMINAL_PLAN.md  ← This document
```

---

## 6. Environment Variables

| Var | Default | Purpose |
|---|---|---|
| `BENZINGA_API_KEY` | *(required)* | API token for REST calls |
| `TERMINAL_POLL_INTERVAL_S` | `5.0` | Seconds between polls |
| `TERMINAL_SQLITE_PATH` | `newsstack_fmp/terminal_state.db` | Separate state DB |
| `TERMINAL_JSONL_PATH` | `artifacts/terminal_feed.jsonl` | JSONL export for VisiData |
| `TERMINAL_WEBHOOK_URL` | *(empty = disabled)* | TradersPost webhook URL |
| `TERMINAL_WEBHOOK_SECRET` | *(empty)* | HMAC secret for webhook signing |
| `TERMINAL_MAX_ITEMS` | `500` | Max items to keep in live feed |
| `TERMINAL_CHANNELS` | *(empty = all)* | Comma-separated channel filter |

---

## 7. Implementation Order

1. **`terminal_poller.py`** — core polling + classification loop
2. **`terminal_export.py`** — JSONL + webhook
3. **`streamlit_terminal.py`** — UI
4. **`tests/test_terminal.py`** — tests
5. Wire `.env` + run full test suite

---

## 8. VisiData Integration

Tail the JSONL file with:

```bash
vd --filetype jsonl artifacts/terminal_feed.jsonl
```

Each line is a self-contained JSON object with all classifications.
VisiData auto-reloads on file change.

---

## 9. TradersPost Webhook (stub)

Later phase — fires HTTP POST with JSON payload when a high-score item
arrives.  Guarded by `TERMINAL_WEBHOOK_URL` being non-empty.

Payload shape (draft):

```json
{
  "ticker": "NVDA",
  "action": "buy",
  "headline": "NVIDIA beats Q4 estimates…",
  "score": 0.91,
  "sentiment": "bullish",
  "event": "earnings",
  "materiality": "HIGH",
  "source_tier": "TIER_2",
  "timestamp": 1740000000.0
}
```

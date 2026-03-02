# API Budget Calculations — SkippALGO Terminal

> Computed: 2 March 2026
> Configuration: 10s market-hours poll, 300s off-hours poll, 30s dedup reset

---

## 1. Constraints

| Resource | Limit | Notes |
|---|---|---|
| FMP Bandwidth | 150 GB / trailing 30 days | FMP Ultimate plan |
| FMP Rate Limit | 3,000 calls/min | Per-minute cap |
| NewsAPI.ai Tokens | 10,000 / month | Article search = 1 token; Event search = 5 tokens |
| Already consumed (bugs/testing) | 32.26 GB | From hammering on 1-2 March 2026 |

---

## 2. Time Windows

| Period | Duration | Poll interval |
|---|---|---|
| Market hours (14:00–22:00 UTC+1) | 8h = 28,800s | **10s** |
| Off-hours (rest of day) | 16h = 57,600s | **300s** (5 min) |
| Weekends (full day) | 24h = 86,400s | **300s** (5 min) |
| Trading days remaining this month | ~20 | |
| Weekend/off days remaining | ~9 | |

---

## 3. Per-Poll Bandwidth

Each BG poller cycle fires exactly 3 HTTP requests:

| Request | Provider | Response size |
|---|---|---|
| `/stable/news/stock-latest?page=0&limit=100` | FMP | ~150 KB |
| `/stable/news/press-releases-latest?page=0&limit=50` | FMP | ~100 KB |
| `fetch_news(updated_since=cursor, page_size=100)` | Benzinga | ~200 KB |
| HTTP headers & overhead (3 requests) | — | ~3 KB |
| **Total per poll** | | **~453 KB** |

**Key fact:** FMP endpoints are completely stateless (`page=0` always).
The cursor only affects Benzinga's `updated_since` parameter.
A cursor reset does NOT create extra FMP calls — it just changes
what Benzinga returns.

---

## 4. Dedup Reset Cost

A "Reset dedup DB" does:
1. `prune_seen(keep_seconds=0)` — clear SQLite `seen` table
2. `prune_clusters(keep_seconds=0)` — clear SQLite `clusters` table
3. `cursor = None` — reset Benzinga cursor
4. `wake_event.set()` — interrupt BG poller sleep → immediate poll

This triggers **1 extra poll cycle** = 3 HTTP requests = **~453 KB**.

The in-memory dedup in `_process_new_items()` (checks `item_id:ticker`
keys + headline matching) prevents re-ingested articles from appearing
as duplicates in the UI.

---

## 5. Feature → API Call Matrix

### KEEP Features

| # | Feature | FMP calls/miss | BZ calls/miss | NewsAPI tokens/miss | Cache TTL |
|---|---|---|---|---|---|
| 1 | **Actionable** | 0 | 0 | 0 | — (feed data) |
| 2 | **Outlook Today** | 2 (econ_cal + sector_perf) | 2 (earnings + economics) | 5–10 (trending+NLP) | 300s |
| 3 | **Outlook Tomorrow** | 2 (econ_cal + sector_perf) | 2 (earnings + economics) | 5–10 (trending+NLP) | 300s |
| 4 | **AI Insights** | 0 | 0 | 0 (OpenAI only) | — |
| 5 | **Segments** | 1 (profile) | 0 | 0 | 300s |
| 6 | **Live Feed** | 0 | 0 | 0 (BG poller) | — |
| 7 | **Rankings** | 0 | 0 | 0 | — (feed data) |
| 8 | **Sector Perf chart** | 1 (sector-perf-snapshot) | 0 | 0 | 300s |
| 9 | **Bitcoin (slow)** | ~3 (quote+F&G+news) | 0 | 1 (BTC headlines) | 300–600s |
| 10 | **Data Table** | 0 | 0 | 0 | — (feed data) |
| 11 | **Alerts** | 0 | 0 | 0 | — (webhook) |

### DROPPED Features (savings)

| Feature | FMP saved/miss | BZ saved/miss | NewsAPI tokens saved | Old TTL |
|---|---|---|---|---|
| Top Movers (FMP) | 5 | 0 | 0 | 90s |
| Movers (BZ) | 0 | 2 (movers+quotes) | 0 | 60s |
| RT Spikes | 5 | 0 | 0 | 90s |
| Spikes | 5 | 0 | 0 | 90s |
| Calendar | 1 | 0 | 0 | 300s |
| Defense & Aerospace | 3 | 0 | 0 | 300s |
| Breaking Events | 0 | 0 | 5/hr | 3600s |
| Trending | 0 | 0 | 5/hr | 3600s |
| Social | 0 | 0 | 1/hr | 3600s |
| Heatmap | 0 | 0 | 0 | — |

---

## 6. Daily Budget — Trading Day

### A. BG Poller (core polling)

| Period | Interval | Polls | FMP reqs | BZ reqs | Bandwidth |
|---|---|---|---|---|---|
| Market (8h) | 10s | 2,880 | 5,760 | 2,880 | 1.304 GB |
| Off-hours (16h) | 300s | 192 | 384 | 192 | 0.087 GB |
| **Subtotal** | | **3,072** | **6,144** | **3,072** | **1.391 GB** |

### B. Dedup resets (every 30s, market hours only)

| | Count | Extra polls | Bandwidth |
|---|---|---|---|
| Market hours (8h) | 960 | 960 | 0.435 GB |

### C. Cached wrappers (KEEP features only)

| Endpoint | TTL | Misses/day (8h) | FMP calls | BW/miss | BW/day |
|---|---|---|---|---|---|
| Sector perf (chart) | 300s | 96 | 96 | 6 KB | 0.6 MB |
| Ticker sectors (Segments) | 300s | 96 | 96 | 10 KB | 1.0 MB |
| Outlook Today | 300s | 96 | 192 | 40 KB | 3.8 MB |
| Outlook Tomorrow | 300s | 96 | 192 | 40 KB | 3.8 MB |
| BTC quote | 300s | 96 | 96 | 5 KB | 0.5 MB |
| BTC fear & greed | 300s | 96 | 96 | 5 KB | 0.5 MB |
| BTC news | 300s | 96 | 96 | 15 KB | 1.4 MB |
| **Subtotal** | | | **864** | | **11.6 MB** |

### D. Daily total

| Category | GB/day |
|---|---|
| BG polling (market 10s + off-hours 300s) | 1.391 |
| Dedup resets (every 30s, market only) | 0.435 |
| Cached wrappers (KEEP features) | 0.012 |
| **Daily total** | **1.838 GB** |

---

## 7. Weekend Day Budget

| Category | GB/day |
|---|---|
| Slow polling (300s, 24h) | 0.130 |
| No dedup resets | 0 |
| **Weekend daily total** | **0.130 GB** |

---

## 8. 30-Day Projection

| Period | Days | GB/day | Total GB |
|---|---|---|---|
| Already consumed (bugs) | — | — | 32.26 |
| Trading days remaining | 20 | 1.838 | 36.76 |
| Weekend days | 9 | 0.130 | 1.17 |
| **Grand total** | | | **70.2 GB** |

---

## 9. NewsAPI.ai Token Projection

| Feature | Tokens/miss | TTL | Misses/day | Tokens/day |
|---|---|---|---|---|
| Outlook trending | 5 | 3600s | 8 | 40 |
| Outlook NLP sentiment (×5) | 5 | 3600s | 8 | 40 |
| BTC headlines | 1 | 3600s | 8 | 8 |
| **Daily total** | | | | **88** |
| **Monthly (22 trading days)** | | | | **1,936** |

---

## 10. Final Budget Summary

| Resource | Cap | Projected | Utilization | Headroom |
|---|---|---|---|---|
| **FMP bandwidth** | 150 GB / 30d | 70.2 GB | **46.8%** | **79.8 GB** |
| **FMP rate limit** | 3,000/min | ~14/min peak | **0.5%** | 99.5% |
| **NewsAPI.ai tokens** | 10,000/mo | 1,936/mo | **19.4%** | 8,064 tokens |

---

## 11. Headroom Analysis

With 79.8 GB spare, you can afford:

| Upgrade | Additional cost | Fits? |
|---|---|---|
| Drop poll to 5s market hours | +1.304 GB/day × 20 = 26 GB | Yes (96.2 GB total) |
| Drop poll to 3s market hours | +3.04 GB/day × 20 = 60.8 GB | Yes (131 GB total, tight) |
| Reset dedup every 10s instead of 30s | +0.87 GB/day × 20 = 17.4 GB | Yes |
| Re-enable spike scanner | +0.044 GB/day | Negligible |
| Run 2 Streamlit tabs simultaneously | ×2 = 140 GB | Barely fits |

---

## 12. Configuration Reference

```bash
# .env settings for this budget
TERMINAL_POLL_INTERVAL_S=10      # 10s during market hours
# Off-hours auto-throttles to 300s via lifecycle manager
# Dedup resets every 30s during market hours (coded in BG poller)
```

---

## 13. Key Technical Notes

1. **FMP endpoints are stateless** — always `page=0, limit=X`. Cursor
   resets don't burn extra FMP bandwidth.
2. **Dedup resets don't cause page reloads** — SQLite clear + cursor
   reset happen in BG thread. In-memory feed dedup prevents duplicates.
3. **Cluster score corruption** on reset — novelty counts reset to 0,
   recycled stories may briefly appear novel. Acceptable trade-off for
   feed freshness.
4. **30s reset + 10s poll** means the dedup DB lives for ~3 poll cycles
   before clearing. This ensures genuinely new articles aren't blocked
   by stale dedup entries while the in-memory dedup catches true
   duplicates.

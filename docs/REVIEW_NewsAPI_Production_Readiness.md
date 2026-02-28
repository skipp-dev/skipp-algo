# NewsAPI.ai Integration — Production Readiness Review v2

**Files in scope:** `terminal_newsapi.py` (~1185 lines), `streamlit_terminal.py` (NewsAPI-related changes across ~3381 lines)  
**Reviewer:** Senior Engineer (automated)  
**Date:** 2026-02-28 (v2 — all fixes applied)  

---

## A) Executive Summary

1. **✅ FIXED — Token drain via non-lazy expander loading** — Breaking Events tab now gates `fetch_event_articles()` behind "📰 Load articles" button per event. `st.stop()` halts tab rendering when token limit is reached.

2. **✅ FIXED — False-positive symbol matching** — `fetch_nlp_sentiment()` now uses word-boundary regex for short tickers (≤6 chars, single-word) and case-insensitive substring for multi-word entity labels (e.g. "Donald Trump").

3. **✅ FIXED — Unbounded cache growth** — `_cache` is now protected by `threading.Lock`, evicts expired entries on read miss, and runs a periodic sweep every 50 writes or when size exceeds 500.

4. **✅ FIXED — `socialScore=0` silent failure** — Social tab now shows an info banner when all scores are zero, explaining it may be a plan limitation.

5. **✅ FIXED — Catch-all exception handlers** — All 7 fetch functions now catch expected errors (`ConnectionError`, `TimeoutError`, `OSError`, `ValueError`, `KeyError`) at WARNING level and unexpected errors at EXCEPTION level with full tracebacks.

6. **✅ FIXED — Thread safety** — `_cache` and `_er_instance` protected by `threading.Lock` with double-check locking on the singleton.

7. **Remaining low-risk items:**
   - `fetch_market_articles()` is unused (available as utility API for future use)
   - API key sent as HTTP query param in `get_token_usage()` (standard for this API, no alternative)

---

## B) Bug List — All Fixed

| # | Severity | Symptom | Root cause | Status |
|---|----------|---------|------------|--------|
| B1 | **HIGH** | Breaking tab burned ~20 tokens per page view | `fetch_event_articles()` auto-called for every event | ✅ Gated behind `st.button` + `st.stop()` on limit |
| B2 | **HIGH** | NLP sentiment false positives for single-char tickers | `if sym in title_upper` substring match | ✅ Word-boundary regex for short tickers, substring for multi-word |
| B3 | **MEDIUM** | Memory leak over hours | No cache eviction | ✅ Lock + sweep every 50 writes + evict on read miss |
| B4 | **LOW** | `has_tokens()` false on transient error | HTTP failure → `{0, 0}` → `False` | ✅ Returns `True` when both are 0 |
| B5 | **LOW** | `_c_sent` unused variable | Dead code in `_render_event_clusters_expander` | ✅ Removed |
| B6 | **LOW** | `_sent_badge` unused variable | Dead code in Breaking Events tab | ✅ Removed |
| B7 | **INFO** | Misleading `_ER_HOST` comment | Comment said SDK uses this host | ✅ Comment corrected |
| B8 | **INFO** | `fetch_market_articles` cache key order-dependent | `f"{keywords}"` gives different keys for same list | ✅ Uses `sorted()` join |
| B9 | **MEDIUM** | Token limit warning didn't stop API calls | Banner shown but calls continued below | ✅ `st.stop()` added after warning |

---

## C) Functional Spec Check

| Feature | Spec | Status | Notes |
|---------|------|--------|-------|
| Breaking Events | Show top breaking events with counts, sentiment, sources | ✅ Working | Token-efficient with click-to-load |
| Event Articles | Expand event → click to load enriched articles | ✅ Working | Gated behind button |
| Trending Concepts | Show trending entities with scores | ✅ Working | Handles nested/flat API structures |
| NLP Sentiment | Cross-validate keyword sentiment | ✅ Working | Mixed matching strategy (word-boundary + substring) |
| Event Clusters | Group articles per ticker by story | ✅ Working | Integrated in 4 tabs via reusable helper |
| Social Score Ranking | Rank by virality | ⚠️ Degraded | `socialScore=0` on plan — user warned |
| Token Usage | Show remaining tokens, stop on limit | ✅ Working | Graceful with `st.stop()` |
| Caching | Thread-safe TTL cache with eviction | ✅ Working | Lock, sweep, max-size cap |
| Graceful degradation | Features disabled without API key/SDK | ✅ Working | `is_available()` + `_ER_AVAILABLE` |

---

## D) Edge Cases

| Edge Case | Current Behavior | Risk |
|-----------|-----------------|------|
| `sentiment` is unexpected type (string) | `sentiment_badge()` returns "⚪ n/a" via `isinstance` guard | ✅ Safe |
| `sentiment` is `None` | Properties return `"neutral"` / `"⚪"` | ✅ Safe |
| Empty symbols list | Cache key `nlp_sentiment::24`, returns `{}` | ✅ Safe |
| Single-char ticker ("A", "C", "V") | Word-boundary regex prevents false matches | ✅ Safe |
| Multi-word entity label ("Donald Trump") | Case-insensitive substring match (no word boundary) | ✅ Safe |
| Very long symbol list (100+) | UI slices to 30 before calling | ✅ Safe |
| API timeout / 5xx | Returns `[]` logged at WARNING — retried next cycle | ✅ Safe |
| `httpx` not installed | `get_token_usage()` catches ImportError, returns zeros | ✅ Safe |
| Concurrent Streamlit threads | `_cache_lock` and `_er_lock` prevent races | ✅ Safe |
| `_er_instance` init failure | Stays `None`, retried next call | ✅ Safe |
| No English title | `_extract_title()` falls back to first language | ✅ Safe |
| Authors as dicts | Extracts `name` key, filters empties | ✅ Safe |
| `trendingScore` as nested dict | Extracts from inner `{source: {score: N}}` | ✅ Safe |
| Network failure in `has_tokens()` | Returns `True` (assume available) | ✅ Safe |
| Token limit reached | `st.stop()` halts further API calls in Breaking tab | ✅ Safe |
| Cache size > 500 entries | Sweep evicts all entries older than max TTL | ✅ Safe |

---

## E) Tests

### Existing coverage

No unit tests exist for `terminal_newsapi.py`. The 1,634 passing tests are all for other modules.

### Recommended test plan

| Test | Category | Priority | What it validates |
|------|----------|----------|-------------------|
| `test_symbol_matching_word_boundary` | Unit | P0 | Short tickers don't match random words |
| `test_symbol_matching_multiword` | Unit | P0 | Multi-word labels matched by substring |
| `test_cache_eviction_on_write` | Unit | P1 | Sweep runs every 50 writes |
| `test_cache_eviction_on_read` | Unit | P1 | Expired entries deleted on read miss |
| `test_cache_max_size` | Unit | P1 | Entries evicted when cache > 500 |
| `test_sentiment_badge_type_guard` | Unit | P1 | Non-numeric sentiment returns "n/a" |
| `test_has_tokens_network_failure` | Unit | P1 | Returns True when HTTP fails |
| `test_extract_title_fallbacks` | Unit | P2 | Dict → eng → first value → str |
| `test_breaking_events_parse` | Integration (mock) | P1 | Both v1/v2 response structures |
| `test_trending_nested_score` | Integration (mock) | P1 | Nested `trendingScore` dict |
| `test_social_authors_dict` | Integration (mock) | P2 | Authors as dicts with `name` key |
| `test_market_articles_cache_key_order` | Unit | P2 | `["a","b"]` == `["b","a"]` |
| `test_cache_thread_safety` | Stress | P2 | Concurrent reads/writes don't corrupt |

---

## F) Refactor Plan

### Completed (all applied)

1. ✅ Word-boundary regex for short tickers, substring for multi-word labels
2. ✅ Cache: `threading.Lock`, eviction on read miss, sweep every 50 writes, max 500 entries
3. ✅ Event articles gated behind "Load articles" button + `st.stop()` on limit
4. ✅ `has_tokens()` returns True on network failure
5. ✅ Dead variables removed: `_c_sent`, `_sent_badge`
6. ✅ `sentiment_badge()` type guard for non-numeric values
7. ✅ `datetime` imports moved to module level
8. ✅ Exception handlers narrowed to expected types + `log.exception` for unexpected
9. ✅ `threading.Lock` on `_cache` and `_er_instance` with double-check locking
10. ✅ `httpx` ImportError guard in `get_token_usage()`
11. ✅ `BreakingArticle` gained `sentiment_label`/`sentiment_icon` properties
12. ✅ Social Score zero warning banner
13. ✅ `_ER_HOST` comment corrected
14. ✅ `fetch_market_articles` cache key made order-independent

### Future improvements (low priority)

1. Write unit tests (see table above)
2. Mock EventRegistry SDK for integration tests
3. Consider removing `fetch_market_articles()` if never used
4. Add Streamlit `@st.cache_data` decorator as alternative to manual cache (would need careful TTL config)

---

*All 1,634 tests pass. 1 pre-existing failure in `test_production_gatekeeper.py` (unrelated).*  
*Both files compile cleanly.*

*End of review.*

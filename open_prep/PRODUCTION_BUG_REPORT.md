# Production Engineering Bug Report — open_prep

> **Scope:** 18 Python files reviewed in full (≈ 11,700 LOC)  
> **Focus:** Correctness, data contracts, reliability, performance, security, testability  
> **Style/formatting issues are excluded.**

---

## Table of Contents

1. [signal_decay.py](#1-signal_decaypy)
2. [scorer.py](#2-scorerpy)
3. [news.py](#3-newspy)
4. [macro.py](#4-macropy)
5. [alerts.py](#5-alertspy)
6. [technical_analysis.py](#6-technical_analysispy)
7. [run_open_prep.py](#7-run_open_preppy)
8. [screen.py](#8-screenpy)
9. [realtime_signals.py](#9-realtime_signalspy)
10. [playbook.py](#10-playbookpy)
11. [outcomes.py](#11-outcomespy)
12. [watchlist.py](#12-watchlistpy)
13. [trade_cards.py](#13-trade_cardspy)
14. [bea.py](#14-beapy)
15. [diff.py](#15-diffpy)
16. [regime.py](#16-regimepy)
17. [error_taxonomy.py](#17-error_taxonomypy)
18. [utils.py](#18-utilspy)

---

## 1. signal_decay.py

### HIGH — Half-life formula is mathematically wrong

- **Location:** `adaptive_freshness_decay()`, line ~103
- **Bug:** The function uses `math.exp(-elapsed_seconds / hl)` but the parameter is named and documented as `half_life`. The actual half-life of `exp(-t/τ)` is `τ * ln(2)` ≈ `0.693 * τ`, not `τ`. The function returns `1/e ≈ 0.368` at `t == hl`, not `0.5` as the name implies.
- **Impact:** A signal with a stated "10-minute half-life" actually decays to 50 % at ~6.93 minutes, meaning signals are treated as 30 % staler than intended. This systematically under-weights older signals versus the documented contract.
- **Fix:** Use `math.exp(-elapsed_seconds * math.log(2) / hl)` or rename the parameter to `time_constant` / `e_fold_time` to match semantics.

---

## 2. scorer.py

### HIGH — Score component 40 % cap uses pre-cap total as denominator

- **Location:** `score_candidate()`, lines ~465-490
- **Bug:** `_total_positive` is computed as the sum of *all* uncapped positive components, then `_cap = 0.40 * _total_positive`. Each component is subsequently capped to `_cap`. But after capping one dominant component, the remaining components are still capped against the **original uncapped total**, not the new effective total. This means one component can be capped to 40 %, but the cap value is inflated by the very component that was capped.
- **Impact:** Scenario: gap_component = 8.0, all others = 0.5 each (sum of 13 others = 6.5). `_total_positive = 14.5`, `_cap = 5.8`. Gap is capped from 8.0 → 5.8 (= 40 % of 14.5). But 5.8 / (5.8+6.5) = 47.1 % of post-cap total, violating the intended 40 % invariant. The score is slightly more concentrated in the dominant component than the 40 % cap promises.
- **Fix:** Apply iterative re-capping: after capping, recompute `_total_positive` from capped values and repeat until stable, or accept 40 % of *post-cap* total as the threshold.

### MEDIUM — `macro_component` only rewards positive bias

- **Location:** `score_candidate()`, line ~442
- **Bug:** `macro_component = w["macro"] * max(bias, 0.0)` — a negative macro bias is **not** passed to the score as a negative component. It's clamped to 0 before multiplication. The separate `risk_off_penalty` partially compensates but uses a different weight key, so the magnitude is decoupled from `w["macro"]`. A `bias = -0.80` and `bias = 0.0` produce identical `macro_component`.
- **Impact:** Negative macro environments are under-penalised in the composite score vs. what the weight configuration intends. Scores cluster higher than they should on risk-off days.
- **Fix:** Intentional design decision? If so, document it. If not, allow `macro_component` to go negative when bias is negative.

### MEDIUM — `freshness_decay` uses `signal_decay.adaptive_freshness_decay` but `elapsed_seconds` may be `None`

- **Location:** `filter_candidate()`, lines ~320-335
- **Bug:** When `premarket_freshness_sec` is `None` (quote has no timestamp), the code passes `None` to `adaptive_freshness_decay()`, which returns `0.0`. A `freshness_decay = 0.0` then contributes `w["freshness_decay"] * 0.0 = 0.0` to the score. This means symbols without any timestamp data receive **zero freshness credit**, which is harsher than a moderately stale score. The intent is likely "no data → neutral default" rather than "no data → maximally penalised".
- **Impact:** Symbols that lack `premarket_freshness_sec` (common for some FMP data tiers) are scored as maximally stale, artificially depressing their ranking relative to peers with any timestamp.
- **Fix:** Default `freshness_decay` to `0.5` or `1.0` when `premarket_freshness_sec is None`.

---

## 3. news.py

### MEDIUM — Article sort for "newest first" uses ISO string comparison, not datetime

- **Location:** `build_news_scores()`, lines ~232-237
- **Bug:** `row["articles"].sort(key=lambda a: a.get("date") or "", reverse=True)` sorts articles by their `date` field, which is an ISO 8601 string. ISO sort is generally correct for lexicographic ordering, but:
  - Articles with `None` date sort to the end (empty string is smallest), which is intentional.
  - However, mixed timezone formats (e.g. `"+00:00"` vs `"Z"`) and presence/absence of microseconds produce incorrect ordering. `"2025-06-03T14:30:00.654321+00:00"` > `"2025-06-03T15:30:00+00:00"` lexicographically (`.` > `+` in ASCII), even though 15:30 is later.
- **Impact:** The "best" (newest) article used for per-symbol sentiment is occasionally wrong, leading to incorrect `event_class`, `materiality`, `is_actionable` being propagated to the playbook engine.
- **Fix:** Parse dates to `datetime` objects for sorting, or normalise all dates to the same format (no microseconds, `+00:00` suffix) before comparison. The `latest_article_utc` tracking correctly uses datetime comparison — apply the same approach to the sort.

### LOW — `_parse_article_datetime` tolerates future dates

- **Location:** `_parse_article_datetime()` (line ~100) + `build_news_scores()` guard at line ~220
- **Bug:** The function parses any date string without clamping. The code at line ~220 guards against future dates for recency-window counting (`if window_24h <= article_dt <= now`) but the article still appears in `articles` list and can become the "best" article for playbook enrichment even if it's future-dated.
- **Impact:** A provider timezone-drift article dated 2 hours in the future lands as `arts[0]` (newest), which drives `event_class` etc. for that symbol.
- **Fix:** Filter future-dated articles from the `articles` list before the sort, or clamp `article_dt = min(article_dt, now)`.

---

## 4. macro.py

### HIGH — CircuitBreaker is not thread-safe

- **Location:** `CircuitBreaker.__init__()`, lines ~40-55, `record_success()`, `record_failure()`
- **Bug:** The `CircuitBreaker` instance is shared across all threads via `FMPClient._circuit_breaker`. `_consecutive_failures`, `_state`, and `_opened_at` are read/written without any locking. With `ThreadPoolExecutor` parallelism in `_atr14_by_symbol()` (up to 8 workers) and `_fetch_premarket_high_low_bulk()` (6 workers), concurrent calls to `_get()` can race on `record_success()` / `record_failure()`, causing:
  - Lost failure counts (two threads increment concurrently, only +1 is recorded)
  - State torn reads (one thread sees HALF_OPEN, another sees CLOSED simultaneously)
  - Premature circuit-open or missed circuit-open because `_consecutive_failures` is under-counted
- **Impact:** Under heavy parallel load, the circuit breaker may either fail to trip (allowing a flood of requests to a down API) or trip prematurely on a spurious race, silently dropping enrichment data. Both degrade ranking quality without any error trail.
- **Fix:** Use `threading.Lock` to guard state mutations, or use `threading.atomic` counters. Alternatively, make the circuit breaker per-thread (but this reduces its effectiveness as a global rate-protector).

### MEDIUM — CSV fallback in `_get()` uses fragile type coercion heuristic

- **Location:** `_get()`, lines ~270-290
- **Bug:** The CSV parser attempts `int(v) if v.isdigit() else float(v)` for every value. This fails for:
  - Negative numbers (e.g. `"-0.5"` → `v.isdigit()` is False, `float(v)` succeeds, OK)
  - But strings like `"1e5"` or `"NaN"` are coerced to float silently (`float("NaN")` succeeds)
  - ISO date strings like `"2025-06-03"` are kept as strings (OK)
  - Empty strings `""` → `v.isdigit()` is False, `float("")` raises ValueError → kept as `""` (OK)
  
  The real issue: `v.isdigit()` returns False for `"0"` on some edge platforms (it shouldn't, but) and always returns False for negative integers like `"-42"`, so those become floats (42.0) instead of ints.
- **Impact:** Downstream code expecting `int` market-cap values may get `float`, causing type-check failures in strict comparisons. Low practical impact since the CSV fallback is rare.
- **Fix:** Try `int(v)` first in a try/except, then `float(v)`, then keep as string. Or use `ast.literal_eval` with a safety wrapper.

### LOW — `_get()` re-creates `Request` object on every retry

- **Location:** `_get()`, line ~230 (loop body)
- **Bug:** The `Request` object is constructed once before the loop at line ~225, but `urlopen()` may consume internal state. Since `Request` objects are lightweight and `urlopen` doesn't mutate them, this is **not** a correctness bug, but the `request` reference shadows the module-level `Request` import. No actual issue — included for completeness.

---

## 5. alerts.py

### MEDIUM — In-memory throttle state resets on process restart

- **Location:** `_last_sent` dict, line ~89
- **Bug:** Throttle state is stored only in `_last_sent: dict[str, float] = {}`. When the process restarts (common in cron/Streamlit/container deployments), all throttle history is lost. The same alert fires again immediately.
- **Impact:** Every restart window produces duplicate alerts. In a Streamlit auto-reload scenario, reloading the page can trigger a burst of alerts for the same symbols.
- **Fix:** Persist `_last_sent` to a file (e.g. `artifacts/open_prep/alert_throttle.json`) using the same atomic-write pattern used elsewhere. Load on import, save on `_mark_sent()`.

### MEDIUM — TradersPost payload uses `prev_close` instead of current price

- **Location:** `_format_traderspost_payload()`, line ~132
- **Bug:** `"price": candidate.get("prev_close")` — this sends the *previous day's close* as the alert price, not the current/premarket price. TradersPost expects the intended entry price.
- **Impact:** Downstream order-execution or display may use a stale price, resulting in missed fills or incorrect position sizing.
- **Fix:** Use `candidate.get("price")` or `candidate.get("premarket_price")` or the indicative price that drove the signal.

### LOW — SSL context is rebuilt per webhook call

- **Location:** `_send_webhook()`, lines ~285-290
- **Bug:** Every call to `_send_webhook()` creates a new `ssl.SSLContext` and attempts to import `certifi`. This is wasteful but not incorrect.
- **Fix:** Hoist `ssl_ctx` to module level or cache as a module-global.

---

## 6. technical_analysis.py

### MEDIUM — `calculate_support_resistance_targets` swallows all exceptions

- **Location:** `calculate_support_resistance_targets()` (outer try/except wrapping entire function body, line ~400-550)
- **Bug:** The function catches `except Exception` at the outermost level and returns a neutral fallback dict. This hides bugs in the S/R calculation (e.g. division by zero, bad OHLCV data, logic errors) without any logging or re-raise option.
- **Impact:** If S/R calculation silently fails, trade cards show `None` stop-loss/targets, and downstream consumers (realtime engine, alert formatting) cannot distinguish "no S/R data" from "calculation bug". Debugging production issues requires reproducing exact inputs.
- **Fix:** Log the exception at WARNING/ERROR level inside the catch. Consider re-raising on non-data errors (e.g. `TypeError`, `AttributeError`).

### MEDIUM — `detect_breakout` `min_bars` check is over-conservative

- **Location:** `detect_breakout()`, line ~273
- **Bug:** `min_bars = max(short_n, long_n) + 5`. With default `short_n=30, long_n=60`, this requires 65 bars. But the function only accesses `closes[-short_n:]`, `closes[-long_n:]`, and `volumes[-50:]`. 50 bars would suffice for all array accesses. The `+5` padding and `max(short_n, long_n)` overcount by ~20 %.
- **Impact:** Symbols with 50-64 daily bars are classified as `"insufficient_data"` and miss breakout detection, even though the data is sufficient. This is common for recently-IPO'd names (3-4 months of history).
- **Fix:** Use `min_bars = max(short_n, long_n)` without the `+5` padding, or compute the actual minimum from the accesses.

### LOW — `_ema()` returns `NaN` for empty input

- **Location:** `_ema()`, line ~260
- **Bug:** Function returns `float("nan")` when `values` is empty. Callers (e.g. `detect_breakout`) check `ema_20 != ema_20` (NaN self-comparison) before use, which works, but this NaN can propagate if a new caller forgets the check.
- **Impact:** Low — existing callers handle it. Noted for defensive maintainability.

---

## 7. run_open_prep.py

### HIGH — `_save_atr_cache` / `_save_atr_cache`: `prev_close_map` key-case mismatch

- **Location:** `_save_atr_cache()`, lines ~2060-2080, vs `_incremental_atr_from_eod_bulk()`, line ~2115
- **Bug:** In `_save_atr_cache`, the `clean_prev_close_map` is keyed by `str(k).upper()` from `clean_atr_map` keys. But `prev_close_map` is populated from `cached_prev_close` (upper-cased) merged with `incremental_close` (which keys are whatever `eod_row` returned). If `eod_row` returns lowercase symbols, the `prev_close_map.get(k)` lookup uses the upper-cased `k` from `clean_atr_map`, which misses the lowercase key in `prev_close_map`, yielding `0.0`.
- **Impact:** `prev_close` values silently become `0.0` in the cache when EOD bulk returns lowercase symbols. On next-day incremental ATR update, `prev_close <= 0.0` causes the symbol to be skipped in `_incremental_atr_from_eod_bulk()`, forcing an expensive per-symbol fallback fetch.
- **Fix:** Normalise `incremental_close` keys to `.upper()` before merging into `prev_close_snapshot`.

### HIGH — Race condition in ThreadPoolExecutor + circuit breaker during ATR fetch

- **Location:** `_atr14_by_symbol()`, lines ~2170-2210 (ThreadPoolExecutor) + `_fetch_symbol_atr()` (line ~2140)
- **Bug:** Multiple `_fetch_symbol_atr` threads call `client.get_historical_price_eod_full()`, which calls `_get()`, which calls `_circuit_breaker.record_success()/record_failure()` — all sharing the same unsynchronised `CircuitBreaker` instance. (This is the same circuit-breaker thread-safety issue as in macro.py but materialises here due to `parallel_workers=8`.)
- **Impact:** Under burst API errors (e.g. FMP returns 5 consecutive 500s), the failure counter may under-count due to races, preventing the circuit from tripping. Conversely, a single slow 504 response during half-open could cause a spurious re-open while another thread succeeds.

### MEDIUM — `_fetch_premarket_high_low_bulk` silently drops results on timeout

- **Location:** `_fetch_premarket_high_low_bulk()`, lines ~2450-2490
- **Bug:** When `as_completed(futs, timeout=timeout_arg)` raises `FuturesTimeoutError`, the code cancels pending futures and continues. But the result of already-completed-but-not-yet-yielded futures is lost. `as_completed()` may have buffered results that were completed before the timeout but not yet iterated. After the `except FuturesTimeoutError`, only `out.setdefault()` runs, setting missing symbols to `None`.
- **Impact:** Some symbols that were actually fetched successfully are reported as `premarket_high=None, premarket_low=None` despite the data being available in the completed future. This under-reports PMH/PML.
- **Fix:** After timeout, iterate `futs` and check `fut.done()` — extract results from completed futures before defaulting.

### MEDIUM — `_compute_gap_for_quote` returns different dict shapes

- **Location:** `_compute_gap_for_quote()`, lines ~1730-1870
- **Bug:** The function returns dicts with inconsistent key sets depending on the code path:
  - The `not is_gap_session` path includes `"overnight_gap_pct"` and `"overnight_gap_source"`.
  - All other paths omit these keys.
  
  Downstream consumers that do `row.get("overnight_gap_pct")` handle this gracefully, but `build_gap_scanner()` (line ~3880) accesses `q.get("overnight_gap_pct")` and will get `None` for gap-session rows rather than the expected `0.0`. Since it falls back to `0.0`, this is functionally OK but creates an implicit contract that's easy to violate.
- **Impact:** Low risk now, but a future consumer doing `if row["overnight_gap_pct"]:` will get `KeyError` on gap-session rows.
- **Fix:** Always include `overnight_gap_pct` and `overnight_gap_source` in the returned dict (set to `None` when not computed).

### MEDIUM — Breakout/consolidation enrichment uses ATR% proxy, not real ADX/BB data

- **Location:** `generate_open_prep_result()`, lines ~3660-3700
- **Bug:** `approx_bb_width = max(atr_pct * 2.5, 0.1)` and `approx_adx = min(max(atr_pct * 8.0, 5.0), 60.0)` are linear proxies of Bollinger Band width and ADX, derived solely from ATR%. These proxies have no empirical basis:
  - ATR% and ADX measure different things (volatility vs. trend strength)
  - A high-ATR% stock can be ranging (high ADX is not implied)
  - `atr_pct * 8.0` maps a 3% ATR stock to ADX=24 (borderline trending), and a 1% ATR stock to ADX=8 (strongly ranging), but a 1% ATR large-cap can be in a strong trend
- **Impact:** The `symbol_regime`, `consolidation`, `is_consolidating`, and `consolidation_score` fields in `ranked_v2` are unreliable proxies. Playbooks that key off `is_consolidating` or `symbol_regime` may make systematic errors (e.g. classifying trending large-caps as "RANGING").
- **Fix:** Either (a) fetch real ADX/BB data from FMP's technical indicators endpoint, (b) compute ADX from the daily bars already fetched in `_daily_bars_cache`, or (c) clearly label these as "proxy" fields in the output contract with a data-quality caveat.

### MEDIUM — `_incremental_atr_from_eod_bulk` momentum_z carries stale prior-day value

- **Location:** `_incremental_atr_from_eod_bulk()`, lines ~2123-2130
- **Bug:** The code explicitly copies `momentum_z` from the prior-day cache: `momentum_map[sym] = round(_to_float(prev_momentum_map.get(sym), default=0.0), 4)`. This is documented as a known limitation ("may lag by ~1 session"). However, the full-refresh path in `_fetch_symbol_atr` computes fresh `momentum_z` via `_momentum_z_score_from_eod()`.
- **Impact:** The staleness compounds: if the cache hits for many consecutive days (incremental path), `momentum_z` can be multiple days old. A stock transitioning from bearish to bullish momentum retains its old negative z-score.
- **Fix:** Compute `momentum_z` from EOD bulk data in the incremental path (requires 50-day lookback, but the bulk response usually contains sufficient history), or annotate the field with `"momentum_z_stale": True` so downstream can discount it.

### LOW — `_evict_stale_cache_files` uses `time.time()` as import trick

- **Location:** `_evict_stale_cache_files()`, line ~2038
- **Bug:** `import time as _time_mod` inside the function body shadows the module-level `time` import. Functional but unnecessarily confusing; `time.time()` is already available at module scope.
- **Fix:** Remove the local import; use the module-level `time`.

### LOW — `_is_likely_us_equity_symbol` may classify SPAC symbols incorrectly

- **Location:** function not fully reviewed but used at line ~3510
- **Bug:** The heuristic for "likely US equity" is based on symbol length and character class. SPACs (e.g. `PSTH.WS`, `SPAK`) may be incorrectly included or excluded depending on the regex.
- **Impact:** Foreign symbols may contaminate the earnings calendar; SPAC warrants may be incorrectly ranked as common equity.

---

## 8. screen.py

### MEDIUM — `rank_candidates` duplicates scoring logic from `scorer.py`

- **Location:** `rank_candidates()` (entire function, lines ~300-514)
- **Bug:** The legacy ranker implements its own scoring formula (gap × weight + rvol × weight + …) that is structurally similar to but numerically different from `scorer.py`'s `score_candidate()`. Both are called in `generate_open_prep_result()` — legacy for `ranked`, v2 for `ranked_v2`. The two scoring functions assign different weights, apply different caps, and handle edge cases differently.
- **Impact:** `ranked` and `ranked_v2` can disagree significantly on symbol ordering. Consumers reading `ranked_candidates` vs `ranked_v2` get inconsistent views. If the legacy path is retained for backward compatibility, this is by design, but any bug fix in one scorer must be manually replicated in the other.
- **Fix:** Document the intentional duality or deprecate the legacy path. At minimum, ensure both are tested against the same reference inputs to catch drift.

### LOW — `_to_float` with `default=0.0` silently converts missing data to zero

- **Location:** `_to_float()` used >50 times in screen.py
- **Bug:** When FMP returns `None` for `previousClose`, `avgVolume`, etc., `_to_float(None, default=0.0)` returns `0.0`. A `previousClose = 0.0` then triggers "missing_previous_close" in gap computation (correct), but an `avgVolume = 0.0` makes `volume_ratio = 0.0`, which is used as a ranking signal. The code cannot distinguish "FMP returned 0 volume" from "FMP returned no data".
- **Fix:** Use `float("nan")` as default where the distinction matters, and check with `val == val` (NaN self-compare pattern already used elsewhere).

---

## 9. realtime_signals.py

### MEDIUM — `_quote_hash` uses MD5 with truncation to 16 chars

- **Location:** `_quote_hash()`, line ~90
- **Bug:** `hashlib.md5(raw.encode()).hexdigest()[:16]` — 16 hex chars = 64 bits of hash space. For change-detection on ~500 symbols polled every few seconds, the collision probability per cycle is ~`n²/2^65`. With 500 symbols and 86400/5 ≈ 17,280 cycles/day, the cumulative collision probability per day is effectively negligible (~10⁻¹⁰).
- **Impact:** Practically zero collision risk. Noted only because MD5 is deprecated for cryptographic use; for non-security hash comparisons it's fine. Using SHA-256 would be equally fast and avoid MD5 in audits.
- **Fix:** Optional: replace with `hashlib.sha256(...).hexdigest()[:16]`.

### MEDIUM — `poll_once()` imports `newsstack_fmp` inside the function body

- **Location:** `poll_once()`, line ~450 (approximate)
- **Bug:** `from newsstack_fmp import ...` is called on every poll cycle. If `newsstack_fmp` is unavailable (optional dependency), the `ImportError` is caught and news integration is silently disabled, which is correct. But the repeated import attempt adds overhead on every poll cycle (~17,000/day).
- **Impact:** Minor CPU overhead. If `newsstack_fmp` raises `ImportError`, it's re-attempted every cycle instead of being cached as unavailable.
- **Fix:** Cache the import result at module level: `_newsstack = None` / try-import once.

### LOW — `GateHysteresis.should_fire()` state persists indefinitely

- **Location:** `GateHysteresis` class (lines ~60-90)
- **Bug:** The `_last_fired` dict grows unboundedly as new symbols are tracked. There's no eviction of symbols that haven't been seen in days.
- **Impact:** Memory growth in long-running processes. With ~500 symbols and 8-byte timestamps, this is <50 KB — negligible.

---

## 10. playbook.py

### MEDIUM — `classify_news_event` iterates all patterns without short-circuit on certainty

- **Location:** `classify_news_event()`, lines ~200-400
- **Bug:** The function iterates through all `NEWS_EVENT_PATTERNS` even after finding a high-confidence match. The first match wins (due to `break` after `if matched`), but the patterns are checked in list order, not by specificity or materiality.
- **Impact:** If a more-specific pattern appears later in the list than a less-specific one, the less-specific match is used. For example, if "FDA approval" appears after "regulatory", an article about FDA approval is classified as generic "regulatory" rather than the more valuable "fda_approval".
- **Fix:** Ensure patterns are ordered from most-specific to least-specific, or score all matches and pick the highest-materiality one.

### LOW — `assign_playbooks` does not validate that `candidates` and result list are same length

- **Location:** `assign_playbooks()` return, line ~860
- **Bug:** The `zip(ranked_v2, playbook_results)` in `generate_open_prep_result()` (line ~3710) assumes both lists have the same length. If `assign_playbooks` filters or drops candidates internally, the zip will silently truncate.
- **Impact:** Currently safe because `assign_playbooks` maps 1:1, but fragile against future refactors.

---

## 11. outcomes.py

### MEDIUM — Feature importance uses Pearson correlation for binary outcomes

- **Location:** `FeatureImportanceCollector.compute_importance()`, lines ~350-400
- **Bug:** The code computes Pearson correlation between continuous features (gap_pct, volume_ratio, score) and a binary outcome (profitable_30m: 0/1). Pearson correlation between a continuous variable and a binary variable is mathematically the point-biserial correlation, which is valid, but:
  - With small sample sizes (ring buffer of 100), the correlation is highly unstable
  - Features with skewed distributions (volume_ratio) produce misleading correlations
  - No statistical significance test is applied
- **Impact:** Feature importance rankings may suggest a feature is important purely due to sample noise, leading to false confidence in weight adjustments.
- **Fix:** Add a minimum sample-size gate (e.g. n ≥ 30), report confidence intervals, or switch to a rank-based metric (Spearman's rho) that's more robust to outliers.

### LOW — File rotation uses calendar days, not trading days

- **Location:** `store_daily_outcomes()`, lines ~240-260
- **Bug:** Outcome files are retained by calendar-day count (`max_age_days=30`). On weekends and holidays, no new files are created, but the retention window counts those days. Effectively, 30 calendar days retains ~21 trading days of data.
- **Impact:** Less backward-validation data than the configured 30-day window implies. Misleads operators counting trading days.

---

## 12. watchlist.py

### MEDIUM — `fcntl`-based file locking is POSIX-only; no-op on Windows

- **Location:** `_lock_file()` / `_unlock_file()`, lines ~30-50
- **Bug:** The code correctly tries `import fcntl` and falls back to a no-op on `ImportError` (Windows). However, the no-op fallback means concurrent processes on Windows can corrupt the watchlist JSON file.
- **Impact:** On POSIX (Linux/macOS production): no issue. On Windows dev environments: potential data loss if two processes write simultaneously.
- **Fix:** Document the limitation or use `msvcrt.locking()` on Windows for advisory locking.

### LOW — `auto_add_high_conviction` always appends, never deduplicates against existing watchlist

- **Location:** `auto_add_high_conviction()`, line ~160-180
- **Bug:** If the same symbol re-qualifies as HIGH_CONVICTION on the next run, it's appended again (with a newer timestamp). The watchlist grows with duplicates.
- **Impact:** UI displays duplicate entries. The `get_watchlist_symbols()` function returns a list (not set), so duplicates affect downstream logic that counts symbols.
- **Fix:** Check if symbol already exists before appending, or use `setdefault` on symbol key.

---

## 13. trade_cards.py

### MEDIUM — ATR trailing stop assumes long-only direction

- **Location:** `_compute_trailing_stop()`, lines ~140-160
- **Bug:** The trailing stop is always calculated as `entry_price - (atr * atr_multiple)`. For a short/fade playbook (bearish), the stop should be `entry_price + (atr * atr_multiple)`. The playbook engine can assign `FADE` strategy, but the trade card always computes a long-side stop.
- **Impact:** Trade cards for FADE/short-biased signals show a stop-loss below entry (wrong direction). A trader following these cards would have no upside protection.
- **Fix:** Accept a `direction` parameter and invert the stop calculation for short signals.

### LOW — S/R target levels may be `None` without fallback

- **Location:** `build_trade_cards()`, lines ~200-248
- **Bug:** When `calculate_support_resistance_targets()` returns `None` for levels (insufficient bar data), the trade card includes `"target_1": None, "target_2": None`. There's no fallback to ATR-based targets.
- **Impact:** Trade cards with `None` targets provide incomplete guidance. Downstream UIs must handle `None` display.

---

## 14. bea.py

### LOW — HTML scraping is fragile and BEA-specific

- **Location:** `_fetch_bea_release_url()`, lines ~50-100
- **Bug:** The function scrapes BEA's HTML page for a release URL using string matching. If BEA changes their HTML layout, the scraper silently fails (returns `None`). This is by design (fail-open), but there's no alerting or metric when the scraper breaks.
- **Impact:** BEA audit becomes a permanent no-op without anyone noticing.
- **Fix:** Log at WARNING level when the scraper finds no match. Add a health-check metric (e.g. count of successful scrapes per week).

### LOW — No rate limiting on BEA HTTP requests

- **Location:** `_fetch_bea_release_url()` uses `urlopen()` directly
- **Bug:** Each pipeline run fetches the BEA page. With multiple runs per day (e.g. Streamlit refresh), this could trigger BEA rate limiting.
- **Impact:** Unlikely at current scale but worth noting.

---

## 15. diff.py

### LOW — `compute_diff` assumes `prev_snapshot` and `current_snapshot` have identical schema

- **Location:** `compute_diff()`, lines ~100-225
- **Bug:** If `prev_snapshot` was written by an older code version with different fields, missing keys in old candidates cause `KeyError` when computing diff fields.
- **Impact:** After a code upgrade that adds new fields to `ranked_v2`, the first diff computation may fail or produce partial results.
- **Fix:** Use `.get()` with defaults for all accessed fields in the diff computation.

---

## 16. regime.py

### MEDIUM — `classify_regime` VIX thresholds produce regime flicker

- **Location:** `classify_regime()`, lines ~200-280
- **Bug:** The regime transitions are based on instantaneous VIX level: `vix > 30 → RISK_OFF`, `vix < 15 → RISK_ON`. When VIX oscillates around 30 (common during moderate stress), the regime alternates between RISK_OFF and NEUTRAL every run. This causes:
  - Alternating weight adjustments (regime-adjusted weights change every run)
  - Spurious regime-change alerts (one per run)
  - Diff noise (every run shows "regime changed")
- **Impact:** Weight instability makes score comparisons across consecutive runs unreliable. Alert fatigue from false regime-change notifications.
- **Fix:** Add hysteresis: require VIX to cross 30 for entry to RISK_OFF but only exit at 27 (3-point dead-band). Store prior regime in state to implement this.

### LOW — `sector_breadth` defaults to 0.0 when sector_performance is empty

- **Location:** `classify_regime()`, line ~220
- **Bug:** When `sector_performance` is empty (FMP endpoint unavailable), `sector_breadth = 0.0`, which signals "no breadth data" and "zero breadth" identically. Zero breadth contributes to ROTATION regime classification.
- **Fix:** Use `None` for "no data" and handle it separately in the regime logic.

---

## 17. error_taxonomy.py

### LOW — Retry decorator does not propagate exception chain on exhaustion

- **Location:** `retry()`, wrapper function, lines ~105-120
- **Bug:** The final `raise last_exc` at the end of the loop (line ~120) is a fallback that theoretically shouldn't be reached (the `if attempt >= attempts: raise` inside the loop should fire first). But if it does fire, `raise last_exc` raises without context (no `from` clause), losing the original stack trace.
- **Impact:** In rare edge cases, the traceback may be incomplete, making debugging harder.
- **Fix:** Use `raise last_exc from last_exc` or simply remove the final guard since it's dead code.

---

## 18. utils.py

### LOW — `to_float` defaults to `0.0`, making missing data indistinguishable from zero

- **Location:** `to_float()`, lines ~1-27
- **Bug:** `to_float(None) → 0.0`, `to_float(0) → 0.0`. Callers cannot distinguish "FMP returned 0" from "FMP returned nothing". This propagates through the entire codebase (used 200+ times across files).
- **Impact:** Systematically, missing data is treated as zero rather than unknown. For most metrics (volume, price, ATR), zero triggers protective guards. For `previousClose = 0.0`, gap computation correctly detects this as missing. But for `avgVolume = 0.0`, relative volume becomes `0/0 → 0.0`, meaning "no volume data" is scored identically to "zero trading volume".
- **Fix:** This is a deep architectural choice. Changing the default to `NaN` would require auditing all 200+ call sites. Document the convention and ensure critical paths (gap, rvol, ATR) have explicit None-awareness.

---

## Cross-Cutting Issues

### HIGH — No integration test coverage for the pipeline

- **Location:** All files
- **Bug:** There are no test files in `open_prep/` (except `test_slim_parity.py` which tests a different module). The pipeline relies on live FMP API calls with no mock/stub layer. This makes it impossible to:
  - Verify score computation determinism
  - Catch regressions in gap/ATR/premarket enrichment
  - Validate the data contract between pipeline stages
- **Impact:** Any change to any of the 18 files risks silent breakage. The scorer cap bug (#2) and half-life bug (#1) would have been caught by unit tests.
- **Fix:** Create a `tests/` directory with:
  - Unit tests for `scorer.score_candidate()` with known inputs
  - Unit tests for `signal_decay.adaptive_freshness_decay()` verifying actual half-life
  - Integration test for `generate_open_prep_result()` with a mocked `FMPClient`

### MEDIUM — Atomic writes don't persist `fsync` before `os.replace`

- **Location:** `_save_atr_cache()`, `_pm_cache_save()`, `save_alert_config()`, `_save_result_snapshot()`, latest-run JSON write — all use `mkstemp + os.write + os.replace` pattern
- **Bug:** None of the atomic-write sites call `os.fsync(fd)` before `os.close(fd)`. On crash/power-loss between `os.close()` and `os.replace()`, the file content may be lost or partially written (file system write-back cache hasn't flushed). On Linux with ext4 default mount options (`data=ordered`), this is usually safe but not guaranteed. On macOS (APFS), `os.replace` is atomic but the content may not be durable.
- **Impact:** On unexpected system crash, cache files may be empty or corrupted. Pipeline gracefully recovers (cache miss → full re-fetch), but alert config or watchlist could be lost.
- **Fix:** Add `os.fsync(fd)` before `os.close(fd)` in all atomic-write helpers.

### MEDIUM — FMP API key appears in URL; no credential rotation support

- **Location:** `macro.py` `_get()`, line ~225
- **Bug:** The API key is passed as a query parameter: `query["apikey"] = self.api_key`. While the code carefully masks URLs in logs (`masked_url`), the key is present in:
  - `RuntimeError` messages (e.g. `FMP API HTTP 401 on /api/v3/...`) — the path doesn't include the key, so this is actually OK
  - Exception tracebacks that include local variables (`url` contains the key)
  - The `Request` object which is part of the local stack frame
- **Impact:** If exceptions with tracebacks are sent to an external logging service (Sentry, Datadog), the API key could leak.
- **Fix:** Strip the `apikey` parameter from the URL before including it in exception messages, or use HTTP headers for authentication (FMP supports `Authorization` header for some tiers).

---

## Summary by Severity

| Severity | Count | Key Items |
|----------|-------|-----------|
| **HIGH** | 5 | Half-life formula wrong; score cap invariant violated; circuit breaker not thread-safe (×2 locations); no test coverage |
| **MEDIUM** | 18 | Throttle state lost on restart; TradersPost wrong price; article sort by string; momentum_z staleness; regime flicker; proxy ADX/BB; PMH/PML data loss on timeout; and others |
| **LOW** | 14 | NaN propagation; EMA edge case; cache eviction micro-issues; BEA fragility; fsync omission; and others |

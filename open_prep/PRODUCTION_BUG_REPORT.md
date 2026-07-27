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

### RESOLVED (2026-07-06, PR #3217) — Half-life formula is mathematically wrong

- **Resolution:** `adaptive_freshness_decay` now uses `math.exp(-elapsed_seconds * _LN2 / hl)` (`_LN2 = math.log(2)`) — the true half-life form recommended below. Verified empirically: decay is exactly `0.5` at `t == hl` and `0.25` at `2·hl` (the old `exp(-t/hl)` gave `0.368`). The module docstring documents the contract. Historical description retained below; do not re-file.
- **Location:** `adaptive_freshness_decay()`, line ~103
- **Bug:** The function uses `math.exp(-elapsed_seconds / hl)` but the parameter is named and documented as `half_life`. The actual half-life of `exp(-t/τ)` is `τ * ln(2)` ≈ `0.693 * τ`, not `τ`. The function returns `1/e ≈ 0.368` at `t == hl`, not `0.5` as the name implies.
- **Impact:** A signal with a stated "10-minute half-life" actually decays to 50 % at ~6.93 minutes, meaning signals are treated as 30 % staler than intended. This systematically under-weights older signals versus the documented contract.
- **Fix:** Use `math.exp(-elapsed_seconds * math.log(2) / hl)` or rename the parameter to `time_constant` / `e_fold_time` to match semantics.

---

## 2. scorer.py

### RESOLVED (2026-07-02, PR #3114) — Score component 40 % cap uses pre-cap total as denominator

- **Resolution:** Der Pre-Cap-Denominator ist jetzt das *dokumentierte, beabsichtigte*
  Design. Der hier ursprünglich vorgeschlagene Fix („iterative re-capping … repeat
  until stable") wurde implementiert und **zurückgebaut**: Er ist mathematisch
  nicht-konvergent, sobald weniger als drei vergleichbare positive Komponenten
  existieren, und crushte dominante Komponenten geometrisch auf `raw * 0.40**5`
  (~1 % des Werts). Den Loop **nicht** wieder einführen.
- **Analyse & Regression-Guard:** `tests/test_scorer_component_cap_convergence.py`,
  Kommentar `#8 Score Component Cap` in `open_prep/scorer.py`.

### MEDIUM (NEW 2026-07-27) — §15 SYMBOL-layer regime weights never fire

- **Location:** `score_candidate()` feature build — `"symbol_regime": detect_symbol_regime(adx=..., bb_width_pct=...)`
  (scorer.py:533-536) and its use at scorer.py:577-578.
- **Bug:** The regime is derived from `quote.get("adx")` / `quote.get("bb_width_pct")`. **No producer
  populates either key** on the premarket quote path, so the `_to_float` fallbacks (`15.0` / `3.0`)
  always apply. `detect_symbol_regime(15.0, 3.0)` returns `"NEUTRAL"`, and `resolve_regime_weights`
  applies no tilt for `NEUTRAL` — verified empirically: with the defaults **not one weight changes**,
  while real inputs move five (`gap`, `gap_sector_relative`, `rvol`, `momentum_z`, `ext_hours`, e.g.
  `adx=30 / bb=5 → TRENDING`). The comment at scorer.py:576 describes the adjustment as compounding
  with the market tilt; in production it is a no-op.
- **Why the data is missing:** the measured indicators *are* computed in the same run
  (`compute_adx_from_bars` / `compute_bb_width_pct_from_bars`, run_open_prep.py:5762-5763) but from
  `_daily_bars_cache`, which is only built at run_open_prep.py:5698 — **after** `rank_candidates_v2`
  (run_open_prep.py:5596). The values exist too late to reach the scorer.
- **Impact:** Trade-affecting. A documented weight-adaptation layer silently contributes nothing, so
  gap/rvol/momentum weighting is regime-blind at the symbol level. Also a truth defect: the
  enrichment stage later **overwrites** `row["symbol_regime"]` with the measured value, making the
  emitted row look as though scoring used it.
- **Status:** shadow measurement landed first (`open_prep/regime_shadow.py` +
  `row["regime_weight_shadow"]` / `row["symbol_regime_at_scoring"]`) so the ranking impact can be
  quantified on real runs before the weights are wired up. Wiring requires hoisting the daily-bars
  fetch above the scoring stage — not a one-line change.

### MEDIUM (IMPACT CORRECTED 2026-07-27) — `macro_component` only rewards positive bias

- **Correction:** The *mechanism* below is accurate, but the stated **impact is inverted** — this
  is by-design asymmetry, not under-penalisation. A negative bias is routed through
  `risk_off_penalty = abs(min(bias, 0.0)) * w["risk_off_penalty_multiplier"]` (scorer.py, multiplier
  `2.0`) and **subtracted**. Measured against `DEFAULT_WEIGHTS` (`macro = 0.7`): `bias = +0.8` nets
  `+0.56`, `bias = -0.8` nets `-1.60` — risk-off is penalised ~2.9× harder than upside is rewarded,
  so scores do **not** "cluster higher on risk-off days". Letting `macro_component` go negative (the
  fix proposed below) would double-count the penalty and **weaken** the model. Do not "fix" this;
  the remaining task is documentation only.
- **Location:** `score_candidate()`, line ~442
- **Bug:** `macro_component = w["macro"] * max(bias, 0.0)` — a negative macro bias is **not** passed to the score as a negative component. It's clamped to 0 before multiplication. The separate `risk_off_penalty` partially compensates but uses a different weight key, so the magnitude is decoupled from `w["macro"]`. A `bias = -0.80` and `bias = 0.0` produce identical `macro_component`.
- **Impact:** Negative macro environments are under-penalised in the composite score vs. what the weight configuration intends. Scores cluster higher than they should on risk-off days.
- **Fix:** Intentional design decision? If so, document it. If not, allow `macro_component` to go negative when bias is negative.

### RESOLVED — `freshness_decay` uses `signal_decay.adaptive_freshness_decay` but `elapsed_seconds` may be `None`

- **Resolution:** `adaptive_freshness_decay(None)` now returns `0.5` (neutral), not `0.0` — `signal_decay.py:100-101` (`# Unknown age → neutral, not dead`); `scorer.py:168` documents that the live filter path relies on this "neutral, not dead" behaviour. Landed with the §1 half-life rewrite. Do not re-file.
- **Location:** `filter_candidate()`, lines ~320-335
- **Bug:** When `premarket_freshness_sec` is `None` (quote has no timestamp), the code passes `None` to `adaptive_freshness_decay()`, which returns `0.0`. A `freshness_decay = 0.0` then contributes `w["freshness_decay"] * 0.0 = 0.0` to the score. This means symbols without any timestamp data receive **zero freshness credit**, which is harsher than a moderately stale score. The intent is likely "no data → neutral default" rather than "no data → maximally penalised".
- **Impact:** Symbols that lack `premarket_freshness_sec` (common for some FMP data tiers) are scored as maximally stale, artificially depressing their ranking relative to peers with any timestamp.
- **Fix:** Default `freshness_decay` to `0.5` or `1.0` when `premarket_freshness_sec is None`.

---

## 3. news.py

### RESOLVED (verified 2026-07-27) — Article sort for "newest first" uses ISO string comparison, not datetime

- **Resolution:** The lexicographic sort is gone. `build_news_scores` now sorts on parsed datetimes —
  `row["articles"].sort(key=lambda a: _parse_article_datetime(a.get("date")) or _EPOCH, ...)`
  (news.py:374-376), with an in-code note that the key is `_parse_article_datetime` (returns
  `datetime | None`). Mixed `+00:00`/`Z` forms and microsecond variants therefore order correctly.
  This is exactly the fix proposed below ("apply the same approach as `latest_article_utc`").
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

### RESOLVED (verified 2026-07-24) — CircuitBreaker is not thread-safe

- **Resolution:** `_CircuitBreaker` is fully lock-guarded (`self._lock = threading.Lock()`; `allow_request`/`on_success`/`on_failure` all `with self._lock`) — macro.py:527/531/535. The referenced `record_success`/`_consecutive_failures` API no longer exists.

- **Location:** `CircuitBreaker.__init__()`, lines ~40-55, `record_success()`, `record_failure()`
- **Bug:** The `CircuitBreaker` instance is shared across all threads via `FMPClient._circuit_breaker`. `_consecutive_failures`, `_state`, and `_opened_at` are read/written without any locking. With `ThreadPoolExecutor` parallelism in `_atr14_by_symbol()` (up to 8 workers) and `_fetch_premarket_high_low_bulk()` (6 workers), concurrent calls to `_get()` can race on `record_success()` / `record_failure()`, causing:
  - Lost failure counts (two threads increment concurrently, only +1 is recorded)
  - State torn reads (one thread sees HALF_OPEN, another sees CLOSED simultaneously)
  - Premature circuit-open or missed circuit-open because `_consecutive_failures` is under-counted
- **Impact:** Under heavy parallel load, the circuit breaker may either fail to trip (allowing a flood of requests to a down API) or trip prematurely on a spurious race, silently dropping enrichment data. Both degrade ranking quality without any error trail.
- **Fix:** Use `threading.Lock` to guard state mutations, or use `threading.atomic` counters. Alternatively, make the circuit breaker per-thread (but this reduces its effectiveness as a global rate-protector).

### RESOLVED (verified 2026-07-24) — CSV fallback in `_get()` uses fragile type coercion heuristic

- **Resolution:** Rewritten as `_coerce_csv_value` (macro.py:110): negatives via the int path, `NaN`/`inf` stay strings, `1e5`→float. The `v.isdigit()` heuristic is gone.

- **Location:** `_get()`, lines ~270-290
- **Bug:** The CSV parser attempts `int(v) if v.isdigit() else float(v)` for every value. This fails for:
  - Negative numbers (e.g. `"-0.5"` → `v.isdigit()` is False, `float(v)` succeeds, OK)
  - But strings like `"1e5"` or `"NaN"` are coerced to float silently (`float("NaN")` succeeds)
  - ISO date strings like `"2025-06-03"` are kept as strings (OK)
  - Empty strings `""` → `v.isdigit()` is False, `float("")` raises ValueError → kept as `""` (OK)
  
  The real issue: `v.isdigit()` returns False for `"0"` on some edge platforms (it shouldn't, but) and always returns False for negative integers like `"-42"`, so those become floats (42.0) instead of ints.
- **Impact:** Downstream code expecting `int` market-cap values may get `float`, causing type-check failures in strict comparisons. Low practical impact since the CSV fallback is rare.
- **Fix:** Try `int(v)` first in a try/except, then `float(v)`, then keep as string. Or use `ast.literal_eval` with a safety wrapper.

### RESOLVED (verified 2026-07-24) — `_get()` re-creates `Request` object on every retry

- **Resolution:** Refactored into `_request_once` (macro.py:736); the self-admittedly “not a bug” concern is moot.

- **Location:** `_get()`, line ~230 (loop body)
- **Bug:** The `Request` object is constructed once before the loop at line ~225, but `urlopen()` may consume internal state. Since `Request` objects are lightweight and `urlopen` doesn't mutate them, this is **not** a correctness bug, but the `request` reference shadows the module-level `Request` import. No actual issue — included for completeness.

---

## 5. alerts.py

### NOT REACHABLE (documented 2026-07-27) — the entire webhook alert subsystem has never been configured

- **Finding (unwired-feature sweep, direction F):** `load_alert_config` reads
  `artifacts/open_prep/alert_config.json` with a fail-open to
  `DEFAULT_CONFIG` (`enabled: False`, `targets: []`) — and **no such file has
  ever existed anywhere** (path is gitignored via `artifacts/open_prep/*.json`,
  absent locally, never created on CI; the only writer `save_alert_config` is
  a REPL utility with zero callers). `dispatch_alerts` /
  `alert_regime_change` / `alert_weather_change` therefore return empty on
  every production run and always have. The TradersPost/Slack/Discord webhook
  code paths (including the previously-RESOLVED §5 payload fixes) are
  effectively dead code behind an operator opt-in nobody ever exercised.
- **Decision:** documented-off, not removed — the real alert path is
  `rt_notify` (realtime_signals → Slack), which is live and separate. If
  webhook alerts are ever wanted, create the config file; the code is
  test-covered and ready.

### NOT REACHABLE (verified 2026-07-27) — In-memory throttle state resets on process restart

- **Resolution:** Accurate as mechanism (`_last_sent` is still process-local, alerts.py:94), but the
  failure scenario cannot occur on the production path. `open_prep.alerts` has exactly one non-test
  importer — `run_open_prep.py:22` — and that pipeline runs on `run-open-prep-daily.yml`
  `cron: "0 13 * * 1-5"`, i.e. **once per trading day**. There is no second run inside the
  `throttle_seconds: 600` window for a persisted state to suppress, and the Streamlit-reload /
  container-restart scenario below belongs to a caller that does not exist. Within the run the
  throttle works and is lock-guarded (`_throttle_lock`, alerts.py:95/111/118). Persisting it would
  add a file dependency for no behavioural gain.
- **Location:** `_last_sent` dict, line ~89
- **Bug:** Throttle state is stored only in `_last_sent: dict[str, float] = {}`. When the process restarts (common in cron/Streamlit/container deployments), all throttle history is lost. The same alert fires again immediately.
- **Impact:** Every restart window produces duplicate alerts. In a Streamlit auto-reload scenario, reloading the page can trigger a burst of alerts for the same symbols.
- **Fix:** Persist `_last_sent` to a file (e.g. `artifacts/open_prep/alert_throttle.json`) using the same atomic-write pattern used elsewhere. Load on import, save on `_mark_sent()`.

### RESOLVED (verified 2026-07-24) — TradersPost payload uses `prev_close` instead of current price

- **Resolution:** `_format_traderspost_payload` reads `candidate.get('price') or candidate.get('prev_close')` (alerts.py:190) — current price first, prev_close only as fallback.

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

### RESOLVED (verified 2026-07-24) — `calculate_support_resistance_targets` swallows all exceptions

- **Resolution:** Now uses per-section `try/except` with `logger.warning` (7 sites in technical_analysis.py) — no single outer silent catch.

- **Location:** `calculate_support_resistance_targets()` (outer try/except wrapping entire function body, line ~400-550)
- **Bug:** The function catches `except Exception` at the outermost level and returns a neutral fallback dict. This hides bugs in the S/R calculation (e.g. division by zero, bad OHLCV data, logic errors) without any logging or re-raise option.
- **Impact:** If S/R calculation silently fails, trade cards show `None` stop-loss/targets, and downstream consumers (realtime engine, alert formatting) cannot distinguish "no S/R data" from "calculation bug". Debugging production issues requires reproducing exact inputs.
- **Fix:** Log the exception at WARNING/ERROR level inside the catch. Consider re-raising on non-data errors (e.g. `TypeError`, `AttributeError`).

### NOT A DEFECT — PREMISE FALSE (verified 2026-07-27) — `detect_breakout` `min_bars` check is over-conservative

- **Correction:** The claim "50 bars would suffice for all array accesses" is **false**.
  `detect_breakout` reads `prior_high_l = max(highs[-(long_n + 1):-1])` (and the matching
  `prior_low_l`), which needs **`long_n + 1` = 61** bars for a complete window, not 50. Python
  slicing does not raise on a short list — it silently returns a truncated window, so a 60-bar input
  would quietly turn the documented "60-day prior high" into a 54-day one. `min_bars = max(short_n,
  long_n) + 5 = 65` is therefore a guard against silent window truncation with **4** bars of
  headroom over the strict requirement, not a ~20 % overcount. Applying the fix proposed below
  (dropping the `+5`) would introduce exactly that silent truncation. Leave as-is.
- **Location:** `detect_breakout()`, line ~273
- **Bug:** `min_bars = max(short_n, long_n) + 5`. With default `short_n=30, long_n=60`, this requires 65 bars. But the function only accesses `closes[-short_n:]`, `closes[-long_n:]`, and `volumes[-50:]`. 50 bars would suffice for all array accesses. The `+5` padding and `max(short_n, long_n)` overcount by ~20 %.
- **Impact:** Symbols with 50-64 daily bars are classified as `"insufficient_data"` and miss breakout detection, even though the data is sufficient. This is common for recently-IPO'd names (3-4 months of history).
- **Fix:** Use `min_bars = max(short_n, long_n)` without the `+5` padding, or compute the actual minimum from the accesses.

### RESOLVED (verified 2026-07-24) — `_ema()` returns `NaN` for empty input

- **Resolution:** Intentional and documented (“distinguish no-data from a genuine zero”); callers guard. By-design, not a defect.

- **Location:** `_ema()`, line ~260
- **Bug:** Function returns `float("nan")` when `values` is empty. Callers (e.g. `detect_breakout`) check `ema_20 != ema_20` (NaN self-comparison) before use, which works, but this NaN can propagate if a new caller forgets the check.
- **Impact:** Low — existing callers handle it. Noted for defensive maintainability.

---

## 7. run_open_prep.py

### RESOLVED — NOT REACHABLE (verified 2026-07-25) — `_save_atr_cache`: `prev_close_map` key-case mismatch

- **Resolution:** Every symbol entering the ATR path is upper-cased at ingestion — the sole caller passes `atr_symbols` double-uppered (`run_open_prep.py:4569` list-comp `.strip().upper()` + `_normalize_symbols` which also `.strip().upper()`), and load/save key the cache with `str(k).upper()`. So `cached_atr.get(symbol)` / `prev_close_map.get(k)` always hit; the mixed-case trigger cannot occur on real inputs. Code-fragile but not reachable (re-confirmed 2026-07-25). Do not re-file.
- **Location:** `_save_atr_cache()`, lines ~2060-2080, vs `_incremental_atr_from_eod_bulk()`, line ~2115
- **Bug:** In `_save_atr_cache`, the `clean_prev_close_map` is keyed by `str(k).upper()` from `clean_atr_map` keys. But `prev_close_map` is populated from `cached_prev_close` (upper-cased) merged with `incremental_close` (which keys are whatever `eod_row` returned). If `eod_row` returns lowercase symbols, the `prev_close_map.get(k)` lookup uses the upper-cased `k` from `clean_atr_map`, which misses the lowercase key in `prev_close_map`, yielding `0.0`.
- **Impact:** `prev_close` values silently become `0.0` in the cache when EOD bulk returns lowercase symbols. On next-day incremental ATR update, `prev_close <= 0.0` causes the symbol to be skipped in `_incremental_atr_from_eod_bulk()`, forcing an expensive per-symbol fallback fetch.
- **Fix:** Normalise `incremental_close` keys to `.upper()` before merging into `prev_close_snapshot`.

### RESOLVED (verified 2026-07-25) — Race condition in ThreadPoolExecutor + circuit breaker during ATR fetch

- **Resolution:** This is (by the entry's own words) "the same circuit-breaker thread-safety issue as in macro.py" — and that `_CircuitBreaker` is now fully lock-guarded (`allow_request`/`on_success`/`on_failure` all `with self._lock`; see §4 RESOLVED). The ATR threads reach it through the shared `FMPClient._circuit_breaker`, so the same lock fixes this site. No unsynchronised counter remains.
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

### RESOLVED (verified 2026-07-27) — Breakout/consolidation enrichment uses ATR% proxy, not real ADX/BB data

- **Resolution:** Both proposed fixes landed. The enrichment now **prefers measured indicators**
  computed from the daily bars already fetched in the run — `real_adx = compute_adx_from_bars(bars)`
  / `real_bbw = compute_bb_width_pct_from_bars(bars)` (run_open_prep.py:5762-5766, "eval-findings D7")
  — and falls back to the ATR% proxy only when the bars are insufficient (< 2×14+1 for Wilder ADX,
  < 20 for BB). That is fix (b). Fix (c) landed too: every row carries
  `row["regime_source"] ∈ {"daily_bars", "atr_proxy", "no_data"}` so the provenance is disclosed
  per candidate (audit #2670 W2). The proxy branch is explicitly commented "synthesized BB/ADX, NOT
  measured indicators".
- **Separate, still-open finding (2026-07-27):** the *scorer's* `symbol_regime` is unrelated to this
  enrichment and is inert — see "§15 SYMBOL-layer regime weights never fire" in §2 (`scorer.py`).
- **Location:** `generate_open_prep_result()`, lines ~3660-3700
- **Bug:** `approx_bb_width = max(atr_pct * 2.5, 0.1)` and `approx_adx = min(max(atr_pct * 8.0, 5.0), 60.0)` are linear proxies of Bollinger Band width and ADX, derived solely from ATR%. These proxies have no empirical basis:
  - ATR% and ADX measure different things (volatility vs. trend strength)
  - A high-ATR% stock can be ranging (high ADX is not implied)
  - `atr_pct * 8.0` maps a 3% ATR stock to ADX=24 (borderline trending), and a 1% ATR stock to ADX=8 (strongly ranging), but a 1% ATR large-cap can be in a strong trend
- **Impact:** The `symbol_regime`, `consolidation`, `is_consolidating`, and `consolidation_score` fields in `ranked_v2` are unreliable proxies. Playbooks that key off `is_consolidating` or `symbol_regime` may make systematic errors (e.g. classifying trending large-caps as "RANGING").
- **Fix:** Either (a) fetch real ADX/BB data from FMP's technical indicators endpoint, (b) compute ADX from the daily bars already fetched in `_daily_bars_cache`, or (c) clearly label these as "proxy" fields in the output contract with a data-quality caveat.

### NOT REACHABLE (verified 2026-07-27) — `_incremental_atr_from_eod_bulk` momentum_z carries stale prior-day value

- **Resolution:** The carry-over line is real, but it does not execute on either production path.
  `_incremental_atr_from_eod_bulk` only reaches it for symbols whose bulk EOD row is dated `as_of`
  (`if row_date and row_date != as_of.isoformat(): continue`). Both producers run **pre-open** — the
  GH-Actions job at `cron: "0 13 * * 1-5"` (09:00 ET) and the local driver with `--pre-open-only`
  (`scripts/vd_open_prep.sh`) — and pre-open there is no completed EOD bar for `as_of`, so every
  symbol is skipped, `momentum_map` stays empty, and all symbols fall through to `_fetch_symbol_atr`,
  which recomputes `_momentum_z_score_from_eod(candles, period=50)` fresh. The function's own header
  already states the incremental path "no-ops pre-open".
- **Empirical proof:** four consecutive production cache files
  (`artifacts/open_prep/cache/atr/2026-07-{22,23,24,27}_p14.json`) — every symbol's `momentum_z`
  changes every day (AMD `1.5096 → 0.205 → −0.5812 → −0.7878`; likewise AMZN/GOOGL/META/MSFT).
  Under an active carry-over consecutive days would be **identical**. They never are.
- **Residual:** on a hypothetical post-close run with a warm prior-day cache the carry-over would
  apply, and would then compound (`prev_day = _prev_trading_day(as_of)` chains across weekends), so
  the in-code "may lag by ~1 session" would understate it. No such caller exists today.
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

### BY DESIGN — VERIFIED (2026-07-27) — `rank_candidates` duplicates scoring logic from `scorer.py`

- **Resolution:** The duality is intentional and the drift risk was checked directly (duplicated-logic
  sweep, 2026-07-25, PRs #4045/#4046). `screen.rank_candidates` is the legacy **display** ranker;
  `scorer.score_candidate` is the live **trade-rank** path — only the latter gates. The §8 hard-block
  duality is complete and v2 is a **strict superset** of v1's hard-blocks (the safe direction: v2 can
  only reject more, never less), the threshold literals currently equal the shared config, and the
  gap-`None` footgun in v1 is unreachable. No fix had landed in one copy but not the other. The ask
  below ("document the intentional duality") is satisfied by this note.
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

### RESOLVED (verified 2026-07-24) — `_quote_hash` uses MD5 with truncation to 16 chars

- **Resolution:** Actual is `hexdigest()[:12]` with `usedforsecurity=False` (realtime_signals.py:1839); change-detection only, self-heals next poll. The report’s own verdict (“practically zero collision risk”) stands — non-issue.

- **Location:** `_quote_hash()`, line ~90
- **Bug:** `hashlib.md5(raw.encode()).hexdigest()[:16]` — 16 hex chars = 64 bits of hash space. For change-detection on ~500 symbols polled every few seconds, the collision probability per cycle is ~`n²/2^65`. With 500 symbols and 86400/5 ≈ 17,280 cycles/day, the cumulative collision probability per day is effectively negligible (~10⁻¹⁰).
- **Impact:** Practically zero collision risk. Noted only because MD5 is deprecated for cryptographic use; for non-security hash comparisons it's fine. Using SHA-256 would be equally fast and avoid MD5 in audits.
- **Fix:** Optional: replace with `hashlib.sha256(...).hexdigest()[:16]`.

### RESOLVED (verified 2026-07-24) — `poll_once()` imports `newsstack_fmp` inside the function body

- **Resolution:** Cached: the sync path guards `if not hasattr(self, '_ns_poll_fn')` (realtime_signals.py:3179) and the async loop caches in locals; the import runs once.

- **Location:** `poll_once()`, line ~450 (approximate)
- **Bug:** `from newsstack_fmp import ...` is called on every poll cycle. If `newsstack_fmp` is unavailable (optional dependency), the `ImportError` is caught and news integration is silently disabled, which is correct. But the repeated import attempt adds overhead on every poll cycle (~17,000/day).
- **Impact:** Minor CPU overhead. If `newsstack_fmp` raises `ImportError`, it's re-attempted every cycle instead of being cached as unavailable.
- **Fix:** Cache the import result at module level: `_newsstack = None` / try-import once.

### RESOLVED (verified 2026-07-24) — `GateHysteresis.should_fire()` state persists indefinitely

- **Resolution:** Renamed to `evaluate()` over `_state` with `max_state_size=1000` eviction (realtime_signals.py:1657/1691); no `should_fire`/`_last_fired`.

- **Location:** `GateHysteresis` class (lines ~60-90)
- **Bug:** The `_last_fired` dict grows unboundedly as new symbols are tracked. There's no eviction of symbols that haven't been seen in days.
- **Impact:** Memory growth in long-running processes. With ~500 symbols and 8-byte timestamps, this is <50 KB — negligible.

---

## 10. playbook.py

### RESOLVED (verified 2026-07-25) — `classify_news_event` iterates all patterns without short-circuit on certainty

- **Resolution:** The described mechanism is stale: there is no `NEWS_EVENT_PATTERNS` constant (patterns are three separate lists) and the worked example is false (`"FDA approval … regulatory review"` → label `fda`, materiality HIGH — verified). The one real residual — first-match ORDER can mask a co-occurring higher-materiality label — is now explicitly documented in code as a deliberate tradeoff (`playbook.py:116-119`: "this is match ORDER, not a materiality ranking … can be masked"). By-design, not a latent bug.
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

### RESOLVED (verified 2026-07-24) — Feature importance uses Pearson correlation for binary outcomes

- **Resolution:** n-gate (`_MIN_TUNING_SAMPLES=200`) + Welch t-test + Benjamini–Hochberg FDR (outcomes.py:1099/1366) are implemented and wired into `compute_weight_adjustments`.

- **Location:** `FeatureImportanceCollector.compute_importance()`, lines ~350-400
- **Bug:** The code computes Pearson correlation between continuous features (gap_pct, volume_ratio, score) and a binary outcome (profitable_30m: 0/1). Pearson correlation between a continuous variable and a binary variable is mathematically the point-biserial correlation, which is valid, but:
  - With small sample sizes (ring buffer of 100), the correlation is highly unstable
  - Features with skewed distributions (volume_ratio) produce misleading correlations
  - No statistical significance test is applied
- **Impact:** Feature importance rankings may suggest a feature is important purely due to sample noise, leading to false confidence in weight adjustments.
- **Fix:** Add a minimum sample-size gate (e.g. n ≥ 30), report confidence intervals, or switch to a rank-based metric (Spearman's rho) that's more robust to outliers.

### RESOLVED (verified 2026-07-24) — File rotation uses calendar days, not trading days

- **Resolution:** Rotates by file count (`OPEN_PREP_OUTCOME_RETENTION_DAYS`, default 90 newest = one per trading day; outcomes.py:227/234) — already the trading-day retention asked for.

- **Location:** `store_daily_outcomes()`, lines ~240-260
- **Bug:** Outcome files are retained by calendar-day count (`max_age_days=30`). On weekends and holidays, no new files are created, but the retention window counts those days. Effectively, 30 calendar days retains ~21 trading days of data.
- **Impact:** Less backward-validation data than the configured 30-day window implies. Misleads operators counting trading days.

---

## 12. watchlist.py

### NOT REACHABLE (verified 2026-07-27) — `fcntl`-based file locking is POSIX-only; no-op on Windows

- **Resolution:** Accurate, already documented in code, and unreachable in production. watchlist.py:18
  guards `import fcntl  # POSIX only` and watchlist.py:33 states the fallback ("Falls back to a no-op
  on platforms without fcntl (Windows)") — i.e. the report's own "Fix: document the limitation" is
  already satisfied. Production runs on `ubuntu-latest` (`run-open-prep-daily.yml`) and macOS locally,
  both of which take the `fcntl.flock` path (watchlist.py:41/44). The entry's own impact line concedes
  "On POSIX (Linux/macOS production): no issue".
- **Location:** `_lock_file()` / `_unlock_file()`, lines ~30-50
- **Bug:** The code correctly tries `import fcntl` and falls back to a no-op on `ImportError` (Windows). However, the no-op fallback means concurrent processes on Windows can corrupt the watchlist JSON file.
- **Impact:** On POSIX (Linux/macOS production): no issue. On Windows dev environments: potential data loss if two processes write simultaneously.
- **Fix:** Document the limitation or use `msvcrt.locking()` on Windows for advisory locking.

### RESOLVED (verified 2026-07-24) — `auto_add_high_conviction` always appends, never deduplicates against existing watchlist

- **Resolution:** Dedups against the `existing` symbol set before appending (watchlist.py:153/160).

- **Location:** `auto_add_high_conviction()`, line ~160-180
- **Bug:** If the same symbol re-qualifies as HIGH_CONVICTION on the next run, it's appended again (with a newer timestamp). The watchlist grows with duplicates.
- **Impact:** UI displays duplicate entries. The `get_watchlist_symbols()` function returns a list (not set), so duplicates affect downstream logic that counts symbols.
- **Fix:** Check if symbol already exists before appending, or use `setdefault` on symbol key.

---

## 13. trade_cards.py

### RESOLVED (verified 2026-07-25) — ATR trailing stop assumes long-only direction

- **Resolution:** `_compute_trailing_stop()` no longer exists. The current `_trail_stop_profiles_from_atr(row, direction)` has an explicit short branch (`stop = reference + dist`, trailing ABOVE entry) and `_card_direction` supplies `"short"` for a gap-up GAP_FADE; `direction` is threaded into both trailing-stop and key-levels. Empirically SHORT stops sit above entry. Fixed.
- **Location:** `_compute_trailing_stop()`, lines ~140-160
- **Bug:** The trailing stop is always calculated as `entry_price - (atr * atr_multiple)`. For a short/fade playbook (bearish), the stop should be `entry_price + (atr * atr_multiple)`. The playbook engine can assign `FADE` strategy, but the trade card always computes a long-side stop.
- **Impact:** Trade cards for FADE/short-biased signals show a stop-loss below entry (wrong direction). A trader following these cards would have no upside protection.
- **Fix:** Accept a `direction` parameter and invert the stop calculation for short signals.

### RESOLVED (verified 2026-07-25) — S/R target levels may be `None` without fallback

- **Resolution:** The named output fields `"target_1"`/`"target_2"` are no longer emitted by `build_trade_cards`. The card emits `key_levels.sr_targets` (nullable) AND always emits `trail_stop_atr` (ATR distances + stop_prices) — exactly the ATR-based fallback this entry asked for. Fixed.
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

### RESOLVED (2026-07-24, PR #3991) — `classify_regime` VIX thresholds produce regime flicker

- **Resolution:** `classify_regime` carries a ±1pt VIX dead-zone, but it was inert in prod — the pipeline reset the hysteresis anchor every run, and batch runs are per-process, so `_prev_regime` was always `None`. PR #3991 seeds the anchor from the prior run's persisted regime when it is the same session (else reset), so intra-session dashboard refreshes no longer flicker. See `regime.seed_regime_hysteresis_from_prior_run`.
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

### RESOLVED (verified 2026-07-25) — No integration test coverage for the pipeline

- **Resolution:** The premise is false. `tests/` holds dozens of open_prep suites — e.g. `test_open_prep.py`, `test_open_prep_contracts.py`, `test_open_prep_scorer_uplift.py`, `test_playbook_scoring_sizing.py`, `test_outcome_backfill.py`, `test_regime_*`, and — pointedly — `test_scorer_component_cap_convergence.py`, the exact regression this entry claimed unit tests would have caught. Mocked-FMP integration coverage exists. Fixed.
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

### RESOLVED (verified 2026-07-25) — Atomic writes don't persist `fsync` before `os.replace`

- **Resolution:** The "none call `os.fsync`" premise is false. Every listed site now fsyncs before `os.replace`: `_save_atr_cache` (run_open_prep.py:3126), `_pm_cache_save` (:3526), `save_alert_config` (alerts.py:80), `_save_result_snapshot` (:5655), latest-run JSON (:5993), and `store_daily_outcomes` (outcomes.py:218/852). Fixed.
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

> **Counts are OPEN items (not yet RESOLVED) as of 2026-07-27.** Of 47 catalogued entries, 31
> carry an inline `RESOLVED` / `NOT REACHABLE` / `BY DESIGN` / premise-correction note (verified
> against current code) and 16 remain open. Every originally-HIGH item is resolved.
>
> **2026-07-27 — all 11 then-open MEDIUM entries were re-verified individually.** None turned out to
> be an actionable live bug: 2 were already fixed (article sort, proxy ADX/BB), 3 are unreachable on
> the production paths (momentum_z staleness, alert throttle, fcntl), 2 had a **false premise** and
> would have made things worse if "fixed" (`macro_component` — risk-off is penalised ~2.9× harder,
> not under-penalised; `detect_breakout min_bars` — 61 bars are required, not 50), 1 is verified
> by-design (v1/v2 duality), and 3 are accurate but low-impact and self-mitigating (PMH/PML timeout,
> gap dict shapes, FMP key in URL). One **new** MEDIUM was found in the process: §15 SYMBOL-layer
> regime weights never fire. Treat any surviving entry's *impact* line as unverified until re-checked
> — several overstated or inverted the consequence while describing the mechanism correctly.

| Severity | Open | Key open items |
|----------|------|----------------|
| **HIGH** | 0 | none — half-life, score cap, circuit-breaker (×2), prev_close key-case, and no-test-coverage all RESOLVED / NOT REACHABLE |
| **MEDIUM** | 4 | §15 regime weights never fire (NEW); PMH/PML timeout loss; gap dict shapes; FMP key in URL |
| **LOW** | 12 | future-dated articles; SSL rebuild per call; cache-evict local import; SPAC classify; screen `_to_float` zeros; playbook length; BEA fragility (×2); diff schema drift; sector_breadth 0.0; retry exc-chain; utils `to_float` convention |

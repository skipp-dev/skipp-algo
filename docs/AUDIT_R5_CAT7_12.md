# Audit Round 5 — Categories 7–12

**Date:** 2026-02-28  
**Scope:** All Python files in `*.py`, `open_prep/`, `newsstack_fmp/`, `scripts/`, `tests/`

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0     |
| HIGH     | 0     |
| MED      | 6     |
| LOW      | 5     |
| **Total**| **11**|

---

## Findings

### 7.2 — Race condition on `_tv_cooldown_until` read

- **File:** `terminal_bitcoin.py:144–145`
- **Severity:** MED
- **Category:** 7 (Type Safety) / 9 (Data Integrity)
- **Description:** `_tv_is_cooling_down()` reads the global `_tv_cooldown_until` without holding `_tv_rate_lock`. The same function in `terminal_technicals.py:178` correctly acquires the lock before reading. Under concurrent access (Streamlit multi-threaded rerun + background polling), this is a data race that could read a partially-written float.
- **Code (buggy):**

  ```python
  def _tv_is_cooling_down() -> bool:
      return time.time() < _tv_cooldown_until
  ```

- **Code (correct — terminal_technicals.py):**

  ```python
  def _tv_is_cooling_down() -> bool:
      with _tv_rate_lock:
          deadline = _tv_cooldown_until
      return time.time() < deadline
  ```

- **Fix:** Add `with _tv_rate_lock:` around the read in `terminal_bitcoin.py:144`.

---

### 8.1 — httpx.Client singleton never closed (terminal_bitcoin)

- **File:** `terminal_bitcoin.py:84`
- **Severity:** MED
- **Category:** 8 (Resource Leaks)
- **Description:** `_get_client()` creates `_client = httpx.Client(timeout=15.0)` as a module-level singleton. No `atexit.register()` or `close()` exists — the client's underlying connection pool leaks on shutdown. Compare with `newsstack_fmp/pipeline.py` which properly registers `_cleanup_singletons()` via `atexit`.
- **Fix:** Add after `_get_client()`:

  ```python
  import atexit
  atexit.register(lambda: _client.close() if _client else None)
  ```

---

### 8.2 — httpx.Client singleton never closed (terminal_forecast)

- **File:** `terminal_forecast.py:47`
- **Severity:** MED
- **Category:** 8 (Resource Leaks)
- **Description:** `_get_fmp_client()` creates `_fmp_client = httpx.Client(timeout=10.0)` as a module-level singleton with no cleanup. Same root cause as 8.1.
- **Fix:** Same atexit pattern.

---

### 10.2 — FinnhubClient / AlpacaClient — no retry on transient HTTP failures

- **File:** `open_prep/macro.py:1248` (FinnhubClient._get), `open_prep/macro.py:1483` (AlpacaClient._get)
- **Severity:** MED
- **Category:** 10 (Error Recovery / Resilience)
- **Description:** Both clients use bare `urlopen()` with no retry logic. A single transient 500, 502, 503, 504, or timeout kills the request. Compare with `FmpAdapter._safe_get()` in `newsstack_fmp/ingest_fmp.py:78` which has proper retry+backoff for `{429, 500, 502, 503, 504}`. Also note that `FMPClient._get()` at `macro.py:253` already has circuit-breaker logic but FinnhubClient and AlpacaClient do not.
- **Fix:** Add retry with exponential backoff for status codes in `{429, 500, 502, 503, 504}`, similar to `FmpAdapter._safe_get()`.

---

### 12.1 — TradingView rate-limiter code duplicated across 2 files

- **File:** `terminal_bitcoin.py:130–178` vs `terminal_technicals.py:170–215`
- **Severity:** MED
- **Category:** 12 (Code Quality / Maintainability)
- **Description:** Four nearly-identical functions are fully duplicated:
  - `_tv_is_cooling_down()` (and the bitcoin version has a bug — finding 7.2!)
  - `_tv_register_429()`
  - `_tv_register_success()`
  - `_tv_throttle()`
  
  Plus 7 shared state variables: `_tv_cooldown_until`, `_tv_consecutive_429s`, `_TV_COOLDOWN_BASE`, `_TV_COOLDOWN_MAX`, `_TV_MIN_CALL_SPACING`, `_tv_last_call_ts`, `_tv_rate_lock`.
  
  The duplication directly caused the race-condition bug in finding 7.2 (the bitcoin copy diverged from the technicals copy).
- **Fix:** Extract into a shared module (e.g. `_tv_rate_limiter.py`) or a `TVRateLimiter` class. Both files import from it.

---

### 12.3 — Giant functions exceeding 100 lines (top offenders)

- **Files:** Multiple
- **Severity:** MED
- **Category:** 12 (Code Quality / Maintainability)
- **Description:** 10 functions exceed 100 lines. Top offenders:

  | File | Function | Lines |
  |------|----------|-------|
  | `open_prep/streamlit_monitor.py:604` | `main()` | 1610 |
  | `open_prep/streamlit_monitor.py:796` | `_render_open_prep_snapshot()` | 1402 |
  | `open_prep/run_open_prep.py:3640` | `generate_open_prep_result()` | 882 |
  | `open_prep/realtime_signals.py:1251` | `poll_once()` | 433 |
  | `open_prep/scorer.py:210` | `filter_candidate()` | 273 |
  | `open_prep/scorer.py:489` | `score_candidate()` | 266 |
  | `open_prep/technical_analysis.py:610` | `calculate_support_resistance_targets()` | 222 |
  | `open_prep/realtime_signals.py:1031` | `_detect_signal()` | 216 |
  | `newsstack_fmp/pipeline.py:244` | `poll_once()` | 199 |
  | `terminal_export.py:213` | `build_vd_snapshot()` | 198 |
  
- **Fix:** Progressively refactor into sub-functions. Priority: `streamlit_monitor.py:main` (1610 lines) and `run_open_prep.py:generate_open_prep_result` (882 lines).

---

### 7.1 — `getattr(cached_429, 'error', '')` type mismatch (FALSE POSITIVE)

- **File:** `terminal_bitcoin.py:578`
- **Severity:** LOW
- **Category:** 7 (Type Safety)
- **Description:** Pylance may flag `getattr(cached_429, 'error', '')` because `_get_cached()` returns `Any` and Pylance can't narrow the type to `BTCTechnicals`. However, `BTCTechnicals.error` is typed `str` (line 310: `error: str = ""`), so the default `''` is the correct type. This is NOT a real bug.
- **Fix:** Optional: add `# type: ignore[arg-type]` or narrow the cache return type.

---

### 11.1 — `logger.error()` without `exc_info=True`

- **File:** `open_prep/run_open_prep.py:3320, 3333, 3415`
- **Severity:** LOW
- **Category:** 11 (Logging Quality)
- **Description:** Three `logger.error()` calls in fail-open exception handlers log only `%s` of the exception but don't include `exc_info=True`, losing the traceback. In production, these are the most important paths to debug.

  ```python
  logger.error("Macro calendar fetch failed ...: %s", exc)          # L3320
  logger.error("Invalid --pre-open-cutoff-utc ...: %s", exc)        # L3333
  logger.error("Quote fetch failed ...: %s", exc)                   # L3415
  ```

- **Fix:** Add `exc_info=True` to all three calls.

---

### 12.2 — `_safe_float()` duplicated in 4 files

- **File:** `terminal_spike_scanner.py:297`, `terminal_spike_detector.py:288`, `open_prep/technical_analysis.py:46`, `streamlit_terminal.py:1099` (as `_safe_float_mov`)
- **Severity:** LOW
- **Category:** 12 (Code Quality / Maintainability)
- **Description:** Identical `_safe_float(val, default=0.0) -> float` implementations exist in 4 files. A canonical `to_float()` already exists in `open_prep/utils.py:13` with the same signature and semantics.
- **Fix:** Replace duplicates with `from open_prep.utils import to_float as _safe_float` (or rename callers).

---

### 12.4 — Rank weight magic numbers without named constants

- **File:** `terminal_export.py` (inside `build_vd_snapshot`, approximately L380)
- **Severity:** LOW
- **Category:** 12 (Code Quality / Maintainability)
- **Description:** The composite rank formula uses inline magic numbers:

  ```python
  r["rank_score"] = round(_chg * 0.7 + _ns * 100.0 * 0.3, 2)
  ```

  The weights `0.7` and `0.3` and the `100.0` scaling factor have no named constants.
- **Fix:** Define `_RANK_WEIGHT_PRICE = 0.7`, `_RANK_WEIGHT_NEWS = 0.3`, `_NEWS_SCORE_SCALE = 100.0` as module-level constants.

---

### 12.5 — Identical dict constants in terminal_ui_helpers.py

- **File:** `terminal_ui_helpers.py:22–51`
- **Severity:** LOW
- **Category:** 12 (Code Quality / Maintainability)
- **Description:** Two pairs of identical dictionaries:
  - `MATERIALITY_COLORS` (L22–26) == `MATERIALITY_EMOJI` (L38–42) — same keys and values
  - `RECENCY_COLORS` (L28–35) == `RECENCY_EMOJI` (L44–51) — same keys and values
- **Fix:** Remove duplicates and alias: `MATERIALITY_EMOJI = MATERIALITY_COLORS` and `RECENCY_EMOJI = RECENCY_COLORS`.

---

## Not-a-Finding Notes

| Item | Reason |
|------|--------|
| `scripts/*.py` using `print()` | Acceptable for CLI launcher scripts — user-facing output |
| `newsstack_fmp` adapter `.close()` | Covered by `atexit.register(_cleanup_singletons)` in `pipeline.py` |
| `terminal_spike_scanner.py:82` httpx.Client | Uses `with` context manager — properly closed |
| `terminal_poller.py` httpx.Client instances | All use `with` context manager — properly closed |
| `terminal_bitcoin.py:578` getattr type | False positive — `BTCTechnicals.error` is `str`, not `bool` |

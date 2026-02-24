# Senior Code Review — `open_prep/` Suite

**Reviewer:** GitHub Copilot (Claude Opus 4.6)  
**Scope:** Full `open_prep/` package (~12 500 LOC across 21 Python files)  
**Constraints:** Fail-open philosophy · no breaking schema changes · no silent drops · long-only gap scanner

---

## HIGH Severity

### H-1 · Double JSON artifact write – data race & wasted I/O

**File:** `run_open_prep.py` lines 3736-3744 **and** 3851-3857  
`generate_open_prep_result()` writes `latest_open_prep_run.json` at line 3739.  
`main()` writes the *same file again* at line 3854 (from the already-serialised `rendered` string).  
The second write uses `json.dumps(result, indent=2)` (no `default=str`) and will **crash** if the result dict contains any non-serialisable object (e.g. `datetime`, `date` instances) that the first write tolerates via `default=str`.  
Additionally, two writes to the same path without coordination are a race condition when Streamlit and CLI run simultaneously.

**Fix:** Remove the redundant write in `main()`.

---

### H-2 · `outcomes.py` – bare `float()` crashes on corrupt data

**File:** `outcomes.py` lines 156-159  

```python
gap_pct = float(rec["gap_pct"]) if rec.get("gap_pct") is not None else 0.0
rvol = float(rec["rvol"]) if rec.get("rvol") is not None else 0.0
pnl = float(rec["pnl_30m_pct"]) if rec.get("pnl_30m_pct") is not None else 0.0
```

If a stored JSON record contains a non-numeric string (e.g. `"N/A"`, `""`), `float()` raises `ValueError` and the entire hit-rate computation crashes – violating fail-open.

**Fix:** Use `_to_float()` from `utils.py` or wrap in try/except with default 0.0.

---

### H-3 · `outcomes.py` `prepare_outcome_snapshot` – same bare `float()` issue

**File:** `outcomes.py` lines 230-231  

```python
gap_pct = float(row["gap_pct"]) if row.get("gap_pct") is not None else 0.0
rvol = float(row.get("volume") or 0)
```

Same crash vector as H-2.

---

### H-4 · `scorer.py` weight ensemble `load_weight_set` – silent `pass` on corrupt JSON

**File:** `scorer.py` lines 76-84  
If the weight file is corrupt, the bare `except Exception: pass` silently returns `None`, which then causes `DEFAULT_WEIGHTS` to be used — but this should at least be logged as a warning since the operator explicitly placed a custom weight file and expects it to take effect.

**Fix:** Add `logger.warning(...)` inside the except block.

---

## MEDIUM Severity

### M-1 · `run_open_prep.py` `_compute_gap_for_quote` – `previousClose` ≤ 0 returns `None`; callers don't all handle it

**File:** `run_open_prep.py` line ~1640  
When `previousClose` is zero or missing, `_compute_gap_for_quote()` returns `None`. Most callers use `_to_float(q.get("gap_pct"), 0.0)` which handles this, but `build_gap_scanner()` at line 3801 uses `effective_gap` directly *after* an early `continue` only if `gap_available` is False. The gap_available check depends on `gap_pct is not None`, so `None` values flow correctly. **No crash**, but the logic would be clearer with an explicit `0.0` default.

---

### M-2 · v1 `rank_candidates()` in `screen.py` duplicates v2 scorer logic

**Files:** `screen.py` lines 150-508, `scorer.py` lines 400-746  
The v1 ranker is a near-clone of v2 without sector-relative scoring, freshness decay, diminishing returns, or adaptive gating. Both are maintained in parallel, creating a maintenance burden. The v2 pipeline is used by `generate_open_prep_result()`, so v1 is effectively dead code unless used by external scripts.

**Fix:** Deprecate v1; add a `_deprecated` suffix or docstring warning.

---

### M-3 · In-memory alert throttle resets every process restart

**File:** `alerts.py` line 39  
`_SENT_SYMBOLS: dict[str, float] = {}` is module-level. Every time the CLI is run or Streamlit restarts, throttle state is lost. This can cause duplicate alerts immediately after a restart.

**Fix:** (Low priority — acceptable for current usage pattern. Document the behavior.)

---

### M-4 · `watchlist.py` / `outcomes.py` – no cross-process file locking

**Files:** `watchlist.py` `_save_raw()`, `outcomes.py` `store_daily_outcomes()`  
Both use `tempfile + os.replace` for atomic writes (good), but simultaneous writers (Streamlit + CLI) can still cause last-write-wins data loss. The read→modify→write pattern in `auto_add_high_conviction()` is particularly susceptible.

**Fix:** Use `fcntl.flock()` or a `.lock` file for the read-modify-write critical section.

---

### M-5 · `macro.py` `FMPClient._get()` – API key in URL assembled in memory

**File:** `macro.py` line 164  

```python
query["apikey"] = self.api_key
url = f"{self.base_url}{path}?{urlencode(query)}"
```

Although the URL is never logged (good — error messages use `path` only), a crash traceback or debugger session could expose the full URL. This is a minor hygiene issue.

**Fix:** No code change needed; just ensure `repr=False` stays on `api_key` (it does).

---

### M-6 · `run_open_prep.py` – large ThreadPoolExecutor for ATR with no semaphore on FMP API calls

**File:** `run_open_prep.py` line ~2177  
`_atr14_by_symbol()` uses `ThreadPoolExecutor(max_workers=atr_parallel_workers)` (default 6) calling FMP /stable/historical-price-eod per symbol. With 200 symbols, that's 200 FMP calls at 6 concurrency. If the FMP plan has rate-limiting, this can trigger 429s. The retry logic handles it, but the burst can cause significant delays.

**Fix:** Add a short `time.sleep(0.05)` between calls or use a semaphore. Acceptable as-is since retry/backoff handles 429s.

---

### M-7 · `realtime_signals.py` – no deduplication of signals across restarts

**File:** `realtime_signals.py` lines 340-370  
On restart, `_active_signals` is empty, so the same breakout can be re-signaled. The engine checks in-memory state only. If the user restarts during market hours, they get duplicate A0/A1 alerts.

**Fix:** Load previous signals from `latest_realtime_signals.json` on startup and merge with active list.

---

### M-8 · `streamlit_monitor.py` – `st.exception(exc)` leaks full traceback to UI

**File:** `streamlit_monitor.py` line 442  
If the pipeline fails, the full Python traceback is shown in the Streamlit UI, which could contain file paths, API endpoints, or other internal details.

**Fix:** Show a sanitised error message; log the full traceback to the logger instead.

---

## LOW Severity

### L-1 · `macro.py` – uses `urllib` while `newsstack_fmp` uses `httpx`

Two different HTTP clients across the project. Not a bug, but increases dependency surface and maintenance burden.

### L-2 · `screen.py` – `_clamp` defined as inner function on every call

**File:** `screen.py` line 92  
A one-line function defined inside `classify_long_gap()` on every call. Negligible perf impact but poor style.

**Fix:** Move to module level.

### L-3 · `playbook.py` – `_ARTICLE_TEXT_LIMIT = 500` truncates article text

**File:** `playbook.py` line 65  
Keyword matching on truncated text may miss important signals in longer articles. Acceptable trade-off for performance.

### L-4 · `scorer.py` `FRESHNESS_HALF_LIFE_SECONDS = 600` is a constant

**File:** `scorer.py` line 99  
`signal_decay.py` has proper `adaptive_half_life()`, but the scorer uses a fixed 600s half-life. Should use the adaptive version for consistency.

**Fix:** Use `adaptive_half_life()` from `signal_decay.py`.

### L-5 · `bea.py` – HTML scraping of BEA website is fragile

**File:** `bea.py` lines 54-100  
The regex-based HTML scraping of `bea.gov` will break if BEA changes their page structure. Fail-open design mitigates impact.

### L-6 · `diff.py` – score change threshold hardcoded to 0.5

**File:** `diff.py` line 120  
The threshold for reporting score changes is hardcoded. Should be configurable via env var for tuning.

### L-7 · Missing `__all__` exports in most modules

Makes it harder for tooling and IDE autocompletion to know the public API surface.

### L-8 · `realtime_signals.py` – `SIGNALS_PATH` / `LATEST_RUN_PATH` use `Path(__file__)`

**File:** `realtime_signals.py` lines 43-44  
These resolve to the package source directory, not a user-configurable artifacts directory. This is inconsistent with `outcomes.py` and `watchlist.py` which use `artifacts/open_prep/`.

---

## Evidence Pack

| Finding | File | Lines | Impact |
|---------|------|-------|--------|
| H-1 | run_open_prep.py | 3736-3744, 3851-3857 | Crash on non-serialisable values; wasted I/O |
| H-2 | outcomes.py | 156-159 | `ValueError` crash on corrupt stored data |
| H-3 | outcomes.py | 230-231 | Same as H-2 |
| H-4 | scorer.py | 76-84 | Silent config failure, operator confusion |
| M-1 | run_open_prep.py | ~1640 | Clarity |
| M-2 | screen.py | 150-508 | Dead code / maintenance burden |
| M-3 | alerts.py | 39 | Duplicate alerts after restart |
| M-4 | watchlist.py, outcomes.py | various | Last-write-wins data loss |
| M-5 | macro.py | 164 | API key in memory |
| M-6 | run_open_prep.py | ~2177 | FMP rate-limit bursts |
| M-7 | realtime_signals.py | 340-370 | Duplicate signals on restart |
| M-8 | streamlit_monitor.py | 442 | Traceback leakage |
| L-1 | macro.py | - | Dual HTTP clients |
| L-2 | screen.py | 92 | Inner function style |
| L-3 | playbook.py | 65 | Article truncation |
| L-4 | scorer.py | 99 | Fixed vs adaptive half-life |
| L-5 | bea.py | 54-100 | Fragile HTML scraping |
| L-6 | diff.py | 120 | Hardcoded threshold |
| L-7 | All modules | - | Missing `__all__` |
| L-8 | realtime_signals.py | 43-44 | Signal files in source dir |

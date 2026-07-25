# FMP Quote Row Contract for Databento Migration

## Overview

This document enumerates the exact fields that `open_prep/realtime_signals.py` reads from an FMP quote-row dictionary during signal detection and polling. It is the source-of-truth contract that a Databento-based `QuoteSource` adapter must satisfy.

## Field Inventory

For each field, this table records:
- **Field Name**: The dictionary key as accessed via `.get()` in the FMP path.
- **Python Type**: The runtime type after `_safe_float()` coercion or raw extraction.
- **Meaning**: Semantic purpose in signal detection.
- **Null/Missing Behavior**: How the code handles absence or invalid values.
- **Databento Derivation**: How to compute the field from Databento `ohlcv-1s` bars plus daily reference data.

| Field | Type | Meaning | Null/Missing Behavior | Databento Derivation |
|-------|------|---------|----------------------|--------------------|
| `symbol` | `str` | Stock ticker symbol, normalized to uppercase. | Skipped if missing or empty in quote row; see line 2608–2610 in realtime_signals.py (`_fetch_realtime_quotes()`). | Extracted from bar's `symbol` column; reference-file symbol field. |
| `price` | `float` | Current last price, measured in dollars. Primary source for intraday price; fallback is `lastPrice`. | Coerced via `_safe_float()` with fallback to `lastPrice`; if both missing/invalid, returns 0.0 (line 2725); signal detection skipped if ≤ 0 (line 2755). | Last bar's `close` price from the current session. |
| `lastPrice` | `float` | Fallback price field, same semantic as `price`. | Only used if `price` is falsy or invalid (line 2725). | Same as `price`; last bar's `close`. |
| `previousClose` | `float` | Previous session's closing price; used to compute intraday % change and volume-ratio denominator. | Coerced via `_safe_float()` to 0.0 if missing; signal detection skipped if ≤ 0 (line 2755–2756). | Daily reference file's `previousClose` for the date. Must be persisted in session-date index. |
| `volume` | `float` (raw: `Any`) | Cumulative **regular-session** volume for the day at poll time, used for volume-ratio and pace normalization. | Raw value extracted without coercion (line 2727); then validated via `_safe_float()` (line 2728). If raw value is non-numeric or NaN/Inf, signal detection is skipped with debug log (line 2737–2743). | Cumulative regular-session volume up to poll time (sum of all 1-second bars' volumes in current session, from 9:30 ET onward). **Note:** postmarket flows have separate volume logic (see `build_postmarket_quotes()` in postmarket_quotes.py; postmarket volume = current - baseline). |
| `avgVolume` | `float` | Average daily trading volume (ADV), used to compute volume ratios and A0 thresholds; normalized to ≥1000 to avoid skipping signals. | Coerced via `_safe_float()` with fallback to `watchlist_entry.get("avg_volume")` (line 2730). If result < 1000, signal detection is skipped (line 2748–2753). **FMP batch-quote endpoint does NOT return this field today.** | Daily reference file's average daily volume (ADV); typically a 20/30/60-day rolling average. Must be keyed by symbol and session date. Fallback: watchlist dict if Databento reference lacks the field. |
| `timestamp` | `float` (epoch, ms or s) | Quote's arrival timestamp (nanoseconds or milliseconds since Unix epoch, depending on source). Recorded as audit metadata in signal. | Coerced via `_safe_float()` (line 2809). Normalized to seconds via `_normalize_epoch()` in a0_contract.py:153. **Live signal detection does NOT apply a hard freshness gate.** The -30 ≤ age ≤ 300s gate (line 2675–2677) exists only in `_poll_extended_shadow()` for metrics; real signals record only `data_age_ms` and `data_age_unknown` as audit fields (a0_contract.py:159–163, 177–178). | Databento bar's `ts_event` (nanoseconds or provided timestamp); convert to seconds. For realtime polling, use the bar's last-update timestamp or ingest time. |
| `received_at` | `float` (epoch) | When the quote was received by the data provider. Used for audit trails in signal metadata. | Passed to `build_market_snapshot()` as `raw_ts_recv` parameter (line 2810). Normalized via `_normalize_epoch()` (a0_contract.py:154); if None/invalid, falls back to `observed_at`. **Never None in final signal.** Lands in `signal.details["ts_recv"]` via `A0Decision.to_details()`. | Databento's reception timestamp or ingest time. If unavailable, use bar's `ts_event`. |
| `source` | `str` | Data-source identifier ("fmp" by default). Stored in signal metadata for traceability. | Coerced via `str()` with fallback default "fmp" (line 2808). | String literal "databento" or equivalent identifier to distinguish from FMP. |
| `expected_volume_fraction` | `float` ([0.02, 1.0]) | Expected cumulative volume fraction at current time, derived from time-of-day model or persisted in quote. Used for replay/test determinism and live volume-pace normalization. | Passed through if provided via `_resolve_expected_volume_fraction()` (line 861–871); otherwise computed via `_expected_cumulative_volume_fraction()` live wall-clock model (line 806–858). Bounded to [0.02, 1.0]. | Compute via 3-segment piecewise-linear time-of-day model: **0-30 min:** 0%→25%, **30-90 min:** 25%→40%, **90-390 min:** 40%→100% (line 851–856). Or persist in reference file keyed by symbol + session + (optional) time-of-day. |
| `changesPercentage` | `str` or `float` | Intraday % change from previous close; used in quote-hash for dirty-flag detection, NOT signal detection. | Extracted as-is (no type conversion in hash, line 1838); used to detect quote staleness. Skipping signal detection if quote unchanged (line 3273–3275). | Compute: `((close - previousClose) / previousClose) * 100`. Only for quote-dirty detection; not load-bearing for signal logic. |
| `bidPrice` | `float` | Best bid price in aftermarket **SHADOW ONLY** — NOT used in live signal detection. Used in `_poll_extended_shadow()` to compute midpoint price and cross detection for metrics. | Shadow-only code path in postmarket_quotes.py. Coerced via `_safe_float()` to 0.0 if missing (postmarket_quotes.py line 100). If bid > 0 and ask > 0 and bid ≤ ask, midpoint is used as extended price (line 112). Never feeds signal detection. | Databento aftermarket quotes or bids stream. Optional; if unavailable from 1s bar schema, derive from a dedicated bid/ask feed or omit with fallback to trade price. |
| `askPrice` | `float` | Best ask price in aftermarket **SHADOW ONLY** — NOT used in live signal detection. Used in `_poll_extended_shadow()` with `bidPrice` to compute midpoint; cross-detection gate prevents inverted midpoints. | Shadow-only code path in postmarket_quotes.py. Coerced via `_safe_float()` to 0.0 if missing (postmarket_quotes.py line 101). Cross-check: if bid > ask, row is rejected (line 103, 117–118). Never feeds signal detection. | Databento aftermarket quotes or asks stream. Optional; if unavailable from 1s bar schema, derive from a dedicated bid/ask feed or omit with fallback to trade price. |

---

## Data-Source Context

### Regular-Session Fields (Batch Quote)

Sourced from FMP's `/stable/batch-quote` endpoint (line 2646). The adapter MUST populate:
- `symbol`, `price`/`lastPrice`, `previousClose`, `volume`, `avgVolume`, `timestamp`, `changesPercentage`.
- **Source field:** should indicate "databento" or equivalent.

### Postmarket Fields (Aftermarket Quotes + Trades) — SHADOW-ONLY

**WARNING: Postmarket bid/ask/trade fields are UNWIRED for live signal detection.** They exist only in `_poll_extended_shadow()` (line 2633–2704) for metrics and telemetry, NOT for signal generation.

Sourced from FMP's `/stable/batch-aftermarket-quote` (line 2647) and `/stable/batch-aftermarket-trades` (line 2648) **only when** `_poll_extended_shadow()` runs (outside regular session). The adapter MAY populate:

- `bidPrice`, `askPrice` from aftermarket quotes (for future development or shadow monitoring);
- `price`, `timestamp` from aftermarket trade rows (for metrics only).
- **Postmarket logic in shadow:** trade price is preferred; if stale, fallback to bid/ask midpoint (postmarket_quotes.py, line 106–120).

**Signal detection only runs during regular session** (`_fetch_realtime_quotes()`, line 2584–2616). Postmarket data never feeds `_detect_signal()` (line 2709–2830).

### Reference Data (Daily)

- `previousClose`, `avgVolume`, and optional `expected_volume_fraction` (by time-of-day) must be sourced from a daily reference file keyed by symbol and session date.
- Databento's daily-bars schema (e.g., `ohlcv-1d`) can supply the prior session's close; ADV must be pre-computed (e.g., 20/30/60-day rolling average) and refreshed daily.

---

## Derivation Details

### Session-Time Price Fields

| Field | Derivation |
|-------|-----------|
| `dayHigh` | Running session-high, accumulated from all bars up to poll time. **GAP:** Not explicitly accessed in realtime_signals.py; implied by signal logic but not extracted. Candidates: maintain a session-high cache keyed by symbol, updated per bar. |
| `dayLow` | Running session-low, accumulated from all bars up to poll time. **GAP:** Not explicitly accessed in realtime_signals.py; implied by signal logic but not extracted. Candidates: maintain a session-low cache keyed by symbol, updated per bar. |

### Expected Volume Fraction

The field `expected_volume_fraction` is resolved at poll time via `_resolve_expected_volume_fraction()` (line 861–871):
1. **If quote carries the field:** use it (bounded to [0.02, 1.0]).
2. **Else:** compute from ET wall-clock time via `_expected_cumulative_volume_fraction()` (line 806–858):
   - **Pre-market** (< 9:30 ET): 0.02 (expect 2% of daily volume).
   - **Regular session** (9:30–close): **Front-loaded 3-segment piecewise-linear model:**
     - **0–30 min:** 0% → 25% (linear ramp)
     - **30–90 min:** 25% → 40% (linear ramp)
     - **90–390 min:** 40% → 100% (linear ramp)
   - **Post-market** (close–20:00 ET): 1.0 (raw ratio is fine).
   - **After 20:00 ET:** 1.0 (day is closed).

For replay determinism, the reference file may optionally pre-compute this field per symbol and hour of day.

---

## Null/Missing Handling Guarantees

1. **`price` and `previousClose` both missing/invalid:** Signal is skipped entirely (line 2755–2756). No fallback.
2. **`volume` missing or invalid:** Signal is skipped with debug log (line 2737–2743).
3. **`avgVolume` < 1000:** Signal is skipped (line 2748–2753). FMP batch-quote does not return this; fallback is `watchlist_entry.get("avg_volume")`.
4. **`timestamp` missing:** Normalized to None and recorded as `data_age_unknown=True` (a0_contract.py:153, 178); no rejection gate for live signals.
5. **`symbol` empty/missing:** Row excluded from quote-fetch dict (line 2608–2610); never enters signal detection.
6. **`bidPrice`, `askPrice` missing:** Only relevant in shadow (`_poll_extended_shadow()`); aftermarket midpoint derivation skipped, trade price is preferred (postmarket_quotes.py, line 106–120).

---

## Implementation Notes for Databento Adapter

### Must-Have Fields

The following fields are **load-bearing** (signal detection fails without them):
- `symbol`, `price`, `previousClose`, `volume`, `avgVolume`, `timestamp`.

### Nice-to-Have Fields

The following improve audit/replay but are not load-bearing:
- `received_at`, `source`, `expected_volume_fraction`, `changesPercentage`.
- **Postmarket shadow-only fields:** `bidPrice`, `askPrice` (**DO NOT** scope this as byte-parity critical; shadow-only, unwired from signal detection). If unavailable, shadows fall back to trade price or skip metrics.

### Caching & Session Awareness

1. **Session boundaries:** The adapter must track the regular-session date and close time (9:30–16:00 ET, or 15:30 for some symbols). Signal detection only runs during regular session.
2. **Cumulative volume reset:** Reset `volume` to 0 at each session boundary (4:00 AM ET).
3. **Reference data:** Pre-fetch and cache daily `previousClose` and `avgVolume` keyed by symbol + date; refresh at end-of-day or on-demand miss.
4. **Postmarket offset (shadow only):** For shadow metrics only, compute postmarket volume delta as `current_cumulative - session_close_baseline` (see postmarket_quotes.py, line 132–137).

---

## Code References

- **Realtime quote fetch:** `open_prep/realtime_signals.py:2584–2616` (`_fetch_realtime_quotes()` — regular session only).
- **Signal detection:** `open_prep/realtime_signals.py:2709–2830` (`_detect_signal()` — field reads on quote dict).
- **Quote hashing:** `open_prep/realtime_signals.py:1835–1839` (dirty-flag detection).
- **Extended shadow (metrics only):** `open_prep/realtime_signals.py:2633–2704` (`_poll_extended_shadow()` — postmarket feeds, no signaling).
- **Postmarket adapter:** `open_prep/postmarket_quotes.py:41–157` (postmarket volume & price normalization).
- **Expected-volume model:** `open_prep/realtime_signals.py:806–858` (`_expected_cumulative_volume_fraction()`).
- **Expected-volume resolver:** `open_prep/realtime_signals.py:861–871` (`_resolve_expected_volume_fraction()`).
- **Market snapshot builder:** `open_prep/a0_contract.py:138–179` (field normalization, audit metadata).
- **FMP client fetch:** `open_prep/macro.py:2164–2224` (`get_stable_batch_quotes()`).

---

## Summary

**13 fields** are read from an FMP quote row during signal detection and polling. **10 fields** are clean-derivable from Databento `ohlcv-1s` bars + daily reference data. **2 fields** (`dayHigh`, `dayLow`) require session-state caching but are implied rather than explicitly extracted. **1 field** (`expected_volume_fraction`) requires either reference pre-computation or live wall-clock calculation.

No mandatory gaps exist; all required fields can be sourced from Databento + a daily-reference file (e.g., previous close + ADV keyed by symbol and date).

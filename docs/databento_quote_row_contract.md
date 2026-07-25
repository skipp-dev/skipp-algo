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
| `symbol` | `str` | Stock ticker symbol, normalized to uppercase. | Skipped if missing or empty; see line 2639, 2641 in realtime_signals.py. | Extracted from bar's `symbol` column; reference-file symbol field. |
| `price` | `float` | Current last price, measured in dollars. Primary source for intraday price; fallback is `lastPrice`. | Coerced via `_safe_float()` with fallback to `lastPrice`; if both missing/invalid, returns 0.0 (line 2725); signal detection skipped if ≤ 0 (line 2755). | Last bar's `close` price from the current session. |
| `lastPrice` | `float` | Fallback price field, same semantic as `price`. | Only used if `price` is falsy or invalid (line 2725). | Same as `price`; last bar's `close`. |
| `previousClose` | `float` | Previous session's closing price; used to compute intraday % change and volume-ratio denominator. | Coerced via `_safe_float()` to 0.0 if missing; signal detection skipped if ≤ 0 (line 2755–2756). | Daily reference file's `previousClose` for the date. Must be persisted in session-date index. |
| `volume` | `float` (raw: `Any`) | Cumulative **regular-session** volume for the day at poll time, used for volume-ratio and pace normalization. | Raw value extracted without coercion (line 2727); then validated via `_safe_float()` (line 2728). If raw value is non-numeric or NaN/Inf, signal detection is skipped with debug log (line 2737–2743). | Cumulative regular-session volume up to poll time (sum of all 1-second bars' volumes in current session, from 9:30 ET onward). **Note:** postmarket flows have separate volume logic (see `build_postmarket_quotes()` in postmarket_quotes.py; postmarket volume = current - baseline). |
| `avgVolume` | `float` | Average daily trading volume (ADV), used to compute volume ratios and A0 thresholds; normalized to ≥1000 to avoid skipping signals. | Coerced via `_safe_float()` with fallback to `watchlist_entry.get("avg_volume")` (line 2730). If result < 1000, signal detection is skipped (line 2748–2753). **FMP batch-quote endpoint does NOT return this field today.** | Daily reference file's average daily volume (ADV); typically a 20/30/60-day rolling average. Must be keyed by symbol and session date. Fallback: watchlist dict if Databento reference lacks the field. |
| `timestamp` | `float` (epoch, ms or s) | Quote's arrival timestamp (nanoseconds or milliseconds since Unix epoch, depending on source). Used for freshness age calculations. | Coerced via `_safe_float()` with millisecond/second normalization (line 2672–2673): values ≥ 1 billion are divided by 1000 (ms→s). Freshness gate: -30 ≤ age ≤ 300 seconds (line 2676–2677). Postmarket adaptive: max_age_seconds = 300 (postmarket_quotes.py line 50). | Databento bar's `ts_event` (nanoseconds or provided timestamp); convert to seconds. For realtime polling, use the bar's last-update timestamp or ingest time. |
| `received_at` | `float` (epoch) | When the quote was received by the data provider. Used for audit trails in signal metadata. | Passed directly to `RealtimeSignal.raw_ts_recv` (line 2810); no validation. If missing, signal.raw_ts_recv is `None`. | Databento's reception timestamp or ingest time. If unavailable, use bar's `ts_event`. |
| `source` | `str` | Data-source identifier ("fmp" by default). Stored in signal metadata for traceability. | Coerced via `str()` with fallback default "fmp" (line 2808). | String literal "databento" or equivalent identifier to distinguish from FMP. |
| `expected_volume_fraction` | `float` ([0.02, 1.0]) | Expected cumulative volume fraction at current time, derived from time-of-day model or persisted in quote. Used for replay/test determinism and live volume-pace normalization. | Passed through if provided; otherwise computed via `_expected_volume_fraction()` live wall-clock model (line 2771). Bounded to [0.02, 1.0] (open_prep.realtime_signals line 861–880). | Compute via time-of-day model: `_expected_volume_fraction()` (line 828–880) using current ET time and regular-session hours (9:30–close). Or persist in reference file keyed by symbol + session + (optional) time-of-day. |
| `changesPercentage` | `str` or `float` | Intraday % change from previous close; used in quote-hash for dirty-flag detection, NOT signal detection. | Extracted as-is (no type conversion in hash, line 1838); used to detect quote staleness. Skipping signal detection if quote unchanged (line 3273–3275). | Compute: `((close - previousClose) / previousClose) * 100`. Only for quote-dirty detection; not load-bearing for signal logic. |
| `bidPrice` | `float` | Best bid price in aftermarket, used to compute midpoint price and cross detection. Extracted only from aftermarket-quote rows, not regular batch quotes. | Coerced via `_safe_float()` to 0.0 if missing (postmarket_quotes.py line 100). If bid > 0 and ask > 0 and bid ≤ ask, midpoint is used as extended price (line 112). | Databento aftermarket quotes or bids stream. If unavailable from 1s bar schema, derive from a dedicated bid/ask feed or omit with fallback to trade price. |
| `askPrice` | `float` | Best ask price in aftermarket, used with `bidPrice` to compute midpoint; cross-detection gate prevents inverted midpoints. | Coerced via `_safe_float()` to 0.0 if missing (postmarket_quotes.py line 101). Cross-check: if bid > ask, row is rejected (line 103, 117–118). | Databento aftermarket quotes or asks stream. If unavailable from 1s bar schema, derive from a dedicated bid/ask feed or omit with fallback to trade price. |

---

## Data-Source Context

### Regular-Session Fields (Batch Quote)

Sourced from FMP's `/stable/batch-quote` endpoint (line 2646). The adapter MUST populate:
- `symbol`, `price`/`lastPrice`, `previousClose`, `volume`, `avgVolume`, `timestamp`, `changesPercentage`.
- **Source field:** should indicate "databento" or equivalent.

### Postmarket Fields (Aftermarket Quotes + Trades)

Sourced from FMP's `/stable/batch-aftermarket-quote` (line 2647) and `/stable/batch-aftermarket-trades` (line 2648). The adapter MUST populate:
- `bidPrice`, `askPrice` from aftermarket quotes;
- `price`, `timestamp` from aftermarket trade rows.
- **Postmarket logic:** trade price is preferred; if stale, fallback to bid/ask midpoint (postmarket_quotes.py, line 106–120).

### Reference Data (Daily)

- `previousClose`, `avgVolume`, and optional `expected_volume_fraction` (by time-of-day) must be sourced from a daily reference file keyed by symbol and session date.
- Databento's daily-bars schema (e.g., `ohlcv-1d`) can supply the prior session's close; ADV must be pre-computed (e.g., 20/30/60-day rolling average) and refreshed daily.

---

## Derivation Details

### Session-Time Price Fields

| Field | Derivation |
|-------|-----------|
| `open` | First regular-session bar's `open` for the day. Used in signal details but not directly from quote row (see line 2684: `regular_by[symbol].get("price")` is used for reference). |
| `dayHigh` | Running session-high, accumulated from all bars up to poll time. **GAP:** Not explicitly accessed in realtime_signals.py; implied by signal logic but not extracted. Candidates: maintain a session-high cache keyed by symbol, updated per bar. |
| `dayLow` | Running session-low, accumulated from all bars up to poll time. **GAP:** Not explicitly accessed in realtime_signals.py; implied by signal logic but not extracted. Candidates: maintain a session-low cache keyed by symbol, updated per bar. |

### Expected Volume Fraction

The field `expected_volume_fraction` is computed at poll time via `_expected_volume_fraction()` (line 828–880):
1. **If quote carries the field:** use it (bounded to [0.02, 1.0]).
2. **Else:** compute from ET wall-clock time:
   - **Pre-market** (< 9:30 ET): 0.02 (expect 2% of daily volume).
   - **Regular session** (9:30–close): `(elapsed_minutes / 390) * fudge_factor`, clamped to [0.02, 1.0].
   - **Post-market** (close–20:00 ET): 1.0 (raw ratio is fine).
   - **After 20:00 ET:** 1.0 (day is closed).

For replay determinism, the reference file may optionally pre-compute this field per symbol and hour of day.

---

## Null/Missing Handling Guarantees

1. **`price` and `previousClose` both missing/invalid:** Signal is skipped entirely (line 2755–2756). No fallback.
2. **`volume` missing or invalid:** Signal is skipped with debug log (line 2737–2743).
3. **`avgVolume` < 1000:** Signal is skipped (line 2748–2753). FMP batch-quote does not return this; fallback is `watchlist_entry.get("avg_volume")`.
4. **`timestamp` missing:** Freshness check defaulting to 0.0 (line 2672); will fail freshness gate if current epoch >> 0.
5. **`symbol` empty/missing:** Row excluded from bulk processing (line 2639–2641).
6. **`bidPrice`, `askPrice` missing:** Aftermarket midpoint derivation skipped; trade price is preferred (postmarket_quotes.py, line 106–120).

---

## Implementation Notes for Databento Adapter

### Must-Have Fields

The following fields are **load-bearing** (signal detection fails without them):
- `symbol`, `price`, `previousClose`, `volume`, `avgVolume`, `timestamp`.

### Nice-to-Have Fields

The following improve audit/replay but are not load-bearing:
- `received_at`, `source`, `expected_volume_fraction`, `changesPercentage`.
- Postmarket fields: `bidPrice`, `askPrice` (used only in postmarket polling; if unavailable, falls back to trade price).

### Caching & Session Awareness

1. **Session boundaries:** The adapter must track the regular-session date and close time (9:30–16:00 ET, or 15:30 for some symbols).
2. **Cumulative volume reset:** Reset `volume` to 0 at each session boundary (4:00 AM ET).
3. **Reference data:** Pre-fetch and cache daily `previousClose` and `avgVolume` keyed by symbol + date; refresh at end-of-day or on-demand miss.
4. **Postmarket offset:** For postmarket volume, compute delta as `current_cumulative - session_close_baseline` (see postmarket_quotes.py, line 132–137).

---

## Code References

- **Main fetch loop:** `open_prep/realtime_signals.py:2646–2704` (polling + staleness check).
- **Signal detection:** `open_prep/realtime_signals.py:2709–2830` (field reads on quote dict).
- **Quote hashing:** `open_prep/realtime_signals.py:1835–1839` (dirty-flag detection).
- **Postmarket adapter:** `open_prep/postmarket_quotes.py:41–157` (postmarket volume & price logic).
- **Volume normalization:** `open_prep/realtime_signals.py:760–880` (time-of-day expected-volume model).
- **Polling retry logic:** `open_prep/macro.py:2164–2224` (FMP stable batch-quote fetch).

---

## Summary

**13 fields** are read from an FMP quote row during signal detection and polling. **10 fields** are clean-derivable from Databento `ohlcv-1s` bars + daily reference data. **2 fields** (`dayHigh`, `dayLow`) require session-state caching but are implied rather than explicitly extracted. **1 field** (`expected_volume_fraction`) requires either reference pre-computation or live wall-clock calculation.

No mandatory gaps exist; all required fields can be sourced from Databento + a daily-reference file (e.g., previous close + ADV keyed by symbol and date).

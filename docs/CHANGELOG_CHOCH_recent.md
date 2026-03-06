# CHOCH Indicator & Strategy — Recent Changes

## USI-CHOCH Early-Signal Upgrade (2026-03-05)

Applied the latest CHoCH fast-entry improvements to **`USI-CHOCH.pine`** to get
earlier BUY/CHoCH context without removing existing USI/VWAP logic.

### Added

- **Same-Bar Verify for bullish CHoCH**
  - `chochVerifyLong` now combines:
    - same-bar verification (`chochVerifyLong_samebar`), and
    - legacy next-bar verification (`chochVerifyLong_next`).
  - Effect: CHoCH confirmation can fire at the earliest possible bar.

- **Early Signals block (new inputs)**
  - `Enable Anticipation signals`
  - `Proximity %`
  - `Show Anticipation markers`
  - `Enable Momentum Pre-CHoCH`
  - `RSI Length`
  - `RSI Divergence lookback`
  - `Volume spike multiplier`
  - `Show Momentum Pre-CHoCH markers`

- **Anticipation logic (`A↑` / `A↓`)**
  - Emits early markers when price approaches swing levels with matching structure context.

- **Momentum Pre-CHoCH logic (`M↑` / `M↓`)**
  - Adds RSI-divergence + volume-spike early markers prior to structure break.

- **Visuals + alerts for early signals**
  - New marker shapes and optional background tint for anticipation and pre-CHoCH events.
  - New alertconditions:
    - `Anticipation Bullish`
    - `Anticipation Bearish`
    - `Momentum Pre-CHoCH Bullish`
    - `Momentum Pre-CHoCH Bearish`

### Notes

- Existing USI Flip BUY/SHORT and BEST Bullish CHoCH logic remain intact.
- Changes were integrated into `USI-CHOCH.pine` only (no behavior drift in other scripts unless explicitly ported).

## USI Bull-Momentum Filter (current)

**Problem:** EXIT and SHORT signals fired even when USI Red was above USI Blue,
i.e. during bullish momentum. This caused premature exits from winning long
positions and false short entries against the trend.

**Fix:** Added a **USI Bull Filter** that suppresses EXIT and SHORT signals
whenever `usiRed > usiBlue` (bullish momentum confirmed by the USI oscillator).

- New input toggle: `USI Bull Filter: block EXIT/SHORT while Red > Blue`
  (default: **on**, group: *Exit Extensions*)
- New variable `usiBullActive` — true when the USI system is enabled, the
  filter is on, and Red > Blue.
- `doShort` now requires `not usiBullActive`.
- `doExit` is fully suppressed while `usiBullActive` is true
  (via `doExitFiltered`).
- Applied identically to both **CHOCH-Indicator.pine** and
  **CHOCH-Strategy.pine**.

---

## Simplified Trade Labels (`09b380a`)

Consolidated the 8 priority-split EXIT/COVER plotshape calls
(EXIT-Struct, EXIT-EMA, EXIT-USI, EXIT-IMP, COVER-Struct, …) into a single
`plotshape` each. Labels now show only **BUY**, **SHORT**, **EXIT**, **COVER**
with no sub-type suffix text.

## Colored Trade Labels (`0ec502e`)

Changed all trade-label `plotshape` calls from `shape.triangleup/down` to
`shape.labelup/down`, added `textcolor=color.white`, and updated colours to
match the VWAP Long Reclaim indicator style:

| Signal | Color        | Shape      |
|--------|-------------|------------|
| BUY    | `color.lime`  | `labelup`  |
| SHORT  | `color.red`   | `labeldown`|
| EXIT   | `color.orange`| `labeldown`|
| COVER  | `color.teal`  | `labelup`  |

## Alertcondition Calls (`832c87b`)

Added `alertcondition()` declarations for all signals (Bullish/Bearish ChoCH,
BOS, combined structure events, BUY, SHORT, EXIT, COVER) so users can create
TradingView alerts per condition from the alert dialog.

## Consolidated Runtime Alerts

Alerts are batched into a single `alert()` call per bar using an array join
pattern (`array.push` + `array.join(_parts, "+")` +
`alert.freq_once_per_bar`). This prevents TradingView alert throttling on
large watchlists.

---

## Streamlit Terminal — Recent Fixes

| Commit | Change |
|--------|--------|
| `2d4b248` | **File watcher:** Changed `.streamlit/config.toml` `fileWatcherType` from `"none"` to `"auto"` so code changes trigger live hot-reload instead of requiring a full server restart. |
| `5321c5d` | **AI Insights buttons:** Switched preset/Ask Again/Clear buttons to direct `if button():` state mutation (no callbacks, no `st.rerun()`). |
| `6df33d0` | **AI Insights buttons:** Intermediate fix — `on_click` callback pattern. |
| `01b316d` | **Tab crash isolation:** Wrapped all 8 inline tab bodies in `_tab_guard` context manager to isolate render crashes. |
| `0afc4a0` | **AI Insights crash:** Fixed `StreamlitAPIException` caused by programmatically setting `fmp_ai_pause_auto_refresh` after its bound `st.toggle` widget rendered. Fixed mixed 2/4-space indentation. |
| `55483bd` | **Auto-refresh guard:** Added `_fmp_ai_executing` flag checked by the auto-refresh fragment to prevent reruns during long-running AI queries. |

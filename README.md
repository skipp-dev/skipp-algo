# SkippALGO — Outlook + Forecast (Calibrated Probabilities)

Pine Script v6 · Non-repainting · Bar-close confirmed

SkippALGO combines a signal engine with a multi‑timeframe dashboard that clearly separates:

- **Outlook (State):** current regime/bias snapshot per timeframe (non‑predictive).
- **Forecast (Probability):** calibrated probability of a defined forward outcome, gated by sample sufficiency.

## What you get

- Multi‑timeframe **Outlook** with bias, score, and components (Trend/Momentum/Location).
- **Forecast** block with Pred(N)/Pred(1) plus calibrated $P(\mathrm{Up})$.
- Strict **non‑repainting** behavior (`lookahead_off`, `barstate.isconfirmed`).
- Confidence gating, macro + drawdown guards, and MTF confirmation.

## Quick start

1. Add `SkippALGO.pine` to your TradingView chart.
2. Start with default horizons (1m–1d) and **predBins=3**.
3. Let calibration warm up (watch sample sufficiency in Forecast rows).
4. Read **Outlook first**, then confirm with **Forecast** probabilities.

## Table guide (short)

- **Outlook (State):** descriptive snapshot at the last confirmed bar for each TF.
- **Forecast (Prob):** conditional probability for the defined target (default: next‑bar direction).
- `…` and `n0` indicate insufficient data; do not treat as a signal.
- Forecast rows include **nCur/Total** and a target footer describing active target definitions.

## Documentation

- **Deep technical documentation:** `docs/SkippALGO_Deep_Technical_Documentation.md`
- **Deep technical documentation (current):** `docs/SkippALGO_Deep_Technical_Documentation_v6.2.22.md`
- **Kurzfassung für neue Nutzer:** `docs/SkippALGO_Kurzfassung_Fuer_Nutzer.md`
- **Roadmap enhancements:** `docs/SkippALGO_Roadmap_Enhancements.md`
- **Wiki (local mirror):** `docs/wiki/Home.md`
- **Changelog:** `CHANGELOG.md`

## Recent changes (Feb 2026)

- **Latest (v6.3.2 — 14 Feb 2026) — Hotfix 2:**
  - **Syntax Fix (v6.3.2)**: Replaced `color.cyan` with `color.aqua` to adhere to Pine Script v6 strictness.
  - **Syntax Fix (v6.3.1)**: Removed erratic duplicate code block in indicator logic that caused a compilation error.
  - **Cooldown Fix (v6.3.0)**: `cooldownMode` "Minutes" prevents H1/H4 charts from being blocked for hours.
  - **Fast Entries (v6.3.0)**: `cooldownTriggers` "ExitsOnly" logic explicitly allows add-on entries.
  - **QuickALGO (v6.3.0)**: Optimized to Score+Verify logic; fixed MTF repainting.
  - **Validation**: Full regression test suite passed (339 tests).
  - **Pine Hardening**: Fixed type-safety issues in `ta.barssince` logic across all scripts.

- **Latest (12 Feb 2026) — QuickALGO signal/context upgrade:**
  - Added optional **3-candle engulfing filter** (default OFF) in both indicator and strategy:
    - Long entries require bullish engulfing after 3 bearish candles.
    - Short entries require bearish engulfing after 3 bullish candles.
    - Optional body-dominance check (`body > previous body`).
    - Optional engulfing bar coloring (bullish yellow / bearish white).
  - Added optional **ATR volatility context layer** (default OFF) in both scripts:
    - Regime overlay: `COMPRESSION`, `EXPANSION`, `HIGH VOL`, `EXHAUSTION`.
    - Regime label with ATR ratio.
    - Optional ATR percentile context (`0..100`) with configurable lookback.
  - All additions were implemented with **Indicator ⇄ Strategy parity** and validated without diagnostics errors.

- **Latest (12 Feb 2026) — PRE label intelligence + parity hardening:**
  - PRE labels were upgraded from static `plotshape` markers to dynamic `label.new()` payloads in **both** scripts.
  - PRE-BUY / PRE-SHORT now show:
    - trigger **Gap** in ATR units (distance-to-trigger),
    - directional probability (`pU` / `pD`),
    - model confidence (`Conf`).
  - Gap semantics are engine-aware:
    - **Hybrid:** close ↔ EMA fast distance
    - **Breakout:** close ↔ swing high/low distance
    - **Trend+Pullback:** EMA flip/reclaim proximity
    - **Loose:** close ↔ EMA fast proximity
  - ChoCH behavior was aligned back to v6.2.18 intent:
    - visual ChoCH structure tags are not probability-filtered,
    - `chochMinProb` remains an entry-level gate (not a visual marker gate).

- **TradingView settings persistence:**
  - Script titles were stabilized to avoid input resets on updates:
    - `indicator("SkippALGO", ...)`
    - `strategy("SkippALGO Strategy", ...)`
- **REV probability controls (clarified and exposed):**
  - Added `REV: Min dir prob` (`revMinProb`, default `0.50`) for the normal REV entry path.
  - `Rescue Mode: Min Probability` (`rescueMinProb`) continues to govern only the rescue fallback path (with huge volume + impulse).
- **Open-window behavior:**
  - Near market open (±window), pU filter bypass applies to standard and reversal entries as configured.
- **Exit/Cover label formatting:**
  - Long first line was split into multiple rows for better readability on chart labels.
- **Watchlist alert stability:**
  - Reworked alert dispatch to send at most **one consolidated `alert()` per bar** per symbol (instead of multiple independent alert calls), reducing TradingView throttling / “eingeschränkte Funktionalität” risk on large watchlists.

- **Parity fixes (Indicator ⇄ Strategy):**
  - Loose engine now applies `enhLongOk/enhShortOk` consistently in both scripts.
  - `barsSinceEntry` now starts at `0` on the entry bar in both scripts (no risk-decay tightening on the entry bar) and uses `>=` for `canStructExit`.
  - Regression Slope (RegSlope) subsystem is now supported in the Strategy as well (inputs + helpers + gating in `enhLongOk/enhShortOk`).
- **Governance:** added regression tests to lock these behaviors and keep future edits honest.

## Current verification status

- **Pytest:** See latest CI run attached to the active pull request (count evolves as tests are added).
- Includes dedicated regression coverage for:
  - PRE-BUY / PRE-SHORT signal plumbing and dynamic label payloads,
  - BUY / REV-BUY / EXIT label + alert wiring,
  - Indicator/Strategy parity-critical entry/exit invariants.

## License

This project is distributed under the Mozilla Public License 2.0 (see source headers).

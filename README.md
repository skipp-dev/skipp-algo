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
- **Roadmap enhancements:** `docs/SkippALGO_Roadmap_Enhancements.md`
- **Wiki (local mirror):** `docs/wiki/Home.md`

## Recent changes (Feb 2026)

- **TradingView settings persistence:**
  - Script titles were stabilized to avoid input resets on updates:
    - `indicator("SkippALGO", ...)`
    - `strategy("SkippALGO Strategy", ...)`
- **REV probability controls (clarified and exposed):**
  - Added `REV: Min pU` (`revMinProb`, default `0.50`) for the normal REV entry path.
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

## License

This project is distributed under the Mozilla Public License 2.0 (see source headers).

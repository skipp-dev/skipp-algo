# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [2026-02-12]

### Added (Signals & Volatility)

- New input: `REV: Min pU` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed (Parity)

- Stabilized script titles to preserve TradingView input settings across updates:
  - `indicator("SkippALGO", ...)`
  - `strategy("SkippALGO Strategy", ...)`
- Consolidated runtime alert dispatch to one `alert()` call per bar per symbol, reducing watchlist alert-rate pressure and TradingView throttling risk.
- EXIT/COVER label text layout split into shorter multi-line rows for better chart readability.
- Open-window pU bypass behavior applies during configured market-open window as implemented in current logic.

### Clarified

- `Rescue Mode: Min Probability` (`rescueMinProb`) controls only the rescue fallback path (requires volume + impulse), while `revMinProb` controls the normal REV path.

### Fixed

- Corrected Strategy-side forecast gate indentation/structure parity so open-window bypass behavior is consistently applied.

### Added

- Optional **3-candle engulfing filter** (default OFF) in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Long entries require bullish engulfing after 3 bearish candles.
  - Short entries require bearish engulfing after 3 bullish candles.
  - Optional body-dominance condition (`body > previous body`).
  - Optional engulfing bar coloring (bullish yellow / bearish white).
- Optional **ATR volatility context layer** (default OFF) in both scripts:
  - Regime overlay and label: `COMPRESSION`, `EXPANSION`, `HIGH VOL`, `EXHAUSTION`.
  - ATR ratio to configurable baseline (`SMA`/`EMA`).
  - Optional ATR percentile context (`0..100`) with configurable lookback.

### Changed

- Maintained strict **Indicator ⇄ Strategy parity** for new signal/context features to avoid behavior drift between visual and strategy paths.

---

## Notes

- This changelog tracks user-facing behavior and operational reliability updates.
- Historical items before this file was introduced may still be referenced in commit history and docs.

# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [2026-02-12]

### Added

- New input: `REV: Min pU` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed

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

---

## Notes

- This changelog tracks user-facing behavior and operational reliability updates.
- Historical items before this file was introduced may still be referenced in commit history and docs.

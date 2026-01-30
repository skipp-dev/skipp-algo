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

## Documentation

- **Deep technical documentation:** `docs/SkippALGO_Deep_Technical_Documentation.md`
- **Roadmap enhancements:** `docs/SkippALGO_Roadmap_Enhancements.md`
- **Wiki (local mirror):** `docs/wiki/Home.md`

## License

This project is distributed under the Mozilla Public License 2.0 (see source headers).

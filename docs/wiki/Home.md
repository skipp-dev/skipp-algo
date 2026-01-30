# SkippALGO Wiki

Welcome to the SkippALGO wiki. This local wiki mirrors the GitHub Wiki content for the repository.

## Overview

SkippALGO is a Pine Script v6 indicator that separates **Outlook (State)** from **Forecast (Probability)**:

- **Outlook (State):** current regime snapshot per timeframe (non‑predictive).
- **Forecast (Probability):** calibrated probability of a defined forward outcome with sample‑size gating.

## Getting started

1. Add `SkippALGO.pine` to your TradingView chart.
2. Use default horizons (1m–1d) and **predBins=3** to warm up faster.
3. Read **Outlook** first, then confirm with **Forecast** probabilities.

## Table semantics (short)

- **Outlook (State):** last confirmed bar snapshot for each TF.
- **Forecast (Prob):** conditional probability for the defined target.
- `…` or `n0` means insufficient data.

## Documentation

- Deep technical documentation: `docs/SkippALGO_Deep_Technical_Documentation.md`
- Roadmap: `docs/SkippALGO_Roadmap_Enhancements.md`

## Roadmap highlights

- Alternate forecast targets (k‑bar return, ATR‑normalized, path‑based TP/SL)
- Per‑TF sample counts in the table
- Per‑TF calibration reset

# Getting Started with SkippALGO Strategy in TradingView

**Date:** 17 Feb 2026
**Version:** v6.3.13

## Introduction

This guide explains how to transition from the **SkippALGO Indicator** (signals only) to the **SkippALGO Strategy** (backtesting and trade management). Unlike the indicator, the strategy file simulates specific entry and exit rules, allowing you to see historical performance and potential outcomes.

## 1. How to Add the Strategy Script

1. **Open Pine Editor**: At the bottom of your TradingView interface, click the tab labeled `Pine Editor`.
2. **Paste Code**: Copy the entire content of the `SkippALGO_Strategy.pine` file and simple paste it into the editor window (delete any default code first).
3. **Add to Chart**: Click the **"Add to chart"** button in the top right corner of the editor panel.
    * *Result*: You will see standard blue (Long) and red (Short) arrows appear on your chart candles where trades would have occurred.

## 2. Visualizing Your Risk (TP & SL)

Once a position is open (on the chart), the Algo draws lines to show your active risk parameters:

* 🔴 **Red Line (Stop Loss)**: The price level where the trade will be closed to prevent further loss.
* 🟢 **Green Line (Take Profit)**: The target price level where profits will be secured.
* 🟠 **Orange Line (Trailing Stop)**: If active, this line trails behind price to lock in profits as the trend continues.

*Note: These lines act as a visual confirmation of what the internal logic is doing.*

## 3. The "Automation" Reality Check

New users often assume that connecting a broker (like IBKR) to TradingView allowing the Strategy setup to trade automatically. **This is not the case.**

### The Limitation

* **Trading Panel**: The manual trading buttons (Buy/Sell) connect directly to your broker (IBKR).
* **Pine Strategy**: The script runs on TradingView's servers/browser and **does not have permission** to click those manual buttons for you.

### How Automation Actually Works

To automate execution with IBKR (or any broker) via TradingView, you generally need three components:

1. **The Trigger**: A TradingView **Alert** created from your Strategy.
2. **The Messenger**: A **Webhook URL** entered in the Alert settings.
3. **The Executor**: A 3rd-party bridge service (e.g., *Capitalise.ai*, *3Commas*, *TradersPost*) that receives the Webhook signal and then sends the API order to IBKR.

### Recommended Beginner Workflow

Do not rush into complex automation. Start with this workflow:

1. **Validation**: Use the **Strategy Tester** tab (next to Pine Editor) to verify that your settings would have been profitable on recent data.
2. **Signaling**: Set an Alert on the Strategy to notify you (App/Popup/Email) when a signal triggers.
3. **Execution**: When the alert fires:
    * Check the chart.
    * Verify the setup.
    * Manually execute the trade in your IBKR Trading Panel.

This "Semi-Automated" approach is safer and helps you learn the Algo's personality before trusting it with unattended money.

## 4. Important Behavior Updates (Feb 14–15, 2026)

### A) USI direction hard-filter is now strict

For score-based entries, direction conflicts are blocked by design:

* If USI is **Bearish** (`usiBearState`), **BUY is blocked**.
* If USI is **Bullish** (`usiBullState`), **SHORT is blocked**.

This prevents momentum-only counter-trend entries when USI structure disagrees.

### B) Optional faster USI Red line (controlled)

You can enable a de-lagged Red line (Line5) without changing all USI lines:

* `useUsiZeroLagRed`
* `usiZlAggressiveness`

Recommended starting point for live A/B testing: **75%** aggressiveness.

Fast scalping preset (aggressive USI verify):

* `USI Aggressive: same-bar verify = ON`
* `USI Aggressive: verify 1-of-3 = ON`
* `USI Aggressive: tight-spread votes = ON` (optional; relaxes strict tight-spread Hold+Continuation)
* `Hardened Hold (L5 > L4) = OFF`

Optional profile for earlier entries:

* `Entry behavior profile = Scalp Early (v6.3.12-fast)`
  * lowers score thresholds,
  * slightly lowers probability/ChoCH thresholds,
  * disables score confidence hard-gate for faster confirmation timing.

### B.1) Faster ChoCH detection (Strategy parity)

ChoCH timing controls are now available in the Strategy exactly like in the Indicator:

* `ChoCH signal mode`:
  * `Ping (Fast)` = immediate structure ping,
  * `Verify (Safer)` = requires one-bar confirmation,
  * `Ping+Verify` = accepts either.
* `Show ChoCH Ping markers` adds `?` ping markers on chart for visual timing checks.

New fast presets:

* `ChoCH Scalp Fast preset`
  * forces `Breakout Source = Wick`,
  * forces `ChoCH signal mode = Ping (Fast)`,
  * uses effective `swingR = max(swingR, 1)`.
* `ChoCH Fast+Safer preset`
  * forces `Breakout Source = Wick`,
  * forces `ChoCH signal mode = Ping+Verify`,
  * uses effective `swingR = max(swingR, 1)`.

HUD note:

* the Strategy eval HUD now shows active ChoCH runtime mode, for example:
  * `ChoCH=Fast (Ping (Fast),Wick,R=1)`.

### C) USI touch-based flip sensitivity improved

USI flip detection around Red-vs-Blue/Envelope transitions now handles practical touch behavior more reliably (not only hard visual separation), improving exit timing on fast transitions.

### D) Score + Chop integration clarified

Score integration now runs in hybrid mode:

* Score can inject entries (`engine OR score`).
* Active chop can still block final entry via `chopVeto`.
* Optional directional context hardening is available via `scoreRequireDirectionalContext` (default ON):
  * score BUY injection requires bullish context,
  * score SHORT injection requires bearish context.

Global score-probability floor note:

* `Enforce score min pU/pD on all entries` does **not** block `REV-BUY`.
* `REV-BUY` keeps its dedicated reversal probability gates (`revMinProb` + reversal/open-window path logic).
* Practical note: if `revMinProb` is already above your score `min pU`, toggling the score floor may appear to have no visible impact on `REV-BUY`.

For diagnostics, score debug output now includes:

* `chop:0/1`
* `veto:0/1`
* `ctxL:0/1`, `ctxS:0/1`
* `BLOCK:...` reason (for example `IN_POSITION`)

If `SCORE BUY` is above threshold but no trade is opened, check in this order:

1. `BLOCK` (position/state gate),
2. `veto` (chop veto),
3. `ctxL` / `ctxS` (directional-context gate).

### E) Unified exit trigger (LONG and SHORT)

Exit logic is now intentionally unified in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:

* `riskExitHit` (TP / SL / Trailing)
* `usiExitHit`
* `engExitHit`

The final close condition is an OR-union:

* `riskExitHit OR usiExitHit OR engExitHit`

So whichever exit source triggers first closes the open position (for both EXIT and COVER paths).

### F) Cooldown semantics on exits restored

Cooldown timestamp updates now occur again on real exit events:

* If `cooldownTriggers = ExitsOnly` or `AllSignals`, EXIT/COVER events update the cooldown timer.
* This applies symmetrically to LONG and SHORT handling.

Available cooldown trigger modes:

* `ExitsOnly` (default): timer updates on EXIT/COVER.
* `AllSignals`: timer updates on BUY/SHORT/EXIT/COVER.
* `EntriesOnly`: timer updates only on BUY/SHORT.

Indicator setting parity note:

* `SkippALGO.pine` now exposes both same-bar re-entry toggles:
  * `Allow same-bar BUY after COVER`
  * `Allow same-bar SHORT after EXIT`

Execution-order note (important for live expectations):

* The runtime processes **exits first**, then **entries** on each confirmed bar.
* Therefore, a freshly opened `BUY`/`SHORT` on bar $N$ cannot be exited on the same bar $N$ by this state machine.
* In `EntriesOnly` mode with `cooldownBars >= 1`, the strategy enforces one full-bar hold after entry for generic exits.
* For `cooldownBars = 1`, earliest possible generic `EXIT` is bar $N+2$.
* Exceptions in `EntriesOnly`: `EXIT SL` and `COVER` can fire immediately after entry.

Concrete example (your setup):

* `cooldownBars = 1`
* `cooldownTriggers = EntriesOnly`
* `Allow same-bar BUY after COVER = true`
* `Allow same-bar SHORT after EXIT = true`

Behavior timeline:

1. Bar $N$: `BUY` fires and opens long.
1. Bar $N+1$: generic `EXIT` is still blocked by the one-full-bar hold rule.
1. Cooldown stamping with `EntriesOnly` happens only on `BUY`/`SHORT`, not on `EXIT`/`COVER`.
1. With `cooldownBars = 1` and checks `bar_index - enBar > 1` (generic exit hold) and `bar_index - lastSignalBar > 1` (entry cooldown), bar $N+1$ is blocked for generic exits and new entries, while bar $N+2$ allows both again.
1. If Stop Loss is hit, `EXIT SL` is allowed immediately even during that hold window; short-side `COVER` is also allowed immediately.
1. If an `EXIT`/`COVER` and opposite entry condition coincide on the same bar, the same-bar toggles allow immediate flip (`COVER → BUY`, `EXIT → SHORT`) as configured.

### G) Optional dynamic TP expansion

You can now enable a dynamic TP mode that increases TP distance as the trade develops:

* `useDynamicTpExpansion` (default ON)
* `dynamicTpKickInR` (when expansion starts)
* `dynamicTpAddATRPerR` (how fast TP expands)
* `dynamicTpMaxAddATR` (hard cap)
* optional gates: `dynamicTpRequireTrend`, `dynamicTpRequireConf`, `dynamicTpMinConf`

Behavior details:

* Expansion is **outward-only** (it will not tighten TP by itself).
* Works for both LONG and SHORT.
* Coexists with existing SL/Trail/USI/Engulfing exits; first active exit trigger still closes the position.

### H) Dynamic SL profile (default ON)

Adaptive stop behavior is available in both scripts:

* `useDynamicSlProfile` (default ON)
* Early anti-noise widening:
  * `dynamicSlWidenUntilR`
  * `dynamicSlMaxWidenATR`
* Progressive tightening as trade matures:
  * `dynamicSlTightenStartR`
  * `dynamicSlTightenATRPerR`
  * `dynamicSlMaxTightenATR`
* optional gates: `dynamicSlRequireTrend`, `dynamicSlRequireConf`, `dynamicSlMinConf`

Behavior details:

* Widening is automatically disabled after BE hit or when trailing is active.
* Tightening remains active under gate conditions.

### I) Entry presets + optional preset-controlled cooldown

Score Engine now supports profile-based tuning:

* `entryPreset = Manual | Intraday | Swing`
* `presetAutoCooldown` (default `false`)

Preset behavior:

* Presets map to effective score variables (`*_Eff`) for thresholds, weights, and probability floors.
* `Manual` keeps the direct user inputs.

Cooldown behavior:

* If `presetAutoCooldown = false` (default), cooldown remains fully input-driven (`cooldownMode`, `cooldownMinutes`, `cooldownTriggers`).
* If `presetAutoCooldown = true` and preset ≠ Manual:
  * cooldown mode is forced to `Bars`,
  * cooldown triggers are forced to `ExitsOnly`,
  * preset cooldown minutes are applied (Intraday/Swing profile values).

### J) Hard confidence gate for score entries (default ON)

To filter low-confidence score entries, an explicit confidence-floor gate is available:

* `scoreUseConfGate`
* `scoreMinConfLong`
* `scoreMinConfShort`

Current defaults (indicator + strategy):

* `scoreUseConfGate = true`
* `scoreMinConfLong = 0.50`
* `scoreMinConfShort = 0.50`

Behavior details:

* Score BUY requires score threshold and confidence floor (`conf >= scoreMinConfLong`) when enabled.
* Score SHORT requires score threshold and confidence floor (`conf >= scoreMinConfShort`) when enabled.
* This gate works together with existing probability and directional-context gates.

### K) Strategy compile-token optimization note

To keep the strategy safely under Pine compile-token limits, strategy-side visual payload was trimmed:

* score debug text was compacted,
* table rendering in `SkippALGO_Strategy.pine` was removed (visual-only).

Important: signal generation, risk logic, and Indicator ⇄ Strategy parity for decision paths remain unchanged.

### L) Preset: Intrabar labels (repainting ON)

Use this preset when you intentionally want BUY/EXIT and SHORT/COVER labels before candle close (realtime preview behavior):

* `Alerts: bar close only = false`
* `Show Long labels (BUY / EXIT) = true`
* `Show Short labels (SHORT / COVER) = true`
* `Show PRE labels (PRE-BUY / PRE-SHORT) = true`

Notes:

* This mode is intentionally intrabar/repainting and may differ from close-confirmed outcomes.
* Preview labels are realtime-only; historical bars still reflect confirmed logic.

### M) Sideways/Chop semantics (naming + intent)

To avoid confusion, the codebase now treats three concepts separately:

* `sidewaysVisual` (UX / chart visibility)

* Purpose: chart dots + consolidation alert wording.
* It is a visual state, not a direct entry gate.
* In the **indicator**, this visual state uses hysteresis so consolidation is less “sticky”.
* In the **strategy**, the same hysteresis model is now applied for consolidation alert state parity.

* `chopRisk` (score risk shaping)

* Purpose: apply chop penalty and optional score-veto behavior.
* Scope: score engine quality control (`scoreL/scoreS`, optional veto path).
* Not the same as visual consolidation dots.

* `usiTightSpread` (USI verify strictness)

* Purpose: make QP verify logic stricter when spread compression is detected.
* Scope: USI Fast+Verify step only (verification strictness), not the global consolidation state.

Practical takeaway:

* If you see long consolidation dots, inspect `sidewaysVisual` tuning.
* If score entries are reduced, inspect `chopRisk` / score veto settings.
* If QP entries feel stricter/looser, inspect `usiTightSpread` drivers (`usiTightFactor`, `usiSpreadLookback`).

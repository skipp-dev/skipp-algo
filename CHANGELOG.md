# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

## [Unreleased]

### Added (2026-02-20)

- **VWT integration (Volume Weighted Trend) in Indicator + Strategy:**
  - Added configurable VWT filter inputs in both scripts:
    - `useVwtTrendFilter`
    - `vwtPreset` (`Auto`, `Default`, `Fast Response`, `Smooth Trend`, `Custom`)
    - `vwtLengthInput`, `vwtAtrMultInput`
    - `vwtReversalOnly`, `vwtReversalWindowBars`
    - `showVwtTrendBackground`, `vwtBgTransparency`
  - Added effective Auto mapping (`vwtPresetEff`, `vwtReversalWindowEff`) based on `entryPreset`.
  - Added VWT runtime state and entry guards:
    - `vwtTrendDirection`, `vwtTurnedBull/Bear`, `vwtBullRecent/BearRecent`
    - `vwtLongEntryOk` / `vwtShortEntryOk`
  - Wired VWT gates into all entry paths:
    - engine gates (`gateLongNow`, `gateShortNow`),
    - reversal globals (`revBuyGlobal`, `revShortGlobal`),
    - score entries (`scoreBuy`, `scoreShort`).

- **Optional VWT trend background overlay (Indicator + Strategy):**
  - Added regime-based background coloring for bullish/bearish VWT trend state.

- **New regression tests for VWT feature:**
  - `tests/test_skippalgo_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`
  - `tests/test_skippalgo_strategy_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`

### Verification (2026-02-20)

- Full test run completed locally:
  - **478 passed, 16 subtests passed, 0 failed**.

### Added

- **ChoCH fast-mode parity in Strategy (v6.3.13 line):**
  - Added Strategy-side ChoCH runtime controls to match Indicator behavior:
    - `ChoCH signal mode` (`Ping (Fast)`, `Verify (Safer)`, `Ping+Verify`),
    - `Show ChoCH Ping markers`.
  - Added Strategy ChoCH presets:
    - `ChoCH Scalp Fast preset` (forces `Wick` + `Ping (Fast)` + effective `swingR=max(swingR,1)`),
    - `ChoCH Fast+Safer preset` (forces `Wick` + `Ping+Verify` + effective `swingR=max(swingR,1)`).
  - Strategy eval HUD now appends active ChoCH runtime configuration (`preset/mode/source/R`) for on-chart verification.

- **Runtime Success-Rate HUD + Eval mode guidance (indicator + strategy):**
  - Added a lightweight last-bar chart label showing live evaluation success rate and sample count:
    - `Success rate (History+Live): xx% (N=yy)` or
    - `Success rate (LiveOnly): xx% (N=yy)`
  - Added explicit `Evaluation mode` tooltip guidance with practical examples:
    - `History+Live` shows immediate populated values from confirmed history,
    - `LiveOnly` starts at `0% (N=0)` on historical bars and grows only in realtime.

- **Configurable BUY re-entry timing after COVER (indicator + strategy):**
  - Added `allowSameBarBuyAfterCover` (default `false`) to both scripts.
  - `false` keeps legacy one-bar delay after a `COVER` before the next `BUY`.
  - `true` allows immediate same-bar `COVER → BUY` re-entry.

- **Configurable SHORT re-entry timing after EXIT (strategy):**
  - Added `allowSameBarShortAfterExit` (default `false`) to strategy.
  - `false` keeps legacy one-bar delay after an `EXIT` before the next `SHORT`.
  - `true` allows immediate same-bar `EXIT → SHORT` re-entry.

- **Same-bar reversal mapping correction (indicator + strategy):**
  - Corrected cross-directional pairing to match runtime exit semantics:
    - `BUY` same-bar control is now `COVER → BUY` (`allowSameBarBuyAfterCover`),
    - `SHORT` same-bar control is now `EXIT → SHORT` (`allowSameBarShortAfterExit`).
  - Rewired phase-2 guards accordingly (`didCover` for BUY, `didExit` for SHORT).
  - Added regression tests to lock this mapping and prevent future inversion.

- **USI Length 5 lower-bound update (indicator + strategy):**
  - `Length 5 (fastest / Red)` now supports `minval=1` (previously `2`) in both scripts.
  - This allows a more aggressive fast-line configuration for USI Quantum Pulse tuning.

- **USI Aggressive Entry Mode guidance (indicator + strategy):**
  - Compact fast-scalping preset recommendation:
    - `USI Aggressive: same-bar verify = ON`
    - `USI Aggressive: verify 1-of-3 = ON`
    - `USI Aggressive: tight-spread votes = ON` (optional)
    - `Hardened Hold (L5 > L4) = OFF`

- **Scalp Early entry behavior profile (indicator + strategy):**
  - Added `Scalp Early (v6.3.12-fast)` to `Entry behavior profile`.
  - Keeps v6.3.12 structure but biases for earlier entries via:
    - slightly lower score thresholds,
    - slightly lower directional/score probability thresholds,
    - lower ChoCH probability threshold,
    - disabled score confidence hard-gate.

- **Cooldown trigger mode `EntriesOnly` (indicator + strategy):**
  - Added new `cooldownTriggers` option `EntriesOnly` in both scripts.
  - `EntriesOnly` updates cooldown timestamps only on entry signals (`BUY`/`SHORT`).
  - In `EntriesOnly` with `cooldownBars >= 1`, exits are hold-gated by entry bar index to enforce one full bar after entry before `EXIT`/`COVER` can fire.
  - Exception update: `EXIT SL` and `COVER` bypass this hold and may fire immediately after entry.
  - Existing modes remain unchanged:
    - `ExitsOnly` updates on `EXIT`/`COVER`.
    - `AllSignals` updates on all signals.

- **Global directional probability floors (indicator + strategy):**
  - Added `Enforce score min pU/pD on all entries` (default `true`).
  - When enabled, `Score min pU (Long)` / `Score min pD (Short)` are enforced as hard floors across BUY/SHORT entry paths.
  - `REV-BUY` is exempt and keeps its dedicated reversal probability gates (`revMinProb` + reversal/open-window logic).
  - Added `Global floor: bypass in open window` (default `true`) to optionally preserve open-window entry behavior.

- **Dedicated REV alert conditions (indicator + strategy):**
  - Added standalone `REV-BUY` and `REV-SHORT` alert conditions.
  - Consolidated runtime alert text now prioritizes `REV-BUY`/`REV-SHORT` labels over generic `BUY`/`SHORT` when reversal entries fire.

- **Dedicated consolidation alert condition (indicator + strategy):**
  - Added standalone `CONSOLIDATION` alert condition.
  - Trigger is phase-entry based (`sidewaysVisual and not sidewaysVisual[1]`) to avoid repeated alerts on every consolidation bar.

- **Sideways visual hysteresis parity (strategy):**
  - Strategy now uses the same visual consolidation hysteresis model as indicator (`sideEnter`/`sideExit` + latched `sidewaysVisual`).
  - This aligns consolidation alert timing semantics across both scripts without changing engine-side entry gating.

- **Consolidation dot color refinement (indicator):**
  - Consolidation dots are now **reddish** when USI is short (`usiStackDir == -1`).
  - All other consolidation states remain **orange**.

- **Directional consolidation entry veto (indicator + strategy):**
  - `BUY` is blocked during bearish/reddish consolidation.
  - `SHORT` is blocked during bullish/orange consolidation.
  - Veto applies to entries only; exits keep normal behavior.

- **Directional consolidation entry veto removed (indicator + strategy):**
  - Consolidation dot color/state is now informational only.
  - `BUY`/`SHORT` are no longer directly blocked by bearish/bullish consolidation dot state.

- **Intrabar alerts/labels default enabled (indicator + strategy):**
  - `Alerts: bar close only` now defaults to `false`.
  - Runtime alert/label flow is intrabar-first by default for BUY/SHORT/EXIT/COVER and PRE-BUY/PRE-SHORT.
  - Close-confirmed-only behavior remains available by setting `Alerts: bar close only = true`.

- **v6.3.13 parity hardening (indicator + strategy):**
  - restored strict entry gating parity in Strategy (`reliabilityOk`, `evidenceOk`, `evalOk`, `abstainGate/decisionFinal`) while preserving session filtering,
  - added full Strategy-side dynamic TP/SL runtime profile support:
    - Dynamic TP expansion (`useDynamicTpExpansion`, `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`, trend/conf gates),
    - Dynamic SL profile (`useDynamicSlProfile`, widen/tighten phases, trend/conf gates),
    - preset-driven effective dynamic TP mapping (`Manual/Conservative/Balanced/Runner/Super Runner`) aligned with indicator.
- **Structure tag wiring completed:**
  - Strategy now renders BOS/ChoCH structure tags (not only entry/exit labels),
  - Indicator now renders BOS tags alongside existing ChoCH tags.
- **ChoCH volume requirement wired:**
  - `chochReqVol` now actively gates ChoCH-triggered entries in both scripts.

### Verification

- Targeted strict-related suites (local, 2026-02-16): **152 passed, 8 subtests passed**.
- Full regression suite (local, 2026-02-16): **390 passed, 16 subtests passed**.

- **Entry behavior profile toggle (legacy timing fallback):** added `entryBehaviorProfile` in indicator + strategy under **Score Engine (Option C)**:
  - `Current (v6.3.12)` keeps stricter score gating/chop veto behavior.
  - `Legacy (v6.3.9-like)` relaxes entry strictness for earlier signal timing by:
    - disabling score probability and confidence hard-gates,
    - disabling score directional-context hard requirement,
    - disabling hard chop veto in final score merge,
    - disabling Regime Classifier 2 auto-tightening,
    - slightly loosening ChoCH probability threshold.

  ### Changed

  - **Fallback activated by default:** `entryBehaviorProfile` now defaults to `Legacy (v6.3.9-like)` in both indicator and strategy for immediate v6.3.9-like signal timing behavior out of the box.

## [v6.3.13] - 2026-02-16

### Added

- Strategy parity completion for dynamic runtime risk modules:
  - Dynamic TP expansion,
  - Dynamic SL profile (widen/tighten),
  - preset-aware effective dynamic TP mapping.
- Structure visualization parity updates:
  - BOS tags now rendered in indicator,
  - BOS/ChoCH structure tags now rendered in strategy.

### Changed

- Restored strict Strategy entry gating parity with indicator:
  - reliability/evidence/eval/abstain decision checks active again in `allowEntry`.
- Wired `chochReqVol` into ChoCH-triggered entry filtering in both scripts.
- Version sync: bumped visible script versions/titles to `v6.3.13`.

### Verification

- Full regression suite: **386 passed**.

## [v6.3.12] - 2026-02-15

### Added

- **RFC v6.4 Phase-3 quality tuning (regime hysteresis):** added state-stability controls for Regime Classifier 2.0 in both scripts:
  - `regimeMinHoldBars` (minimum hold duration before non-shock regime switches)
  - `regimeShockReleaseDelta` (VOL_SHOCK release threshold hysteresis)
  - latched regime logic via `rawRegime2State`, `regime2State`, `regime2HoldBars`
  - shock persistence rule keeps `VOL_SHOCK` active until ATR percentile cools below release threshold

### Changed

- **Version sync:** bumped visible script versions to `v6.3.12` in indicator and strategy headers/titles.
- **Tests:** added Phase-3 parity lock in `tests/test_score_engine_parity.py` (`test_phase3_regime_hysteresis_parity`).
- **Tests (behavioral):** added simulator snapshot coverage for Phase-3 hysteresis edge cases in `tests/test_functional_features.py` (`TestPhase3RegimeHysteresisBehavior`):
  - regime flapping damping via `regimeMinHoldBars`
  - VOL_SHOCK sticky release via `regimeShockReleaseDelta`

### Verification

- Full regression suite passes after integration: **384 passed**.

## [v6.3.11] - 2026-02-15

### Added

- **RFC v6.4 Phase-2 opt-in wiring (default-safe):** integrated the Phase-1 scaffold into active signal controls when explicitly enabled (`useRegimeClassifier2` + `regimeAutoPreset` + detected regime):
  - new effective tuning variables `cooldownBarsEff`, `chochMinProbEff`, `abstainOverrideConfEff`
  - regime-aware mapping for TREND/RANGE/CHOP/VOL_SHOCK under `regime2TuneOn`
  - trend core activation in signal layer via `trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)` and `trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)`
  - ChoCH gating updated to effective threshold (`chochMinProbEff`) in all relevant entry paths
  - abstain override uses effective threshold (`abstainOverrideConfEff`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.11` in indicator and strategy headers/titles.
- **Tests:**
  - added Phase-2 wiring parity coverage in `tests/test_score_engine_parity.py` (`test_phase2_optin_wiring_parity`)
  - aligned trend-regime presence checks to trend-core wiring in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy.py`

### Verification

- Full regression suite passes after integration: **378 passed**.

## [v6.3.10] - 2026-02-15

### Added

- **RFC v6.4 Phase-1 scaffold (default-off):** added non-invasive foundation in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Zero-Lag Trend Core inputs (`useZeroLagTrendCore`, `trendCoreMode`, `zlTrendLenFast/Slow`, `zlTrendAggressiveness`, `zlTrendNoiseGuard`)
  - Regime Classifier 2.0 inputs (`useRegimeClassifier2`, `regimeLookback`, `regimeAtrShockPct`, `regimeAdxTrendMin`, `regimeHurstRangeMax`, `regimeChopBandMax`, `regimeAutoPreset`)
  - debug visibility toggle `showPhase1Debug` with hidden Data Window plots
  - helper functions `f_zl_trend_core` and `f_hurst_proxy`
  - derived diagnostic state variables (`trendCoreFast/Slow`, `trendCoreDiffNorm`, `regime2State`, `regime2Name`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.10` in indicator and strategy headers/titles.
- **Tests:** expanded parity/functional coverage for Phase-1 scaffold invariants:
  - `tests/test_score_engine_parity.py`
  - `tests/test_functional_features.py`
  - `tests/pine_sim.py` (Phase-1 config surface)

### Verification

- Full regression suite passes after integration: **377 passed**.

## [v6.3.9] - 2026-02-15

### Added

- **Functional behavior test matrix (new):** added simulator-driven feature coverage in `tests/test_functional_features.py` for:
  - gate functionality (`reliabilityOk`, `evidenceOk`, `evalOk`, `decisionFinal`),
  - open-window + strict-mode behavior,
  - engine scenarios (Hybrid/Breakout/Trend+Pullback/Loose),
  - risk/exit behavior,
  - reversal logic,
  - feature-flag matrix,
  - randomized invariants,
  - golden-master snapshots.
- **Label/display regression suite (new):** added `tests/test_label_display_regression.py` to lock label payload/style/color contracts and event→label family mapping (BUY/REV-BUY/SHORT/REV-SHORT/EXIT/COVER).
- **Functional test documentation:** added `docs/FUNCTIONAL_TEST_MATRIX.md` and linked it from `README.md`.

### Changed

- **CI guard hardened:** `.github/workflows/ci.yml` now includes explicit read permissions, concurrency cancel-in-progress, manual dispatch (`workflow_dispatch`), timeout guard, and strict pytest execution (`-q --maxfail=1`).
- **Version sync:** updated script headers/titles and docs references to `v6.3.9` for consistency.

### Verification

- Full regression suite passes after integration: **375 passed**.

### Changed

- **Entry presets (new):** added score presets in indicator + strategy via:
  - `entryPreset = Manual | Intraday | Swing`
  - `presetAutoCooldown` (default `false`)
  Presets now drive effective score variables (`*_Eff`) for thresholds, weights, and score probability floors.
- **Optional preset-driven cooldown:** when `presetAutoCooldown = true` and preset is not `Manual`, cooldown uses effective preset values:
  - mode: `Bars`
  - triggers: `ExitsOnly`
  - minutes: `15` (Intraday) / `45` (Swing)
  With `presetAutoCooldown = false` (default), cooldown remains fully user-input controlled.
- **Score integration mode adjusted (Option C):** restored hybrid signal merge so score can inject entries again while still respecting engine logic context.
- **Score directional context gate (new, default ON):** added `scoreRequireDirectionalContext` so score injection requires directional context:
  - BUY score injection needs bullish context (`trendUp`/USI bull state),
  - SHORT score injection needs bearish context (`trendDn`/USI bear state).
- **Dynamic TP expansion:** outward-only TP mode is active by default (default ON) in indicator + strategy:
  - `useDynamicTpExpansion`
  - `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`
  - optional gates: `dynamicTpRequireTrend`, `dynamicTpRequireConf`, `dynamicTpMinConf`
  TP expands as unrealized $R$ grows and never tightens due to this module.
- **Dynamic SL profile (new, default ON):** added adaptive stop profiling in indicator + strategy:
  - optional early widening window (`dynamicSlWidenUntilR`, `dynamicSlMaxWidenATR`) to reduce noise stopouts,
  - progressive tightening phase (`dynamicSlTightenStartR`, `dynamicSlTightenATRPerR`, `dynamicSlMaxTightenATR`) as $R$ grows,
  - optional gates: `dynamicSlRequireTrend`, `dynamicSlRequireConf`, `dynamicSlMinConf`.
  Widening is disabled once BE was hit or trailing is active.
- **Score hard confidence gate (new):** added optional hard confidence floor for score entries in indicator + strategy:
  - `scoreUseConfGate`
  - `scoreMinConfLong`, `scoreMinConfShort`
  - integrated in final score entry decisions via effective vars (`*_Eff`) for preset parity.
  - **Current defaults:** `scoreUseConfGate = true`, `scoreMinConfLong = 0.50`, `scoreMinConfShort = 0.50`.

### Fixed

- **Chop penalty enforcement:** added explicit chop veto in final score merge path:
  - `chopVeto = isChop and (wChopPenalty < 0)`
  - final merge now blocks BUY/SHORT when chop veto is active.
- **Unified exit trigger (LONG + SHORT):** exit/cover now use one OR-union trigger in both scripts:
  - `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`
  - whichever condition fires first closes the position.
- **Cooldown semantics restored:** when `cooldownTriggers` is `ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events again (indicator + strategy parity).
- **Debug transparency:** score debug panel now prints chop veto status (`veto:0/1`) next to `chop` for faster root-cause diagnosis.
- **Debug blocker clarity:** score debug now shows explicit block reason (for example `BLOCK:IN_POSITION`) and prints last-signal age safely (`LS:...@n/a` instead of `NaN` when unavailable).
- **Debug context visibility:** score debug now prints directional context gate flags:
  - `ctxL:0/1` for long score-context pass/fail,
  - `ctxS:0/1` for short score-context pass/fail.
- **Token-budget hardening (Strategy):** reduced compile-token pressure by compacting debug payloads and removing Strategy table rendering (visual-only) while keeping signal/risk/entry-exit logic intact.
- **Parity:** same logic mirrored in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

## [v6.3.8] - 2026-02-15

### Changed

- **USI Exit/Flip Touch Logic (Tier A Red vs Blue):** refined cross detection to treat visual touch/near-touch transitions as valid flip events, improving practical EXIT timing when Red approaches Blue from above.
- **USI Red De-lag Option (Option 2):** added optional Red-line source de-lag controls:
  - `useUsiZeroLagRed`
  - `usiZlAggressiveness`
  This is applied pre-RSI on Line5 for earlier flips with controllable aggressiveness.

### Fixed

- **Contra-state entries blocked (hard rule):** BUY is now vetoed when USI is bearish, and SHORT is vetoed when USI is bullish (when USI is enabled).
- **Parity hardening:** synchronized logic in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`, including gate-timeframe (`f_usi_30m_calc_raw`) handling for the new Red-line de-lag path.

### Tests

- Extended parity checks in `tests/test_score_engine_parity.py` to verify:
  - presence of new USI Red de-lag inputs,
  - Red-line implementation parity,
  - hard USI state blocking in score decisions.

## [v6.3.7] - 2026-02-14

### Added

- **Exit control flexibility:** `useStrictEmaExit` added to allow relaxed trend exits (wait for full EMA trend flip when disabled), reducing deep-pullback shakeouts.

## [v6.3.4] - 2026-02-14

### Fixed

- **SkippALGO Strategy**: Synchronized fix for `plotchar()` scope (global scope with conditional logic) to resolve "Cannot use plotchar in local scope".
- **Maintenance**: Unified versioning across Indicator (v6.3.3 based) and Strategy.

## [v6.3.3] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Moved `plotchar()` debug calls from local scope (if-block) to global scope with conditional `debugUsiPulse and ...` logic to fix "Cannot use plotchar in local scope" errors.

## [v6.3.2] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Replaced `color.cyan` with `color.aqua` to resolve an undeclared identifier error (Pine v6 standard).

## [v6.3.1] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Removed duplicate/erroneous code block related to `qVerifyBuy` logic that caused a "Mismatched input bool" syntax error.
- **Maintenance**: Parity version bump for Strategy script (no functional changes in Strategy).

## [v6.3.0] - 2026-02-14

### Added (System Hardening)

- **Time-Based Cooldown**: `cooldownMode` input ("Bars" vs "Minutes") allows proper HTF trade management without multi-hour lockouts.
- **Explicit Triggers**: `cooldownTriggers` input ("ExitsOnly" vs "AllSignals") strictly defines what resets the timer. "ExitsOnly" (default) ensures fast add-on entries are possible.

### Changed (Optimization)

- **QuickALGO Logic**: Switched from restrictive "Hard-AND" momentum check to "Score+Verify" weighted approach.
- **QuickALGO MTF Fix**: Added `lookahead=barmerge.lookahead_off` to prevent repainting.
- **Cleanup**: Removed legacy "Deep Upgrade" branding from script headers.

## [2026-02-12]

### Added (Signals & Volatility)

- New input: `REV: Min dir prob` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed (Parity)

- Stabilized script titles to preserve TradingView input settings across updates:
  - `indicator("SkippALGO", ...)`
  - `strategy("SkippALGO Strategy", ...)`
- Consolidated runtime alert dispatch to one `alert()` call per bar per symbol, reducing watchlist alert-rate pressure and TradingView throttling risk.
- EXIT/COVER label text layout split into shorter multi-line rows for better chart readability.
- Open-window directional probability (`pU`/`pD`) bypass behavior applies during configured market-open windows as implemented in current logic.

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

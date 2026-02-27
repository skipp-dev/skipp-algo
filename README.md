# SkippALGO — Outlook + Forecast (Calibrated Probabilities)

Pine Script v6 · Non-repainting core logic · Intrabar alerts/labels (default)

SkippALGO combines a signal engine with a multi‑timeframe dashboard that clearly separates:

- **Outlook (State):** current regime/bias snapshot per timeframe (non‑predictive).
- **Forecast (Probability):** calibrated probability of a defined forward outcome, gated by sample sufficiency.

## What you get

- Multi‑timeframe **Outlook** with bias, score, and components (Trend/Momentum/Location).
- **Forecast** block with Pred(N)/Pred(1) plus calibrated $P(\mathrm{Up})$.
- Strict **non‑repainting** behavior (`lookahead_off`, `barstate.isconfirmed`).
- Intrabar-first alert/label UX by default:
  - `Alerts: bar close only = false` (default) sends preview alerts/labels before candle close,
  - switching it to `true` restores bar-close-only signaling.
- Confidence gating, macro + drawdown guards, and MTF confirmation.

## Quick start

1. Add `SkippALGO.pine` to your TradingView chart.
2. Start with default horizons (1m–1d) and **predBins=3**.
3. Let calibration warm up (watch sample sufficiency in Forecast rows).
4. Read **Outlook first**, then confirm with **Forecast** probabilities.

### Preset: Intrabar Labels (Repainting ON)

Use this preset if you explicitly want labels to print **before candle close** (realtime preview behavior).

- `Alerts: bar close only = false`
- `Show Long labels (BUY / EXIT) = true`
- `Show Short labels (SHORT / COVER) = true`
- `Show PRE labels (PRE-BUY / PRE-SHORT) = true`

Notes:

- This mode is intentionally **repainting/intrabar** and can differ from final close-confirmed outcomes.
- Preview labels are realtime-only; historical bars still reflect confirmed logic.

## Table guide (short)

- **Outlook (State):** descriptive snapshot at the last confirmed bar for each TF.
- **Forecast (Prob):** conditional probability for the defined target (default: next‑bar direction).
- `…` and `n0` indicate insufficient data; do not treat as a signal.
- Forecast rows include **nCur/Total** and a target footer describing active target definitions.

## Open-Prep: Pre-Open Briefing Contract

`open_prep` generates a reproducible pre-open briefing for a symbol universe:

- Quotes are enriched with gap metadata (mode + availability + evidence timestamps).
- Macro context and optional news catalyst scores are merged into candidate ranking.
- Top-N candidates are exported with structured trade cards and ATR-based stop/trail profiles.

This output is intentionally score-driven and setup-oriented (for example ORB / VWAP-hold patterns),
not hard-coded to a single directional narrative in documentation.

### Macro explainability and risk guardrails

- `macro_score_components[]` includes:
  - `canonical_event`, `consensus_value`, `consensus_field`, `surprise`, `weight`, `contribution`, `data_quality_flags`
  - optional `dedup` object when canonical duplicates were collapsed (`duplicates`, `chosen_event`, `policy`)
- `ranked_candidates[]` includes:
  - `allowed_setups`, `max_trades`, `data_sufficiency`, `no_trade_reason`, `score_breakdown`
- In `macro_risk_off_extreme`, long setups are degraded to `vwap_reclaim` with `max_trades=1`.
- If RVOL/liquidity is missing in that regime (`rel_volume <= 0`), candidate is fail-safe blocked via
  `no_trade_reason += ["missing_rvol"]`, `long_allowed=false`, and `data_sufficiency.low=true`.
- Headline PCE confirmation is controlled by explicit switch
  `include_headline_pce_confirm` (separate from `include_mid_if_no_high`).

### Monday gap semantics (explicit)

- `RTH_OPEN`: available only when an actual Monday RTH open exists;
  otherwise `gap_available=false` with reason metadata.
- `PREMARKET_INDICATIVE`: available only with timestamp-backed premarket/extended quote evidence;
  otherwise unavailable with explicit `gap_reason`.
- `OFF`: no active Monday gap computation (placeholder/fallback semantics only).

### Candidate data contract (operational fields)

Each candidate row carries gap evidence fields used by downstream exports and reviews:

- `gap_available`, `gap_reason`, `gap_price_source`, `gap_from_ts`, `gap_to_ts`

Run-level metadata includes reproducibility and run context fields:

- `run_datetime_utc`, `inputs_hash`, `gap_mode`

Scoring is a weighted blend of gap, volume/liquidity, macro context, and optional news inputs;
exact weights/clamps are defined in implementation and may evolve with controlled changes.

### Open-Prep Live Monitor (Streamlit)

Für einen laufenden Monitor mit automatischem Refresh alle 15 Sekunden:

- Start: `streamlit run open_prep/streamlit_monitor.py`
- Die App ruft bei jedem Refresh die Datenquellen neu über `generate_open_prep_result(...)` ab.
- Parameter (Symbole, Gap-Mode, ATR-Settings, Pre-Open-Filter) sind in der Sidebar einstellbar.
- v2 candidate view supports realtime-assisted surfacing:
  - symbols with active `A0`/`A1` signals that were only `below_top_n_cutoff` in pipeline scoring
    are auto-promoted into a dedicated **🔥 RT-PROMOTED** section.
  - this prevents high-momentum symbols from being hidden purely due to snapshot cutoff timing.

## Sideways/Chop semantics (quick)

- `sidewaysVisual`: visual consolidation state for dots/alerts (UX layer).
- `chopRisk`: score-layer chop risk used to shape/veto score injections.
- `usiTightSpread`: strict USI verify compression check (verification layer).

These names separate chart UX, score risk handling, and USI verification strictness.
For the full explanation, see `docs/TRADINGVIEW_STRATEGY_GUIDE.md` (section **L**).

Global score floor note:

- `Enforce score min pU/pD on all entries` does **not** block `REV-BUY`.
- `REV-BUY` uses its own reversal probability gates (`revMinProb` + reversal/open-window path).

## Cooldown same-bar toggles (indicator)

In `SkippALGO.pine` (indicator), cooldown behavior now has symmetric same-bar re-entry controls:

- `Allow same-bar BUY after COVER`
- `Allow same-bar SHORT after EXIT`

Default behavior remains conservative (`false`): re-entry waits until the next bar.

Cooldown trigger modes now support:

- `ExitsOnly` (default): cooldown timer updates on `EXIT`/`COVER`
- `AllSignals`: timer updates on every signal (`BUY`/`SHORT`/`EXIT`/`COVER`)
- `EntriesOnly`: timer updates only on entries (`BUY`/`SHORT`)

Timing note:

- State machine order is exits first, then entries per confirmed bar. A newly opened `BUY`/`SHORT` on bar $N$ cannot be exited on bar $N$; earliest `EXIT`/`COVER` is bar $N+1$.
- With `cooldownBars = 1`, entry cooldown check uses `bar_index - lastSignalBar > cooldownBars`, so new entries are blocked on $N+1$ and allowed again from $N+2$.
- Strategy/Indicator note: with `cooldownTriggers = EntriesOnly` and `cooldownBars >= 1`, exits are hold-gated by entry bar index; for `cooldownBars = 1`, generic exits are earliest on bar $N+2$.
- Exceptions in `EntriesOnly` mode: only protective `SL`/`TP` and directional engulfing exits can bypass the hold gate immediately after entry.
- `USI-FLIP` does **not** bypass `EntriesOnly` hold; it remains blocked until the hold window is over.

## Documentation

- **Bloomberg Terminal — Architecture & Plan:** `docs/BLOOMBERG_TERMINAL_PLAN.md`
- **Open Prep Suite — technische Vollreferenz:** `docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md`
- **Open Prep Suite — Ops Quick Reference (24/7):** `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`
- **Open Prep Suite — Incident Runbook Matrix:** `docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md`
- **Open Prep Suite — Incident One-Page (Markdown):** `docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md`
- **Open Prep Suite — Incident One-Page (Print HTML):** `docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE_PRINT.html`
- **Open Prep Suite — Code Reviews:** `docs/REVIEW_open_prep_suite.md`, `docs/REVIEW_open_prep_v2_post_fixes.md`
- **Deep technical documentation:** `docs/SkippALGO_Deep_Technical_Documentation.md`
- **Deep technical documentation (current):** `docs/SkippALGO_Deep_Technical_Documentation_v6.2.22.md`
- **Kurzfassung für neue Nutzer:** `docs/SkippALGO_Kurzfassung_Fuer_Nutzer.md`
- **Roadmap enhancements:** `docs/SkippALGO_Roadmap_Enhancements.md`
- **Functional test matrix (behavior-driven):** `docs/FUNCTIONAL_TEST_MATRIX.md`
- **RFC v6.4 (Adaptive Zero-Lag + Regime Classifier):** `docs/RFC_v6.4_AdaptiveZeroLag_RegimeClassifier.md`
- **Wiki (local mirror):** `docs/wiki/Home.md`
- **Changelog:** `CHANGELOG.md`

## Developer quality checks (Python workspace)

For the Python modules (`newsstack_fmp`, `open_prep`, `terminal_*`, `streamlit_terminal`), the repository uses a documented quality gate with `pytest`, `ruff`, `mypy`, and Pylance/Pyright.

- Test suite (1599 tests): `python -m pytest tests/ -q`
- Linting: `ruff check newsstack_fmp/ open_prep/ terminal_poller.py terminal_export.py terminal_spike_scanner.py terminal_background_poller.py`
- Type-checking: `mypy newsstack_fmp/ terminal_poller.py terminal_export.py`
- Coverage (core modules):
  - `python -m pytest tests/ -q --cov=newsstack_fmp --cov=terminal_poller --cov=terminal_export --cov-report=term-missing`

Configuration is centralized in `pyproject.toml`.
Pylance/Pyright: 0 workspace errors (verified 27 Feb 2026).

## Recent changes (Feb 2026)

- **Latest (27 Feb 2026) — Benzinga full API coverage + Intelligence dashboards:**
  - **Full Benzinga API coverage:** 3 news endpoints (top news, channels, quantified), 5 calendar endpoints (dividends, splits, IPOs, guidance, retail), 20+ financial data methods (fundamentals, ratios, profiles, price history, options activity, charts) via new `BenzingaFinancialAdapter`.
  - **Benzinga Intelligence — Terminal:** Expanded from 3 to 11 sub-tabs (added Dividends, Splits, IPOs, Guidance, Retail, Top News, Quantified, Options Flow).
  - **Benzinga Intelligence — Open Prep:** New 8-tab Benzinga Intelligence section in `open_prep/streamlit_monitor.py` (Dividends, Splits, IPOs, Guidance, Retail, Top News, Quantified, Options).
  - **VisiData enrichment:** Per-ticker enrichment columns (`div_exdate`, `div_yield`, `guid_eps`, `options_flow`) + standalone Benzinga Calendar JSONL export.
  - **Channels & topics filtering:** `channels` and `topics` params wired into REST/WS adapters, Config, terminal_poller.
  - 103 new tests across 4 files. Verification: **1599 passed**, 0 lint errors.

- **Previous (27 Feb 2026) — Benzinga delayed-quote overlay + production hardening:**
  - Benzinga delayed quotes overlaid on stale FMP data during pre-market/after-hours across terminal spike scanner, VisiData, Rankings tab, and open_prep Streamlit monitor.
  - Market-session detection (`market_session()`) with canonical `SESSION_ICONS` in `terminal_spike_scanner.py`.
  - Benzinga calendar, movers, and quotes adapters with 79 tests.
  - 3 production readiness review cycles: 12 bugs fixed (cache key thrashing, falsy `or` patterns, unconditional API calls, BZ column ordering, etc.).
  - Full Pylance/Pyright lint cleanup: 0 workspace errors.
  - Terminal UI: clickable headline links, ring-buffer eviction, optional imports for Streamlit Cloud.

- **Previous (26 Feb 2026) — Python docs + quality hardening update:**
  - Added `pyproject.toml` as the central configuration for:
    - `pytest` discovery/options,
    - `ruff` lint rules,
    - `mypy` type-checking profile,
    - coverage thresholds/reporting.
  - Added focused Python coverage expansion in `tests/test_coverage_gaps.py`.
  - Updated terminal/newsstack test expectations for current runtime contracts (for example `cluster_hash` signature and VisiData snapshot columns).
  - Verification:
    - full suite green (**1116 passed, 34 subtests passed**),
    - lint clean (**ruff: all checks passed**),
    - type-check clean (**mypy: no issues found**),
    - core Python coverage improved to **83%**.

- **Latest (25 Feb 2026) — Open-Prep Streamlit v2 realtime auto-promotion:**
  - Added auto-promotion of realtime `A0`/`A1` symbols from `below_top_n_cutoff` into displayed v2 candidates.
  - Added dedicated **🔥 RT-PROMOTED** section in the monitor.
  - Cross-reference “missing from v2” now excludes already-promoted symbols (shows only hard-filtered / not-in-universe cases).
  - Added focused regression coverage in `tests/test_rt_promotion.py`.
  - Verification: full test suite green (**985 passed, 34 subtests passed**).

- **Latest (v6.3.13b — 16 Feb 2026) — Alert Surface + Consolidation UX:**
  - Added dedicated alert conditions in **indicator + strategy**:
    - `REV-BUY`
    - `REV-SHORT`
    - `CONSOLIDATION` (fires on consolidation phase entry: `trendSide and not trendSide[1]`)
  - Consolidated runtime alert labeling now prioritizes reversal labels (`REV-BUY`/`REV-SHORT`) over generic `BUY`/`SHORT` when applicable.
  - Consolidation dot coloring in indicator refined:
    - USI short state (`usiStackDir == -1`) → reddish dot,
    - otherwise → orange dot.

- **Latest (v6.3.13a — 16 Feb 2026) — Intrabar Default for Alerts/Labels:**
  - `Alerts: bar close only` now defaults to `false` in both indicator and strategy.
  - BUY/SHORT/EXIT/COVER and PRE-BUY/PRE-SHORT alerts + labels are intrabar-first by default (realtime preview pulses).
  - Users can still force close-confirmed behavior by setting `Alerts: bar close only = true`.

- **Latest (v6.3.13 — 16 Feb 2026) — Parity Hardening + Wiring Completion:**
  - Restored strict Strategy entry-gate parity with Indicator (`reliability/evidence/eval/decision`).
  - Added missing Strategy runtime modules for dynamic risk adaptation:
    - Dynamic TP expansion (preset-aware effective mapping + trend/conf gates),
    - Dynamic SL profile (widen/tighten phases + trend/conf gates).
  - Wired previously dormant ChoCH volume requirement (`chochReqVol`) in both scripts.
  - Completed structure tag wiring:
    - Strategy now plots BOS/ChoCH tags,
    - Indicator now plots BOS tags in addition to ChoCH.
  - Verification: full suite green (**386 passed**).

- **Latest (v6.3.12 — 15 Feb 2026) — Phase-3 Quality Tuning (Regime Hysteresis):**
  - Added regime transition stability controls (both scripts):
    - `regimeMinHoldBars`
    - `regimeShockReleaseDelta`
  - Implemented latched regime state flow:
    - `rawRegime2State` (instant classifier output)
    - `regime2State` + `regime2HoldBars` (hysteresis-governed effective state)
  - VOL_SHOCK now persists until ATR percentile cools below the configured release threshold (reduces flapping around shock boundary).
  - Added parity regression lock:
    - `tests/test_score_engine_parity.py::test_phase3_regime_hysteresis_parity`
  - Added behavioral snapshot coverage for hysteresis edge cases:
    - `tests/test_functional_features.py::TestPhase3RegimeHysteresisBehavior`
    - includes flapping damping and VOL_SHOCK sticky-release scenarios.
  - Verification: full test suite green (**384 passed**).

- **Latest (v6.3.11 — 15 Feb 2026) — Phase-2 Opt-In Wiring (Adaptive Zero-Lag + Regime Classifier):**
  - Wired trend-core output directly into trend regime/strength decisions:
    - `trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)`
    - `trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)`
  - Added regime-driven effective mappings under safe opt-in gate (`useRegimeClassifier2` + `regimeAutoPreset`):
    - `cooldownBarsEff`
    - `chochMinProbEff`
    - `abstainOverrideConfEff`
  - Switched ChoCH filters and abstain override to their effective thresholds for regime-aware behavior.
  - Preserved safe defaults: behavior is unchanged unless the new regime classifier path is explicitly enabled.
  - Added/updated parity regression checks:
    - `tests/test_score_engine_parity.py` (`test_phase2_optin_wiring_parity`)
    - trend-regime expectation updates in indicator/strategy test suites.
  - Verification: full test suite green (**378 passed**).

- **Latest (v6.3.10 — 15 Feb 2026) — Phase-1 Scaffold (Adaptive Zero-Lag + Regime Classifier):**
  - Added default-off Phase-1 scaffold inputs in both scripts:
    - `useZeroLagTrendCore`, `trendCoreMode`, `zlTrendLenFast/Slow`, `zlTrendAggressiveness`, `zlTrendNoiseGuard`
    - `useRegimeClassifier2`, `regimeLookback`, `regimeAtrShockPct`, `regimeAdxTrendMin`, `regimeHurstRangeMax`, `regimeChopBandMax`, `regimeAutoPreset`
  - Added derived internal helper logic (`f_zl_trend_core`, `f_hurst_proxy`) and non-invasive runtime diagnostics (`regime2State`, `regime2Name`).
  - Added hidden Data Window debug plots under `showPhase1Debug` for trend-core/regime observability.
  - Added parity + functional tests for the Phase-1 scaffold and invariance behavior.

- **Latest (v6.3.9 — 15 Feb 2026) — CI + Test Coverage Hardening:**
  - Added behavior-driven functional coverage in `tests/test_functional_features.py` (gates, open-window/strict, engines, risk-exit, reversals, flag matrix, invariants, golden snapshots).
  - Added label/display regression coverage in `tests/test_label_display_regression.py` (payload/style/color contracts and event→label family mapping).
  - Added functional test documentation in `docs/FUNCTIONAL_TEST_MATRIX.md`.
  - Hardened CI workflow (`.github/workflows/ci.yml`) with explicit permissions, concurrency cancel-in-progress, workflow dispatch, timeout, and strict pytest guard.
  - Synced script headers/titles and docs references to `v6.3.9`.

- **Latest (15 Feb 2026) — USI behavior + safety hardening:**
  - Added **Entry Presets** for Score Engine tuning:
    - `entryPreset = Manual | Intraday | Swing`
    - Presets drive effective score thresholds/weights/probability floors (`*_Eff`) without changing your manual inputs.
  - Added optional **Preset-controlled Cooldown**:
    - `presetAutoCooldown` (default `false`)
    - when enabled with Intraday/Swing, cooldown uses effective preset profile (Bars + ExitsOnly, with profile minutes).
  - Added optional **hard confidence gate** for score entries:
    - `scoreUseConfGate`
    - `scoreMinConfLong`, `scoreMinConfShort`
    - **Default now enabled** with balanced floors:
      - `scoreUseConfGate = true`
      - `scoreMinConfLong = 0.50`
      - `scoreMinConfShort = 0.50`
  - Added optional **USI Red de-lag path (Option 2)** with:
    - `useUsiZeroLagRed`
    - `usiZlAggressiveness`
  - Added **hard USI state veto** for score-based entries:
    - no BUY while USI is bearish,
    - no SHORT while USI is bullish.
  - Refined **USI touch/cross handling** for practical flip timing (Red vs Blue/Envelope touch transitions are now recognized more reliably).
  - Extended parity regression checks in `tests/test_score_engine_parity.py` for the new USI controls and blocking logic.
  - Refined Score Engine merge behavior:
    - score path can inject entries again (`engine OR score`),
    - but active chop now hard-vetoes entries via `chopVeto`.
  - Added score injection directional-context gate (`scoreRequireDirectionalContext`, default ON):
    - score BUY injection requires bullish context,
    - score SHORT injection requires bearish context.
  - Added debug visibility for chop blocking with `veto:0/1` in score debug labels.
  - Added debug visibility for score context and blockers:
    - `ctxL:0/1`, `ctxS:0/1` (directional context pass/fail),
    - explicit blocker line (for example `BLOCK:IN_POSITION`),
    - safe last-signal age formatting (`LS:...@n/a` when unavailable).
  - Unified exit trigger behavior is now explicit and parity-locked for both LONG and SHORT:
    - `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`.
    - First trigger wins and closes the active position.
  - Restored cooldown semantics on exits/covers:
    - with `cooldownTriggers = ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events.
  - Dynamic risk profile defaults:
    - `Dynamic TP Expansion` is ON by default,
    - `Dynamic SL Profile` is ON by default.
  - Strategy compile-budget hardening:
    - score debug payload was compacted,
    - strategy table rendering was removed (visual-only) to reduce Pine token load,
    - trading logic and Indicator/Strategy parity remain intact.

- **Latest (v6.3.5 — 14 Feb 2026) — Score Engine (Option C):**
  - **New Entry Path**: "Score Engine" (Option C) allows high-quality setups (USI Cross, Liquidity Sweeps) to trigger entries independent of the rigid Engine logic.
  - **Fail-Open Design**: Missing feature data (e.g., waiting for USI calculation) contributes 0 points rather than blocking the trade.
  - **Risk Safety**: Score entries strictly respect the global **Drawdown Hard Gate (`ddOk`)** to prevent trading during portfolio risk events.
  - **Parity**: Fully synchronized between Strategy and Indicator.

- **Previous (v6.3.4 — 14 Feb 2026) — Final Parity Release:**
  - **Strategy Fix (v6.3.4)**: Applied `plotchar` scope fix to Strategy script (parity with Indicator).
  - **Syntax Fix (v6.3.3)**: Moved `plotchar()` from local scope to global scope (Pine Script requirement).
  - **Syntax Fix (v6.3.2)**: Replaced `color.cyan` with `color.aqua`.
  - **Syntax Fix (v6.3.1)**: Removed erratic duplicate code block.
  - **Cooldown Fix (v6.3.0)**: `cooldownMode` "Minutes" support.
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
  - Near market open (±window), directional probability bypass (`pU`/`pD`) can be configured by side, mode, and engine scope for standard and reversal entries.
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

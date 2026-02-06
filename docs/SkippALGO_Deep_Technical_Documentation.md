# SkippALGO — Deep Upgrade v6.1 Technical Documentation

## Pine Script v6 | Non-repainting | Online Learning (SGD) | Ensemble Architecture

## 1) Purpose and Evolution

**Version 6.1 (Deep Upgrade)** represents a fundamental architectural shift from simple "Bin Counting" to a sophisticated **Online Learning System**.

### Feb 02, 2026 Additions (Stability + Decision Quality)

* **Quantile binning** for the score dimension (adaptive density) with fixed‑bin fallback.
* **Chop‑aware regime dimension** for 2D bins and forecast display (distinct flat marker).
* **Decision‑quality abstain gate** with UI feedback (edge + bin samples + optional total evidence).
* **3‑way calibrator safety fallback**: temperature/vector scaling only applies/updates when sample thresholds are met.
* **Display‑time calibration**: 3‑way probabilities reflect temp/vector scaling when eligible.
* **Outlook table refactor**: fixed 10‑column layout with Dir + Up/Flat/Down + nCur and no forecast/eval blocks in the main table.
* **UI Reliability**: Table visibility logic updated to `barstate.islast` to ensure persistent display on high timeframes.
* **Symmetric Targeting**: Mid/Slow profiles updated to symmetric TP/SL (Mid: 0.65/0.65, Slow: 1.0/1.0) to eliminate bearish bias in probabilities.
* **Calibration Tuning**: "Vector" scaling is now the default mode; forecast display threshold lowered to 0.34.

While retaining the core philosophy of "State" vs "Forecast", the engine now employs:

1. **Adaptive Targeting**: Different timeframes have different physics (Noise vs Trend).
2. **Multidimensional Context**: Predictions condition on both *Algorithm Score* and *Volatility Regime*.
3. **Ensemble Scoring**: State is no longer a single number, but a weighted blend of multiple expert signals.
4. **Continuous Calibration**: Using Stochastic Gradient Descent (SGD) to fit Platt Scaling parameters in real-time.

---

## 2) The Four Phases of Upgrade

### Phase 1: Adaptive Target Profiles

Historical static targets (e.g., "Next Bar Close") failed to capture the nuance of different time horizons.

* **Fast TFs (1m, 5m)**: Noise dominance. Target: **K-Bar ATR** (Relative volatility expansion).
* **Mid TFs (15m - 1h)**: Swing structure. Target: **Path Dependent** (Symmetric 0.65 ATR TP/SL).
* **Slow TFs (4h, 1D)**: Trend persistence. Target: **Path Dependent** (Symmetric 1.0 ATR TP/SL).
* **Implementation**: `f_get_params(tf)` dynamically switches target logic based on the seconds-in-timeframe.

### Phase 2: 2D Calibration (Score x Volatility)

Previous versions binned only on `AlgoScore`. This missed a critical factor: A "Bullish Trend" signal behaves differently in Low Volatility (Grind up) vs High Volatility (Blow-off top).

* **Dimensions**:
    1. **Ensemble Score** (Quantized into N bins)
    2. **Volatility Rank** (Low / Mid / High)
* **Storage**: Flattens 2D space into 1D arrays: `Index = BinScore * 3 + BinVol`.
* **Benefit**: Signals are now context-aware. A "strong buy" in extreme volatility might now correctly predict a reversal (mean reversion) rather than continuation.

### Phase 3: Ensemble Signal Generation

The "Outlook Score" is now a composite `sEns` derived from three experts:

1. **Expert A (Trend/State)**: The classic Trend/Momentum/Location logic.
2. **Expert B (Pullback)**: Measures distance from EMAs. Incentivizes entries *between* Fast and Slow EMAs (Sweet spot) vs extended or broken structures.
3. **Expert C (Regime)**: Bias injection based on Volatility.
    * *High Vol (>66%)*: Short Bias / Mean Reversion.
    * *Low Vol (<33%)*: Long Bias / Trend Following.

* **Formula**: `Score = wA*A + wB*B + wC*C`

### Phase 4: Online Calibration (Platt Scaling)

Counting wins/losses in bins provides a "Raw Probability" (`pRaw`). However, this is often "rough" and slow to adapt.

* **Platt Scaling**: We model the true probability as `P(y=1|x) = Sigmoid(a * Logit(pRaw) + b)`.
* **Online Learning**:
  * Whenever a forecast resolves, we calculate the error between the *predicted probability* and the *actual outcome* (0 or 1).
  * **SGD (Stochastic Gradient Descent)** updates the parameters `a` (slope/confidence) and `b` (bias) instantly.
  * **LogLoss Tracking**: The system tracks the Logarithmic Loss to measure the "surprise" of the model, optimizing for true probabilistic confidence rather than just directional accuracy.

### Why the Forecast Calibration Exists (and how it helps)

Raw bin counts can be biased by small samples, regime shifts, and non‑stationary market behavior. The calibration pipeline is designed to make **probabilities trustworthy**, not merely frequentist counts.

**Expected benefits:**

* **Better decision gating:** Entry filters like *Min dir prob* and *Min edge* rely on calibrated probabilities; uncalibrated values would misfire.
* **Regime‑aware adaptation:** 2D bins (score × regime) and optional bull/bear separation let probabilities adapt to market context instead of averaging across incompatible regimes.
* **Graceful warm‑up:** Prior blending prevents false certainty while samples are sparse.
* **Online correction:** Temperature/Vector scaling and Platt scaling continuously correct over‑ or under‑confidence as new data arrives.

---

### 2.1) Forecast Performance Metrics — Interpretation & Thresholds

The script tracks several **proper scoring and calibration metrics** so you can objectively judge whether the probabilities are reliable enough to use.

### Brier Score (3‑way)

**Definition:** mean squared error of probabilistic forecasts, averaged across classes (Up/Flat/Down).

* **Excellent**: `BRIER_EXCELLENT = 0.18`
* **Good**: `BRIER_GOOD = 0.22`
* **Baseline / Random**: `BRIER_BASELINE = 0.25` (roughly no predictive skill)
* **Poor**: `BRIER_POOR = 0.30`

Interpretation: lower is better. Values below ~0.22 suggest meaningful forecasting skill; ~0.25 is effectively random for 3‑class probabilities.

### LogLoss (3‑way)

**Definition:** $-\log(p_{true})$ for the realized class.

Interpretation: lower is better, and it heavily penalizes confident wrong forecasts. A random 3‑class model has baseline logloss $-\log(1/3) \approx 1.099$.

### ECE (Expected Calibration Error)

Tracks absolute calibration error between predicted probabilities and realized frequencies across rolling buckets.

* **Well‑calibrated**: `ECE_GOOD = 0.05`
* **Fair / acceptable**: `ECE_FAIR = 0.10`

Interpretation: values above 0.10 indicate probabilities are materially mis‑calibrated (either too confident or too timid).

### Reliability via 95% CI Half‑Width

Uses a Wilson‑style CI half‑width to label reliability per bin:

* **Strong**: `HW_STRONG = 0.05`
* **OK**: `HW_OK = 0.10`
* **Weak**: above 0.10 or insufficient samples

Interpretation: smaller half‑width means tighter statistical certainty on that probability estimate.

### Platt Parameter Bounds (convergence diagnostics)

These are not performance metrics but stability indicators for the Platt Scaling calibrator:

* **Converged**: $a \in [0.7, 1.5]$, $|b| < 0.5$ — modest corrections; raw probabilities were already reasonable.
* **Unstable**: $a \notin [0.3, 3.0]$ — the calibrator is overcorrecting, indicating either too few samples or a fundamentally misspecified model.

Monitoring these bounds serves as an early warning system for model instability. Automated alerts when parameters drift outside the converged range are recommended (see section 2.2 below).

### Practical metric interpretation (decision rules)

The metrics work together as a diagnostic dashboard:

* **Brier < 0.22 + ECE < 0.05** — the forecast model has genuine skill and is well‑calibrated; trust the entry gates.
* **Brier < 0.22 but ECE > 0.10** — the model has skill but probabilities are systematically off; the calibrators haven't converged yet (need more samples).
* **Brier > 0.25** — no forecasting skill; the probability‑based entry gate is adding noise, not signal.

---

### 2.2) Design Considerations & Operational Guidance

This section captures review feedback and forward‑looking recommendations for maintaining and extending the calibration system.

#### Calibration latency vs. adaptiveness

Phase 4 (online post‑hoc calibration) is critical for adapting to new data but may introduce latency in response to sudden market shifts. The learning rates (`lrCal`, `lrPlatt`) control the speed/stability trade‑off:

* **Faster LR** → quicker adaptation to regime changes, but noisier parameters.
* **Slower LR** → more stable estimates, but slower to react after structural breaks.

Operators should choose learning rates that match their trading horizon. Intraday scalpers may prefer slightly higher LR; swing traders benefit from the defaults.

#### Metric monitoring cadence

* **Brier Score**: review per‑horizon grades regularly (e.g., weekly or after significant volatility events). Persistent Grade C or worse on a horizon suggests the target definition or bin structure needs revisiting.
* **LogLoss**: monitor alongside Brier to detect *overconfident* predictions that Brier alone may mask. A rising LogLoss with stable Brier is a red flag for tail‑risk mispricings.
* **ECE**: check after every calibration reset or major market regime change. Sustained ECE > 0.10 means the calibrators need more samples or the bin count should be reduced.
* **CI Half‑Width**: when a bin's reliability label reads "weak," the system should either abstain from trading on that signal or reduce position size. The existing `requireRelOk` input gate provides this.

#### Platt parameter stability alerts

When Platt parameters drift outside the converged range ($a \notin [0.7, 1.5]$ or $|b| > 0.5$), consider:

1. Logging a warning in the evaluation table (already displayed as color‑coded Platt diagnostics).
2. Temporarily falling back to raw bin probabilities until parameters re‑stabilize.
3. Triggering a per‑horizon calibration reset if instability persists for an extended period.

#### Model update and recalibration schedule

Markets are non‑stationary. Recommended practices:

* **Continuous online learning** (current default): SGD updates on every resolved forecast — no manual retraining needed.
* **Periodic review**: inspect Brier/ECE grades monthly or after major macro events (rate decisions, earnings seasons, volatility spikes).
* **Reset triggers**: reset calibration when switching asset class, after prolonged exchange outages, or when >50% of horizons show Grade D Brier for 5+ consecutive sessions.
* **Count decay** (`countDecay`): the existing exponential decay mechanism (default 0.9995) gradually down‑weights stale observations, providing implicit "forgetting" without explicit resets.

#### Backtesting vs. forward testing

The Strategy file (`SkippALGO_Strategy.pine`) provides backtesting capability, but backtests are inherently optimistic due to:

* No slippage modeling (Pine `strategy()` supports basic slippage but not order‑book simulation).
* No market‑impact costs on larger position sizes.
* Survivorship bias in the symbol universe.

**Recommendation**: after backtesting, run the indicator in paper‑trading mode on live data for at least 2–4 weeks per asset class before committing capital. Compare live Brier/ECE metrics against backtest values to detect overfitting.

#### Risk management beyond ATR

The script uses ATR‑based stops, take‑profits, and trailing stops. Additional risk factors to consider in production:

* **Correlation risk**: multiple instruments may trigger simultaneously during market stress, amplifying portfolio exposure.
* **Slippage**: fast markets (news events, opens) can cause fills significantly worse than the theoretical stop price.
* **Market impact**: for illiquid instruments, the bid‑ask spread and order‑book depth can erode edge.
* **Session boundaries**: the existing RTH close filter (`useRthCloseFilter`) helps, but overnight gap risk on non‑24h instruments remains.

These factors are outside the scope of Pine Script but should be addressed at the portfolio/execution layer.

#### Scalability and computational limits

Pine Script imposes execution‑time and memory limits. As complexity grows:

* Seven horizons × multiple `request.security()` calls per horizon is already near the practical ceiling.
* Adding more ensemble factors, bins, or calibration dimensions will hit TradingView's execution limits.
* If running across many instruments, consider off‑chart computation (e.g., exporting signals via webhooks to an external system that handles portfolio‑level logic).

#### User interface and operational dashboard

The on‑chart table serves as the primary dashboard. For enhanced operational use:

* The evaluation section (Brier / ECE / Platt diagnostics) provides at‑a‑glance model health.
* Reliability labels ("strong" / "ok" / "weak") and sample counts (`nCur/Total`) give immediate data‑sufficiency feedback.
* Alert conditions (`alertcondition`) can push signals to external systems for automated or semi‑automated workflows.
* For users managing multiple instruments, an external aggregation dashboard (consuming webhook alerts) would provide portfolio‑level oversight.

#### Continuous improvement

The calibration framework is designed for extensibility. Areas for future enhancement:

* **Alternative targets**: path‑dependent targets beyond TP vs SL (e.g., time‑weighted returns, max adverse excursion).
* **Additional ensemble factors**: order‑flow proxies, inter‑market correlations, or sentiment data (when available via Pine).
* **Adaptive bin counts**: automatically adjusting `predBinsN` based on available sample depth.
* **Cross‑asset transfer learning**: using calibration from correlated instruments to warm‑start a new symbol's bins.

### 2.3) Signal Engines

The `engine` input selects one of four signal-generation modes. Each mode requires a different combination of filters before a buy or short signal fires:

| Engine | Long trigger | Filters required |
| -------- | ------------- | ----------------- |
| **Hybrid** (default) | EMA touch + (EMA cross-up OR bullish reversal) | Volume, SET, pullback, forecast gate, enhancements |
| **Breakout** | Swing-high breakout | Volume, trend direction, forecast gate, enhancements |
| **Trend+Pullback** | Trend flip or EMA reclaim | Forecast gate, enhancements |
| **Loose** | Close crosses above fast EMA | Cooldown gate only |

* **Hybrid** is the most selective — it requires price to touch the fast EMA *and* either cross above it or print a bullish reversal pattern, while also passing volume, SET confirmation, pullback depth, forecast probability, and all enhancement filters (ADX, ROC, volume-ensemble, pre-momentum, EMA-acceleration, VWAP).
* **Breakout** fires on swing-high/low breaks and requires trend alignment plus volume and forecast gates.
* **Trend+Pullback** fires on EMA crossover or reclaim events and requires fewer filters (no explicit volume or SET gate).
* **Loose** is the most permissive — it fires whenever price closes above (or below) the fast EMA and the cooldown gate allows it. No volume, SET, pullback, forecast, or enhancement filters are applied. It is useful for testing or high-frequency scanning but is prone to false signals in choppy markets.

Short signals mirror the long logic with bearish equivalents. If both a buy and short signal fire on the same bar, both are suppressed to avoid ambiguity.

### 2.4) Configuration Presets

The `config` input selects a named preset that controls a **confidence multiplier** applied to the trust/confidence score. The confidence score gates whether signals are actionable — it must exceed the `minTrust` threshold for a signal to fire.

| Config | Multiplier | Effect |
| -------- | ----------- | -------- |
| **Standard** | 1.00 | Baseline confidence — no scaling |
| **Pro** | 1.05 | +5% boost — slightly more aggressive |
| **V2 Essential** | 0.95 | −5% — most conservative, fewer signals pass `minTrust` |
| **V2 Proficient** | 1.00 | Same as Standard (neutral) |
| **V2 Alpha** | 1.10 | +10% boost — most aggressive, more signals qualify |

The confidence value is computed as:

$$\text{confidence} = \text{clamp}_{[0,1]}\bigl(\text{trustRaw} \times \text{confMultiplier} \times (1 - \text{ddPenalty}) \times \text{crsiFactor}\bigr)$$

where `trustRaw` aggregates directional alignment, guardrail count, ATR rank, data quality, macro score, and momentum state.

**Choosing a preset:**

* Use **V2 Essential** for conservative setups or unfamiliar instruments — fewer but higher-conviction signals.
* Use **Standard** or **V2 Proficient** as neutral defaults.
* Use **Pro** or **V2 Alpha** when data quality is high and the calibration metrics (Brier, ECE) confirm the model is well-calibrated.

---

## 3) Technical Implementation Details

### TfState UDT Architecture (v6.1+)

Both the indicator and strategy now use a **User-Defined Type (UDT)** pattern to manage per-timeframe state, replacing ~100+ individual global arrays with 7 TfState objects.

```pine
type TfState
    // Calibration counts
    int[]   cntN        // N-bin counts (predBinsN × dim2Bins)
    int[]   upN         // N-bin wins
    int[]   cnt1        // 1-bin counts (predBins1 × dim2Bins)
    int[]   up1         // 1-bin wins
    
    // Queues for pending forecasts
    int[]   qBinN, qBin1
    float[] qEntry, qAtr, qMaxH, qMinL
    int[]   qAge
    float[] qProbN, qProb1, qLogitN, qLogit1, qPredN, qPred1
    
    // Online calibration stats
    float[] brierStatsN, brierStats1, llStatsN, llStats1
    float[] plattN, platt1  // Platt scaling [a, b]
    
    // Evaluation buffers (Brier, LogLoss, ECE)
    float[] evBrierN, evSumBrierN, evLogN, evSumLogN, ...
    int[]   evCalCntN, evCalCnt1  // ECE bucket counts
```

**Benefits:**

* **Code reduction**: ~450 lines removed from strategy
* **Maintainability**: Single `TfState st` parameter vs 40+ arrays
* **Consistency**: Indicator and strategy share identical patterns
* **Type safety**: UDT provides clear field documentation

**Key Functions:**

* `f_init_tf_state(nBinsN, nBins1, dim2, evBuckets)` — Initialize TfState with properly sized arrays
* `f_reset_tf(TfState st)` — Clear all calibration and queue arrays
* `f_process_tf(..., TfState st, ...)` — Process calibration for one horizon
* `f_eval_on_resolve(TfState st, pN, p1, isUp)` — Update evaluation metrics

### Data Flow

1. **Signal Generation**: On new bar → `f_ensemble` → `sEns`.
2. **Binning**: `f_bin2D(sEns, volRank)` → `BinID`.
3. **Prediction**:
    * Lookup `pRaw` from `st.cntN/st.upN`.
    * Apply `f_platt_prob(pRaw, a, b)` → **Displayed Probability**.
4. **Storage**: Push `BinID`, `EntryPrice`, `Logit(pRaw)` to `st.qXxx` queues.
5. **Resolution (Next Bars)**:
    * Check if Target Profile conditions met (TP/SL/Time).
    * If resolved:
        * Update `st.cntN/st.upN` (Bin counters).
        * Perform SGD step on `st.plattN[a,b]`.
        * Call `f_eval_on_resolve(st, ...)` for metrics.

---

## 4) Legacy Documentation (v6.0)

Below follows the original architecture, which remains relevant for the non-predictive modules.

### 1) Purpose and design goals

...

### A) **Outlook (State)**

A **non-predictive** multi-timeframe dashboard that describes the *current regime/bias* for each requested timeframe (1m/5m/15m/30m/1h/4h/1d by default). It answers:

> “Given the last confirmed bar on that timeframe, what does the market look like right now?”

This is **not** forecasting.

### B) **Forecast (Probabilities)**

A **calibrated**, evidence-driven probability estimate of a specific forward outcome. It answers:

> “Historically, when the state looked like this, how often did the next bar close up?”

This is forecasting, but it’s **narrowly defined**: next-bar direction on each timeframe (unless you later redefine the target).

### Key design constraints

* **Non-repainting:** uses bar-close confirmation and `barmerge.lookahead_off`.
* **Semantic correctness:** state is labeled “OUTLOOK (STATE)” and forecasts are labeled “FORECAST (PROB)”.
* **Data sufficiency:** forecast output is gated by minimum sample size (`calMinSamples`) and shows neutral/insufficient signals (`…`, `n0`) rather than pretending.

---

### 2) High-level architecture

The script has three major subsystems:

1. **Trading logic**

   * Trend/volatility/guardrails/macro/drawdown
   * Confidence scoring and gating
   * Entry/exit state machine (pos: FLAT/LONG/SHORT)

2. **Outlook (state) engine**

   * Per timeframe state scoring via `request.security()`
   * Outputs bias symbols and components (Trend / Momentum / Location)

3. **Forecast calibration engine**

   * Learns historical mapping from state → forward outcome probability
   * Maintains counts per “score bin” per timeframe
   * Produces `Pred(N)`, `Pred(1)`, `PUp(N)`, `PUp(1)` with sufficiency gates

The **table** is the presentation layer showing:

* System status (confidence, volume, strength, etc.)
* OUTLOOK block (state diagnostics)
* FORECAST block (calibrated probabilities)

---

### 3) Non-repainting and timing semantics

#### 3.1 `request.security()` behavior (critical)

For a higher timeframe `tf` (e.g., 5m on a 1m chart):

* The 5m series updates only when the **5m bar closes**
* Between 5m closes, the series **holds the last completed value**
* With `barmerge.lookahead_off`, you never see “future” higher-timeframe values

So:

* **Outlook** is a snapshot of the last confirmed bar for that tf
* **Forecast** uses those confirmed state values as conditioning inputs

#### 3.2 `barstate.isconfirmed` usage

The script updates and prints only on confirmed bars to ensure:

* Calibration counts are not updated mid-bar
* Table isn’t flickering/partially updated
* You see stable values tied to the last close

**Important nuance:**
If you are on a live bar, the table may not refresh until the bar closes. That’s intentional.

---

### 4) Trading logic subsystem (signals)

#### 4.1 Core indicators

* `emaF = EMA(close, emaFastLen)`
* `emaS = EMA(close, emaSlowLen)`
* `atr = ATR(atrLen)`

#### 4.2 Volatility regime and guardrails

The script estimates volatility regime with:

* `atrRank = pct_rank(atr/close, volRankLen)` in [0..1]

Guardrails count flags:

* `volShock`: atrRank above high threshold
* `gapShock`: open vs prevClose gap %
* `rangeShock`: intrabar range %

`guardrailCount = volShock + gapShock + rangeShock`

Guardrails reduce trust via penalties.

#### 4.3 Macro context gate

Macro is approximated by percentile rank of close over lookback:

* `macroPct = pct_rank(close, macroLen)`
* `macroScore = 1 - macroPct` (unless Off)

Macro gating (if `Hard Gate`):

* Long allowed only if macroPct below long threshold
* Short allowed only if macroPct above short threshold

#### 4.4 Drawdown haircut and hard gate

* `ddPeak = highest(close, ddLookback)`
* `ddAbs = max(0, -(close - ddPeak)/ddPeak)` drawdown magnitude
* Applies continuous penalty and optional hard gate

#### 4.5 Confidence momentum: adaptive RSI + hysteresis

The script maintains momentum state with hysteresis:

* Uses adaptive RSI length depending on chart TF:

  * <=5m: `rsiLenFastTF`
  * <=1h: `rsiLenMidTF`
  * > 1h: `rsiLenSlowTF`

It doesn’t “toggle” momentum on every small RSI wiggle:

* `momLongOnState` turns ON above `rsiLongOn`, OFF below `rsiLongOff`
* `momShortOnState` turns ON below `rsiShortOn`, OFF above `rsiShortOff`

This makes confidence less noisy and more trend-continuation-friendly.

#### 4.6 Connors RSI factor (3,2,100)

Connors RSI is computed as the average of:

* RSI(close, 3)
* RSI(streak, 2) where streak counts consecutive up/down closes
* Percent rank of `ta.change(close)` over 100, scaled to 0..100

This is used as a **multiplicative factor** on confidence:

* Helps modulate confidence based on short-term “timing/quality”
* Not used as the primary directional gate

#### 4.7 Trust score computation

`f_trust_score()` produces a 0..1 value from weighted components:

* Accuracy score (trend + momentum alignment)
* Regime score (penalize high vol)
* Guardrail score (penalize guardrail flags)
* Data quality proxy
* Macro score

Then:

* Multiply by config multiplier (Standard/Pro/V2…)
* Apply drawdown penalty
* Apply Connors RSI factor

#### 4.8 Gating and signal engine

Gate is:

* confidence >= minTrust
* AND MTF OK (if enabled)
* AND macro gate OK
* AND drawdown hard gate not hit

Signal engine logic:

* **Trend+Pullback**: enters on trend flip or reclaim
* Exit logic prioritizes exit/cover before entry
* Cooldown prevents rapid re-entries

This is your “trading decision layer”. It’s independent from the forecast calibration (though it uses the same confidence foundation).

---

### 5) Outlook (State) subsystem

#### 5.1 State definition

For each timeframe, state is computed by `f_state_pack()`:

Inputs:

* EMA fast vs slow
* RSI vs thresholds
* Close vs EMA slow

Outputs:

* `trend ∈ {-1,0,1}`
* `mom ∈ {-1,0,1}`
* `loc ∈ {-0.5, 0, 0.5}`
* Combined score:

  * normalized into `score ∈ [-1..+1]`

Then the table shows:

* Bias symbol from score: ▲ ▼ −
* Score numeric
* T/M/L components (trend/mom/loc)
* RSI value

#### 5.2 Meaning

**Outlook** is a descriptive regime snapshot:

* It’s valid and useful for context and multi-timeframe alignment.
* It is not predictive by itself.
* It updates at the close of each timeframe’s bar.

---

### 6) Forecast (Probabilities) subsystem

This is the most important “new” part compared to your earlier state-only table.

#### 6.1 What exactly is being forecast?

In the current script:

> **Target:** On timeframe `tf`, whether the **next confirmed bar** closes higher than the previous bar (`close > close[1]`).

So forecast is literally:

* `PUp = P(close_next > close_current | current_state_bin)`

This is a *directional next-bar* model.
If you want “trend continuation” defined differently (e.g., forward return over multiple bars, or no adverse excursion), the target function must change.

#### 6.2 Conditioning variable: state score

Forecast does not use raw EMA/RSI directly. It uses the *derived state score* (−1..+1) as the “state descriptor”.

#### 6.3 Binning: score → discrete state bucket

`f_bin(score, bins)` maps score to one of `bins` discrete buckets.

Example:

* bins=3: bearish / neutral / bullish
* bins=5: more granularity, needs more samples

Binning is critical: it reduces the continuous state space into a manageable categorical distribution you can calibrate with limited data.

#### 6.4 Calibration storage (counts)

For each timeframe, the script keeps arrays (length = bins):

* `count[b]` = number of times state fell into bin b
* `upCount[b]` = number of those times the next bar closed up

This is done **separately** for:

* `Pred(N)` / `PUp(N)` (binned model)
* `Pred(1)` / `PUp(1)` (a “more reactive” variant)

Conceptually:

* **N** is “coarser / more stable”
* **1** is “more immediate / reactive”
  (Your current implementation still bins, but the intent is to separate smoothing/conditioning behavior.)

#### 6.5 Update timing: why bar-close only matters

Updates happen only when `barstate.isconfirmed`:

* prevents double-counting during intrabar evaluation
* keeps calibration consistent with non-repaint principle

#### 6.6 Probability estimate with smoothing

For each bin:

> `PUp = (up + α) / (n + 2α)`

Where:

* `n = count[b]`
* `up = upCount[b]`
* `α = alphaSmooth`

This is Laplace/Beta(α, α) style smoothing:

* Avoids 0%/100% probabilities when sample sizes are small
* Gradually converges as n grows

#### 6.7 Data sufficiency gating and Reliability

Two levels of "insufficient" are displayed:

* `n0` / "—" when calculation is impossible (no data)
* `warmup` when n < `calMinSamples`

This is a major correctness improvement: the UI tells the truth about how much evidence exists.

#### 6.8 Turning probability into prediction symbols

`Pred()` is derived from probability thresholds:

* ▲ if `PUp > predUpThr` (e.g. > 0.55)
* ▼ if `PUp < predDnThr` (e.g. < 0.45)
* − otherwise

These thresholds define your "decision boundary" and can be widened/narrowed for stricter/looser prediction.

#### 6.9 Brier Score (Accuracy Tracking)

The script now tracks the **Brier Score** (Mean Squared Error of probability forecasts) to objectively measure accuracy.

* **Score Range:** 0.0 (Perfect) to 1.0 (Worst). 0.25 is random/useless (like guessing 50% every time).
* **BS(N)**: Tracks long-term accuracy. Crucially, this score is **gated by `calMinSamples`**. It only penalizes the model for bins that are considered "mature." This prevents "warmup" noise from ruining the long-term score.
* **BS(1)**: Tracks short-term/fast accuracy. This score is **always active**, updating on every trade regardless of sample size. It reflects the model's immediate adaptability.

#### 6.10 Confidence Intervals & Reliability Labels ("Method 2")

To prevent false confidence in small sample sizes, the system calculates a **95% Confidence Interval (CI)** for every probability.

* **Formula:** standard Wald interval $1.96 \cdot \sqrt{p(1-p)/n}$.
* **Labels:**
  * **"strong"**: CI half-width $\le 5\%$ (High precision).
  * **"ok"**: CI half-width $\le 10\%$ (Acceptable precision).
  * **"weak"**: CI half-width $> 10\%$ OR $n < 30$ (Low precision).
* **Visuals:** The table displays the CI range (e.g., `±4.2pp`) next to the probability.

---

### 7) The Table UI: what each section means

#### 7.1 Status rows (top)

* Confidence: your gate confidence (0..100%)
* MinTrust: threshold used for gating
* Volume: current volume formatted
* Strength: RSI(7) (quick short-term strength)
* MTF: selected set + MTF score
* Pos: FLAT/LONG/SHORT
* LastSig: last action
* Time: timestamp

#### 7.2 OUTLOOK (STATE) block

Columns:

* TF
* Bias (▲/▼/−)
* Score (−1..+1)
* T/M/L components
* RSI

Interpretation:

* Bias/score tells you the current regime snapshot on that TF.
* T/M/L helps you debug why it’s biased (trend vs momentum vs location).

#### 7.3 FORECAST (PROB) block (New Layout)

Columns:

* **TF**: Timeframe label (e.g., 5M, 1H).
* **Pred(N)**: Stable directional call (e.g., ▲ 55%). Shows "warmup" if insufficient data.
* **Data (N)**: Reliability Stats.
  * Format: `Samples/Total` + `Label` + `±CI`
  * Example: `42/150` `strong` `±4.2pp`
  * Gives you instant context on *why* you should (or shouldn't) trust the signal.
* **Pred(1)**: Fast/Reactive directional call.
* **Data (1)**: Reactive Stats (always calculation, useful for spotting regime shifts early).

Interpretation:

* **Pred(N)** is your strategic signal. Trust it only when Data(N) says "strong" or "ok".
* **Pred(1)** is your tactical signal. Be wary of it, but use it to spot turns before N catches up.
* **Brier Checks:** If Brier Scores (shown in footer or header tooltips if enabled) are high (>0.25), the market is currently defying the model's logic.

#### 7.3.1 The difference between #(N) and #(1) (Plain English)

* **#(N) — The "Trusted Veteran" (Strategic)**
  * **Behavior:** Highly selective. Ignores "warmup" noise.
  * **The Change:** Its accuracy score (Brier Score) now *pauses* and waits until a specific pattern has occurred enough times (e.g., 40+ samples) to be statistically "mature."
  * **Why used:** Prevents early luck/bad luck from skewing long-term accuracy.
  * **How to read:** If you see a signal here, it is based on a **proven, high-confidence** history.

* **#(1) — The "Fast Scout" (Tactical)**
  * **Behavior:** Always active. Learns and reports on *everything* from trade #1.
  * **The Change:** Tracks accuracy instantly. Ignores sample size rules.
  * **Why used:** Spots new market regimes fast. If `#(N)` says "UP" but `#(1)` accuracy fails (high Brier score), the trend might be dying.
  * **How to read:** Use as an early warning system.

#### 7.4 Footer rows ("Params" and "Meaning")

These are guardrails against semantic confusion:

* It states what’s what.
* It shows calibration parameters affecting forecast behavior.

---

### 8) How to use the script (practical workflow)

#### Step 1 — Choose your chart timeframe

Most common:

* Trade on 1m or 5m charts for intraday continuation
* Or 15m/1h for slower continuation

#### Step 2 — Let calibration accumulate

The forecast block needs sample sizes.
If `calMinSamples = 50`, you need at least ~50 occurrences per bin per timeframe.
With bins=3, that means:

* You need a decent amount of history/time for stable outputs.

**Tip:** Start with:

* `predBins = 3` (fewer bins → faster learning)
* `alphaSmooth = 1.0` (reasonable smoothing)
* `calMinSamples = 30–50`

#### Step 3 — Read Outlook first, then Forecast

Recommended decision flow:

1. Check OUTLOOK across TFs:

   * Are most timeframes aligned bullish (▲)?
2. Then check FORECAST:

   * Is PUp(N) above your threshold on your trading timeframe and the next one above it?
3. Use confidence gate:

   * Only trade when your confidence and gating permit

#### Step 4 — Tune thresholds to your risk tolerance

* If you want fewer but stronger signals:

  * Increase `predUpThr` and decrease `predDnThr` (wider neutral zone)
* If you want more signals:

  * Bring thresholds closer to 0.50 (but expect noise)

#### Step 5 — Reset calibration only when appropriate

Use `Forecast: Reset calibration now` when:

* Switching symbols with radically different behavior
* Switching markets/regimes (e.g., crypto vs equities)
* You changed the state definition or bin count

Avoid resetting constantly—calibration needs data to become meaningful.

---

### 9) Common misunderstandings (and how this script avoids them)

#### “Isn’t Outlook already a forecast?”

No.
Outlook is a present-state diagnostic.
Forecast is a statistical statement about **future outcomes conditioned on state**.

#### “Why does 5m not change every 1m bar?”

Because 5m data only finalizes on 5m bar close.
That’s correct non-repainting behavior.

#### “Why do I see … or n0?”

Because the model is honest: there isn’t enough data yet for that state bin.

#### “Is the forecast guaranteed?”

No. It’s a **calibrated probability**, not a promise.
It reflects *historical frequency under similar states*.

---

### 10) Performance and limits (Pine constraints)

* `request.security()` is expensive. You’re doing it per timeframe for state packs and outcome checks.
* Seven horizons × multiple security calls can be heavy.
* If TradingView hits execution limits:

  * Reduce the number of horizons
  * Reduce debug outputs
  * Reduce bins or simplify state pack

---

### 11) If you want true “Trend-Continuation forecast” (stronger target)

Right now the forecast target is **next-bar direction**.

For “trend continuation” you may prefer targets like:

* Forward return over H bars > 0 (e.g., `close[H] > close`)
* Or “no adverse excursion” before reaching a profit threshold
* Or “trend still bullish after H bars” (EMA structure persists)

The calibration framework stays the same—only the **realized outcome function** changes.

If you tell me your exact continuation definition (e.g., “price is higher after 3 bars” or “reaches +0.3 ATR before -0.2 ATR”), I can document and implement that target cleanly.

---

### 12) Quick glossary (for users)

* **Bias**: current state direction indicator (▲/▼/−)
* **Score**: numeric state summary (−1..+1)
* **T/M/L**: Trend / Momentum / Location components
* **Pred(N)**: prediction symbol from stable calibration model
* **Pred(1)**: prediction symbol from more reactive companion model
* **PUp**: probability next bar closes up, given current state bucket
* **MinN**: minimum sample size required before predictions become “active”
* **α**: smoothing strength to prevent extreme probabilities early

---

## TradingView Author’s Notes (User Manual)

### What SkippALGO is

SkippALGO combines a **signal engine** (entries/exits) with a **dashboard** that shows:

* **Outlook (State):** what the market looks like *right now* on each timeframe (bias/regime snapshot)
* **Forecast (Probability):** a *calibrated* probability estimate of a forward outcome (e.g., next-bar direction) conditioned on the current state

It is **non-repainting** by design: values are based on confirmed (closed) bars and do not peek into the future.

---

### Quick Start (recommended workflow)

1. **Pick your trading timeframe** (example: 1m or 5m for intraday continuation).
2. **Enable “MTF confirmation”** if you want the higher TFs to act as a trend filter.
3. **Wait for calibration** (Forecast section) to collect enough samples if you use probability forecasting.
4. Use the table:

   * Check **Outlook alignment** across TFs (are multiple TFs pointing the same way?)
   * Check **Forecast probabilities** on your trading TF (and the next higher TF)

---

### How to read the Table

#### A) Status rows (top)

You’ll typically see:

* **Confidence:** your internal trust score (0–100%)
* **MinTrust:** minimum confidence required to allow trades
* **MTF:** the selected MTF set and the current MTF vote/score
* **Pos / LastSig:** current position state and last action
* **Strength:** quick momentum/strength (often RSI7)
* **Volume:** volume display (if applicable)

This block answers: *“Is the engine allowed to trade right now?”*

---

#### B) Outlook (State)

This is **not forecasting**.

Outlook shows, per timeframe:

* A **bias symbol** (▲ / ▼ / −)
* Often a **score** (e.g., -1..+1) and/or components (Trend / Momentum / Location)
* Sometimes the RSI used in state scoring (for transparency)

**Meaning:**

* ▲ = state is bullish *on that timeframe’s last confirmed bar*
* ▼ = state is bearish
* − = neutral / mixed

**Important:** higher timeframe values only change when that timeframe closes. That’s expected.

---

#### C) Forecast (Probability)

This is the **predictive** part — but only for the **specific target** defined by the script (commonly “next-bar up vs down” on each TF).

You’ll typically see 5 columns like:

* **TF**
* **Pred(N)** (symbol derived from probability model using N-bin calibration)
* **Pred(1)** (more reactive companion prediction)
* **PUp(N)** (probability of “Up” under N-bin model)
* **PUp(1)** (probability of “Up” under 1-mode/companion model)

**Data sufficiency matters:**

* If you see `…` or `n0`, it means **not enough samples** to trust the forecast.
* The script is intentionally conservative rather than inventing certainty.

---

### What Pred(N) vs Pred(1) means (intuitive)

* **Pred(N)** is the “stable” prediction: coarser conditioning, typically slower to change, needs fewer mistakes from noise.
* **Pred(1)** is a “reactive” companion: responds faster but can be noisier.

A common use:

* Require **Pred(N)** to agree with your direction
* Use **Pred(1)** as a timing aid or early warning

---

### How to trade with it (Trend-Continuation style)

A practical, rules-based approach:

#### Long continuation idea

1. Outlook is bullish on your trading TF (▲)
1. Outlook is bullish or neutral on the next higher TF (▲ or −)
1. Forecast probability is supportive: `PUp(N) > 55%` and ideally `PUp(1)` also above threshold.
1. Engine gate is open: Confidence ≥ MinTrust; MTF and Macro gates allow Long; not in drawdown hard gate.

#### Short continuation idea

Same logic inverted.

---

### Calibration warm-up (Forecast)

Forecast quality improves with data. You will get best results when:

* You have enough historical bars loaded
* You avoid too many bins early on (start with 3 bins)
* You do not reset calibration too frequently

If you change:

* symbol class (equities → crypto),
* session structure,
* or the state definition / bin count,

then a reset can make sense — otherwise let it accumulate.

---

### Common confusion / troubleshooting

#### “Outlook changes only every 5 minutes on the 5m row”

Correct. 5m data finalizes only on 5m close. This is non-repainting behavior.

#### “Forecast shows …”

That means insufficient sample size for calibration. Reduce bins, reduce min-samples, or accumulate more history.

#### “Why doesn’t the table update mid-candle?”

The script prints on **confirmed bars** to avoid flicker and inconsistent counts.

---

### Safety and limitations

* This is an analytical tool; it does not guarantee profits.
* Forecast is a **conditional probability estimate**, not certainty.
* Always combine with risk management (stop, sizing, session filters).

---

## Developer Appendix (Deep Technical)

This section is written for maintaining/extending the script safely.

### 2.1 Execution model (Pine)

* Script executes on every chart update.
* **Non-repainting standard** requires:

  * All HTF fetches use `request.security(..., lookahead_off)`
  * Calibration updates only on **bar-close** (typically `barstate.isconfirmed`)
  * Table updates either on `barstate.isconfirmed` or `barstate.islast` (depending on how you want UI refresh)

#### Key invariant

> **No forward-looking reference** and no partial-bar calibration updates.

---

### 2.2 Subsystem boundaries

#### A) Trading / gating subsystem

Core outputs:

* `confidence ∈ [0,1]`
* `gateLongNow`, `gateShortNow` booleans
* Position state machine: `pos ∈ {-1,0,+1}`
* Signals: `buySignal, exitSignal, shortSignal, coverSignal`

#### B) Outlook (state) subsystem

Core outputs per TF:

* `score_tf ∈ [-1, +1]`
* Optional components: trend/mom/loc
* Symbol mapping: ▲ ▼ −

#### C) Forecast (calibration) subsystem

Core outputs per TF:

* `PUp(N)`, `PUp(1)` ∈ [0,1]
* `Pred(N)`, `Pred(1)` derived from thresholds
* Sample counts `n` with minimum sample gating

---

### 2.3 Outlook: recommended state definition (contract)

#### State pack contract (per TF)

Inputs:

* `emaFastLen`, `emaSlowLen`
* `rsiLenState` (for state; not necessarily the same as confidence RSI)
* thresholds (e.g., RSI > 55 bullish, <45 bearish)

Data fetch (must be non-repainting):

* `close_tf = request.security(syminfo.tickerid, tf, close, gaps_off, lookahead_off)`
* `emaF_tf = request.security(..., ta.ema(close, emaFastLen), ...)`
* `emaS_tf = request.security(..., ta.ema(close, emaSlowLen), ...)`
* `rsi_tf  = request.security(..., ta.rsi(close, rsiLenState), ...)`

Derived components:

* `trend = sign(emaF_tf - emaS_tf)` in {-1,0,1}
* `mom   = +1 if rsi_tf>hi, -1 if rsi_tf<lo, else 0`
* `loc   = +0.5 if close_tf>emaS_tf, -0.5 if <, else 0`

Score normalization:

* combine into `raw = trend + mom + loc`
* map to [-1,+1] via stable normalization

**Invariant:** score depends only on confirmed HTF bar values.

---

### 2.4 Forecast: calibration math and mechanics (contract)

#### 2.4.1 Define the forecast target (must be explicit)

Common target:

* `upNext = (close_tf > close_tf[1])` on that same timeframe

Other valid targets (trend continuation variants):

* `close_tf[k] > close_tf` (k-step)
* forward return > threshold (in ATR units)
* “hit +X ATR before -Y ATR” (path-dependent; heavier)

**Invariant:** target must be computed on the timeframe’s confirmed bars.

---

#### 2.4.2 Conditioning variable

Use `score_tf` (from Outlook) as the state descriptor.

Then you have two calibration modes:

* **N-bin** mode: bucket score into `predBins` discrete states
* **1-mode** (companion): typically different smoothing/thresholding, or uses a different score mapping; the point is to provide a second “lens”

---

#### 2.4.3 Binning

Function contract:

* `bin = f_bin(score, bins) -> int in [0..bins-1]`
* score ∈ [-1,+1]

Recommended mapping:

* `u = (score + 1) / 2` to map to [0,1]
* `bin = clamp(floor(u * bins), 0, bins-1)`

**Invariant:** identical score always maps to identical bin.

---

#### 2.4.4 Count storage

For each timeframe and each bin you maintain:

* `cnt[b]` total occurrences
* `up[b]` number of up outcomes

In Pine you implement this with `var` arrays:

* `var int[] cnt = array.new_int(bins, 0)`
* `var int[] up  = array.new_int(bins, 0)`

If you support multiple timeframes, you either:

* keep separate arrays per TF, or
* keep 2D arrays encoded as 1D blocks

**Invariant:** counts must update **exactly once per confirmed event**, or calibration breaks.

---

#### 2.4.5 Update timing (critical)

Calibration updates should be tied to the timeframe close event, not every chart bar.

In Pine, for each TF series you can detect “new confirmed HTF bar” by comparing `time_tf`:

* `t_tf = request.security(syminfo.tickerid, tf, time, ..., ...)`
* `newTfBar = ta.change(t_tf)` (IMPORTANT: computed on every bar)

Then you update counts only when `newTfBar` is true (and optionally also require `barstate.isconfirmed` on the chart bar).

**Fix for the warning you mentioned:**

> Any `ta.change()` used inside a conditional must be precomputed globally, because it depends on history.

So:

* `chg_t_tf = ta.change(t_tf)`
* then use `if chg_t_tf` …

**Invariant:** do not hide `ta.change()` inside short-circuit expressions.

---

#### 2.4.6 Probability with smoothing

Using Laplace/Beta smoothing:

* `pUp = (up + alpha) / (cnt + 2*alpha)`

Where `alpha` is float > 0.

**Invariant:** pUp is always within [0,1], even for cnt=0 (it becomes 0.5 if alpha symmetric).

---

#### 2.4.7 Minimum samples gate

Define:

* `canCal = cnt > 0` (or other requirements)
* `enough = cnt >= calMinSamples`

UI behavior:

* If not `canCal`: show “—”
* If `canCal` but not `enough`: show “…” and dim colors
* If `enough`: show normal symbols and probability

This is correctness + UX.

---

### 2.5 Prediction symbol + color functions (avoid “tblText” scope bugs)

#### The exact issue you hit

Your functions referenced `tblText` but `tblText` wasn’t in scope (or was declared later / inside a block).

**Rule:** any helper that uses UI colors should either:

1. receive the color as an argument, or
2. use globally defined constants declared *before* the function block.

Recommended signature style:

* `f_predColorP(pUp, n, canCal, colNeutral, colDim) => ...`
* `f_probTextColor(pUp, n, canCal, colNeutral, colDim) => ...`

This eliminates “Undeclared identifier” issues and makes helpers reusable.

---

### 2.6 Table refresh rules (why tables go empty)

Tables appear “empty” typically due to one of these:

1. `showTable` false
2. `table.clear()` called but subsequent `table.cell()` not executed (due to guard logic)
3. `barstate.isconfirmed` gating prevents updates on live candle (expected)
4. wrong row/col indices or cell writes outside bounds
5. you used `if barstate.islast` but are in replay/market closed context and it isn’t true as expected

**Recommended pattern:**

* Compute all values unconditionally

* Then do:

* `if showTable and barstate.isconfirmed`

  * clear
  * write all cells

This is deterministic and avoids partial refresh.

---

### 2.7 Maintenance checklist (high-signal)

When you change anything, verify these invariants:

#### Non-repaint invariants

* All HTF uses `lookahead_off`
* Calibration updates only on confirmed TF events
* Table prints only on confirmed bars (or last bar, but consistent)

#### Semantic invariants

* “Outlook” labels state only
* “Forecast” labels probability only
* Forecast rows show `n` / `…` when insufficient

#### Consistency invariants

* `ta.change()` / similar history-dependent functions computed every bar globally
* No “short-circuit skipping” of history-dependent calls
* Array bounds always correct (bins, rows, columns)

---

### 2.8 “Developer user story”: how to extend targets safely

If you want to forecast **trend continuation**, do not reuse “next-bar up” blindly. Define continuation precisely, e.g.:

* continuationLong = `(close_tf[3] > close_tf)` (3-bar forward)
* or continuationLong = `(high_tf reaches close_tf + x*ATR before low_tf reaches close_tf - y*ATR)`

Then:

* update the target function
* reset calibration
* let samples accumulate
* confirm min-samples gating still works

---

## Release Notes — SkippALGO (Outlook + Forecast)

**Scope:** semantic correction + probabilistic forecasting + table/UI reliability
**Applies to:** Pine v6 script (SkippALGO)

---

### vNext — Semantic Fix + Calibrated Forecast Engine (Probability-Based)

#### What changed (high level)

This release splits the dashboard into two clearly defined parts:

1. **Outlook (State)**
   A multi-timeframe **snapshot** of the current market regime/bias based on the last confirmed bar for each timeframe.

2. **Forecast (Probability)**
   A **calibrated**, evidence-driven probability estimate of a forward outcome conditioned on the current state.

This is a deliberate semantic correction: **state is not called “forecast” anymore**.

---

### Major Improvements

#### 1) Forecast is now a real forecast (probability, not state)

**Previous behavior:**
The table displayed MTF “bias” computed from confirmed HTF bars (EMA/RSI/location score). This is useful context, but it is a **retrospective state description**, not a forecast.

**New behavior:**
A calibration engine learns from historical data:

* It observes the **current state** (derived from the outlook score)
* It tracks the **next outcome** (e.g., next-bar up vs down on that timeframe)
* It produces **PUp** = conditional probability of “Up” given that state

**Result:** the table now includes **probabilities** and corresponding prediction symbols derived from thresholds.

---

#### 2) Data sufficiency is explicit (no fake certainty)

Forecast outputs are now gated by sample size:

* If calibration cannot be computed → show `—`
* If calibration exists but is insufficient (`n < calMinSamples`) → show `…` / `nX` and dim colors
* If sufficient → show Pred + PUp normally

This prevents premature “100% / 0%” style misinterpretations early in calibration.

---

#### 3) Table now includes 5 columns (Pred(N) + Pred(1) + both probabilities)

The Forecast block now supports a clearer decision interface with:

* **Pred(N)**: stable prediction symbol (N-bin calibration)
* **Pred(1)**: more reactive companion prediction
* **PUp(N)**: probability for the stable model
* **PUp(1)**: probability for the reactive model

This makes it easy to compare:

* stability vs reactivity,
* probability support vs symbol output.

---

#### 4) Non-repainting consistency tightened (`barstate.isconfirmed` guard)

To prevent inconsistent or flickering UI and to ensure calibration integrity:

* Calibration updates and/or table rendering are guarded to occur on **confirmed bars**
* HTF data is fetched with `request.security(... lookahead_off)`

This ensures the dashboard does not “paint future” or update calibration mid-bar.

---

#### 5) Pine consistency warning fixed (`ta.change()` must execute every bar)

A known Pine issue was addressed:

> If `ta.change()` is placed inside conditional expressions, it may not run every bar, causing inconsistent results.

**Fix:**
History-dependent calls like `ta.change()` are now computed into global variables first and then used inside conditions.

This removes warnings and improves determinism.

---

#### 6) UI color scheme unified and stabilized

The table’s visual theme was aligned with your chosen “clean / navy / cyan frame / dim text” scheme.
In addition, helper functions were adjusted to avoid referencing identifiers not in scope (e.g., `tblText`), preventing runtime compile errors.

---

### Behavioral Clarifications (important)

#### Outlook vs Forecast

* **Outlook (State)** = what the last confirmed bar indicates (bias/regime snapshot)
* **Forecast (Probability)** = a conditional probability estimate of a defined forward outcome

The script intentionally does not claim that “Outlook” is predictive by itself.

---

### Migration Notes / How to interpret the update

#### If you previously used “Forecast TF” as direction guidance

Treat that information as **Outlook** now. It’s still useful for:

* multi-timeframe alignment,
* regime filtering,
* context for signal gating.

#### How to use Forecast effectively

* Wait for calibration to accumulate (watch `n` / `…`)
* Start with **few bins** (e.g., 3) and reasonable minimum samples
* Prefer Pred(N) as the stable primary signal, Pred(1) as a timing/early-warning companion

---

### Known Limitations

* Forecast is only as good as its target definition and available historical samples.
* Multi-timeframe calibration can take time to “warm up,” especially with more bins and higher timeframes.
* Pine `request.security()` calls are expensive; too many horizons or debug rows may hit performance limits.

---

### Next Recommended Enhancements (optional roadmap)

* Add alternate forecast targets for “trend continuation” beyond next-bar direction (e.g., k-bar forward return, ATR-based continuation, path-based targets).
* Add per-timeframe sample counts directly in the table for transparency.
* Add an optional “calibration reset per timeframe” control (instead of global reset).

### Recent quality upgrades (v6.2+)

* Per-horizon **quantile bins** (no cross‑TF mixing of score distributions).
* Direction‑aware **macro score** to avoid short bias in oversold regimes.
* **Wilson** confidence intervals for reliability labels (more stable at small $n$).
* Directional **edge** gating for 3‑way probabilities.
* Optional **PathTPvsSL** entry gating and **chop abstain** (high Flat in sideways).
* Optional **ECE/Drift** gating and soft confidence penalty on eval degradation.
* Table badges: **STATE** vs **PROB**, plus **nCur/Total** and target footer for transparency.

---

## TradingView Changelog (User-Friendly)

### ✅ vNext — Outlook + Forecast Upgrade (Semantic Fix + Probability Forecasting)

#### What’s new

* **Outlook (State)** and **Forecast (Probability)** are now separated and labeled correctly.
* The table now shows a real **probability forecast** (conditional probability), not just multi-timeframe bias.
* Forecast block now has **5 columns**:

  * **TF | Pred(N) | Pred(1) | PUp(N) | PUp(1)**

#### What changed

* The old “Forecast” display was actually a **state snapshot** (bias based on confirmed HTF bars).
  It’s still valuable, but it is now correctly presented as **Outlook (State)**.
* A new **calibration engine** learns from history and outputs **PUp** probabilities for a defined forward outcome (typically “next-bar direction” per TF).

#### Reliability / correctness improvements

* Forecast outputs are now **data-sufficiency gated**:

  * `—` = cannot calculate
  * `…` or `nX` = not enough samples yet
  * normal display = enough samples
* Added a **bar-close confirmation guard (`barstate.isconfirmed`)** for stable, non-repainting behavior.
* Fixed Pine consistency warnings by ensuring history-dependent functions (like `ta.change()`) execute every bar.

---

### What this means for you (plain language)

#### 1) Your table is now honest and more useful

Before:

* The “forecast” rows were effectively:
  **“What does the last confirmed 5m/15m/1h bar look like?”**
  That’s **Outlook**, not forecasting.

Now:

* You get **both**:

  * **Outlook (State):** current multi-timeframe bias/regime
  * **Forecast (Probability):** “Given this state, how often did the next bar go up historically?”

#### 2) How to use the new table in practice

Use it top-down:

1. **Outlook first** (context / alignment)

   * If your trading TF and the next higher TF both show ▲, that’s strong continuation context.
2. **Forecast second** (probability support)

   * Prefer **Pred(N)** as the “stable” call.
   * Use **Pred(1)** as a faster but noisier companion.
3. **Respect sample gating**

   * If you see `…`, it’s telling you: “not enough data yet—don’t trust this forecast.”

#### 3) Why you might see `…` after installing

Because the forecast is not guessing—it needs historical samples to calibrate.
Once enough occurrences have been observed, the table becomes “fully active.”

---

### Ultra-short TradingView description (1 paragraph)

SkippALGO is a non-repainting, bar-close confirmed signal + dashboard script that separates **Outlook (State)** from **Forecast (Probability)**. The Outlook block shows current multi-timeframe bias/regime (based on confirmed HTF bars). The Forecast block adds a calibrated probability layer: it learns from historical occurrences of the current state and estimates **PUp** (probability the next bar closes up) per timeframe, with explicit sample-size gating (`—` / `…` when insufficient data). The table includes **TF | Pred(N) | Pred(1) | PUp(N) | PUp(1)**, enabling stable vs reactive probability-based confirmation for trend-continuation decisions.

---

### 5) SkippALGO_Strategy (Deep Upgrade Synchronization)

#### Update Date: Jan 31, 2026

The strategy file `SkippALGO_Strategy.pine` has been fully upgraded to **Version 6.1** standards to match the main indicator's probabilistic engine.

### Key Features Synchronized

1. **Target Profiles**: Strategy now trades based on the same targets as the indicator (K-Bar ATR, Path TP/SL, etc.) rather than simple next-bar close.
2. **2D Binning**: Trade entry probabilities are now conditioned on **Volatility Rank** in addition to the Algo Score.
3. **Ensemble Scoring**: Strategy entries use the composite `sEns` (Trend + Pullback + Regime) signal.
4. **Platt Scaling**: The backtester uses the SGD-calibrated probabilities (`pAdj`) for its "Confidence" filter.

### Workflow

* The Strategy file mimics the Indicator's logic but executes trades (`strategy.entry`) instead of just plotting.
* It serves as the **Backtesting Engine** to validate the `v6.1` Deep Upgrade changes.
* **Note**: Due to Pine Script limits, the strategy may have slightly different memory constraints than the indicator, but the logic is 1:1.

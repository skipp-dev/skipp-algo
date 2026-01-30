# Roadmap Outline — Next Recommended Enhancements

## 0) Guiding principles (applies to all items)

* **Semantic guardrail:** Never label state as forecast. State stays “Outlook”; predictive outputs stay “Forecast (Prob)”.
* **Non-repainting:** All forecast targets must be computed on confirmed TF bars (`lookahead_off`), and calibration updates must happen deterministically.
* **Transparency:** Always surface data sufficiency (sample counts) and the forecast target definition in UI (table footer or tooltip rows).
* **Performance-aware:** Minimize `request.security()` calls; prefer packing multiple series in fewer calls where possible (Pine limitations apply).

---

# 1) Alternate Forecast Targets for “Trend Continuation”

## 1.1 Goal

Upgrade forecasting from “next-bar up/down” to **trend-continuation outcome definitions** that match how you trade continuation setups:

* not just direction, but *quality*: persistence, magnitude, and/or path behavior.

You’ll support multiple targets selectable via input.

## 1.2 Scope — Target families (recommended set)

### A) k-bar forward return sign (simple, strong baseline)

**Definition:**
For TF series `close_tf`, forecast:

* `Up_k = close_tf[k] > close_tf` (or return > 0)

**Inputs:**

* `fcTarget = "k-bar return"`
* `k = input.int(3, "k bars ahead", minval=1, maxval=20)`
* Optional: `returnThreshold` (absolute or %)

**Why:**
Cheap to compute, interpretable, aligns to “continuation over next k bars”.

**Calibration impact:**
Counts update when the k-forward outcome is known (must wait k TF bars).

---

### B) ATR-normalized continuation (magnitude-aware)

**Definition:**
Predict whether forward return exceeds threshold in ATR units:

* `ret = (close_tf[k] - close_tf) / atr_tf`
* `Up_k_ATR = ret >= +x` (or symmetric down)

**Inputs:**

* `x = input.float(0.25, "ATR threshold", step=0.05)`
* `atrLenTarget = input.int(14, "Target ATR len")`
* Optional: separate `xLong`, `xShort`

**Why:**
Normalizes across symbols and regimes; aligns with “move of meaningful size”.

**Implementation note:**
Requires `atr_tf` on the TF (via `request.security`).

---

### C) Path-based: “hit take-profit before stop” (best match for continuation trading)

**Definition:**
From entry point (close at state time), within the next `H` TF bars, determine which occurs first:

* price hits `+TP` (e.g., +0.5 ATR) before it hits `-SL` (e.g., -0.3 ATR)

**Example target:**

* `Win = first_hit(high >= entry + tpATR*ATR) occurs before first_hit(low <= entry - slATR*ATR)` within horizon H.

**Inputs:**

* `H = input.int(6, "Horizon bars", minval=1, maxval=50)`
* `tpATR = input.float(0.5, "TP (ATR)", step=0.05)`
* `slATR = input.float(0.3, "SL (ATR)", step=0.05)`
* `resolveMode = "FirstHit" | "CloseOnly"` (recommend FirstHit)

**Why:**
This is closest to “trend continuation with risk control” and produces actionable probabilities.

**Costs/complexity:**

* You need a mini forward-simulation across the next H TF bars.
* In Pine, true “look forward” on current bar is not allowed; you must evaluate the outcome **when H bars have passed** and update calibration retroactively for the originating bar.

---

## 1.3 Architecture changes (how to implement targets correctly)

### 1.3.1 Separate “state time” from “resolution time”

For each TF, on each new confirmed TF bar:

* compute and store:

  * `stateScore` (conditioning feature)
  * `entryPrice` (reference point)
  * `atrRef` (if needed)
  * `time_tf` or an index

Then, after k or H bars:

* resolve outcome for that earlier state
* update calibration counts for the bin of that earlier state

This implies a **queue/ring buffer** per TF for pending forecasts.

---

### 1.3.2 Recommended data structure in Pine (per TF)

Use `var` arrays as ring buffers:

* `pendingScore[]` (float)
* `pendingBinN[]` (int)
* `pendingBin1[]` (int) if separate
* `pendingEntry[]` (float)
* `pendingAtr[]` (float)
* `pendingIndex[]` or `pendingTime[]`
* For path-based:

  * `pendingMaxHigh[]`, `pendingMinLow[]` accumulators
  * Or update rolling extremes as bars arrive

Because Pine arrays can be managed, but keep sizes bounded:

* use fixed capacity, e.g. `cap = max(H, k) + 5`
* implement push/pop manually

---

### 1.3.3 Outcome resolution logic per target

#### A) k-bar return sign

When you have stored entry at time t:

* resolve at time t+k: `close_tf_now > entry`
  Update bin counts for stored score/bin.

#### B) ATR continuation

Resolve when k bars have passed:

* `((close_tf_now - entry) / atrRef) >= x`

#### C) Path-based first-hit

Maintain for each pending item:

* maxHigh since entry
* minLow since entry
  At each new TF bar, update extremes for all pending items still inside horizon.
  Resolve when:
* maxHigh >= entry + tpATR*atrRef => win
* minLow <= entry - slATR*atrRef => loss
* If horizon ends without hit: classify as neutral / loss / “no decision” depending on your chosen policy.

**Policy choice (recommend explicit input):**

* `NoHitPolicy = "Neutral" | "Loss" | "Ignore"`
  (“Ignore” avoids biasing probabilities in low-vol conditions)

---

## 1.4 Calibration math updates

Calibration remains:

* `pUp = (up + α) / (n + 2α)`
  But now “Up” means “target success” (win event), not just up close.

If you add 3-class outcomes (win/loss/no-hit), consider:

* keep binary for simplicity (win vs not-win) initially
* later upgrade to categorical Dirichlet calibration if needed

---

## 1.5 Table / UI updates required

* Add a footer row: **Forecast Target: …** (e.g., “k=3 bars, ATR x=0.25”)
* Consider showing both:

  * `PWin` (probability of continuation success)
  * optionally `PLoss` if you implement explicit loss tracking

---

## 1.6 Validation checklist

* Confirm counts only update when outcome is *known* (k/H bars later)
* Confirm no lookahead leaks (no referencing future data at origin time)
* Confirm `ta.change(time_tf)` is computed globally and used safely
* Confirm performance acceptable with 6–7 TFs

---

# 2) Add Per-Timeframe Sample Counts in the Table

## 2.1 Goal

Make forecast transparency first-class:

* show `n(N)` and `n(1)` (or at least one n) per TF
* optionally show per-bin n or “current-bin n” (recommended)

## 2.2 What counts are most useful?

### Recommended minimum

Per TF, show:

* `nCur(N)` = sample count for the current state’s bin (N-bin model)
* `nCur(1)` = current-bin sample count for the companion model

This directly answers:

> “How much evidence supports today’s probability?”

### Optional advanced

* show total samples per TF, `nTotal`
* show min/median/max bin counts per TF (for diagnosing bin starvation)

---

## 2.3 Table layout options

You currently have 5 forecast columns. You have three good patterns:

### Option A (best): Add a small “n” line under probability

Keep 5 columns, embed n into text:

* `PUp(N)` cell displays `"62% (n=84)"` when space allows
* fallback to `"62% n84"` for compact

### Option B: Add an extra “n” row per TF block

After each TF row, add a dim row:

* `n(N)=84 | n(1)=52`
  This keeps columns clean.

### Option C: Replace Pred(1) with “n” (not recommended)

You lose the companion signal. Only do this if table width is too constrained.

---

## 2.4 Implementation details

* You need a function:

  * `f_nText(n, canCal) => not canCal ? "n0" : "n" + str.tostring(n)`
* And `nCur` retrieval:

  * `bin = f_bin(score_tf, predBins)`
  * `nCur = array.get(cnt, bin)`  (or per-TF array)

If you store counts per TF, ensure you retrieve the correct TF’s arrays.

---

## 2.5 UX rules

* If `n < calMinSamples`, keep dim color + show `…`
* If `n >= calMinSamples`, normal color
* For extremely low n, consider showing `"n=3 ⚠"` in dim style

---

# 3) Optional “Calibration Reset per Timeframe”

## 3.1 Goal

Today you likely have a global reset input (one button resets all TF calibrations).
Users want to reset only:

* the TF they changed
* or only intraday TFs
* or only the current chart TF

---

## 3.2 UI design options (Pine limitations aware)

### Option A: Per-TF boolean reset inputs (simple, explicit)

Inputs:

* `reset1m`, `reset5m`, `reset15m`, `reset1h`, `reset4h`, `reset1d` (bool)
  Behavior:
* When true, clear arrays for that TF, then auto-set back to false?
  **Pine cannot programmatically change inputs**, so you implement “edge detect”:

  * keep `var bool prevResetX`
  * on rising edge, perform reset

### Option B: Single dropdown selector + “Reset now”

Inputs:

* `resetWhich = input.string("None", options=["None","1M","5M","15M","1H","4H","1D","All"])`
* `resetNow = input.bool(false, "Reset selected calibration now")`
  Use rising edge of `resetNow` and apply to selection.

This is cleaner than 6 booleans.

### Option C: Reset current chart TF only

* `resetWhich = "Chart TF"`
  Useful for traders switching chart TF frequently.

---

## 3.3 Reset semantics (must be defined)

When you reset a TF, you should clear:

* `cnt[]` and `up[]` arrays (all bins)
* pending queues if using k/H targets
* any derived totals

**Important:** If you implement multi-target support, reset should be per:

* timeframe AND target mode
  OR you reset “all targets for this TF”. Make this explicit.

---

## 3.4 Implementation approach

* Maintain per TF `var` arrays (or a multiplexed 1D block)
* Provide a helper:

  * `f_resetCal(refCntArray, refUpArray)` (Pine doesn’t have references like that; you do separate reset functions per TF or a switch block)
* Apply reset on rising-edge event to avoid repeated clearing each bar.

---

## 3.5 Transparency UX

When a TF is reset:

* show `n0` and `…` as expected until samples accumulate
* optionally show a short “RESET” indicator row for 1–2 bars (internal state flag)

---

# 4) Suggested Implementation Order (recommended)

1. **Add sample counts to the table** (lowest risk, immediate transparency)
2. **Add per-timeframe reset control** (low-medium risk, improves usability)
3. **Add alternate forecast targets**

   * Start with **k-bar return sign**
   * Then ATR threshold
   * Then path-based first-hit (most complex)

---

# 5) Acceptance criteria (definition of done)

### Sample counts

* For every TF row, user can see current-bin `n`
* `…` shown until `n >= calMinSamples`

### Per-TF reset

* Resetting one TF clears only that TF’s calibration and pending buffer
* Other TF calibrations remain unchanged

### Alternate targets

* User can select target type
* Table footer shows target definition parameters
* Calibration updates only when outcome is known (k/H bars later)
* No repainting / no lookahead / no Pine warnings about conditional `ta.change`

---

Below is a **concrete Pine implementation plan** that covers **all three enhancements** (alternate targets, per-TF sample counts, per-TF reset) with a **recommended data layout**, **function signatures**, and **performance strategy** to keep `request.security()` calls under control.

---

# A) Performance-first design (reduce `request.security()` calls)

## A1) One `request.security()` per TF, returning a tuple

Instead of 4–8 calls per timeframe, do **one** call per timeframe returning everything you need:

* time (TF bar timestamp)
* close/high/low (for targets)
* emaF/emaS/rsi (for Outlook state)
* atr (for ATR-based targets)

Pattern:

```
[t_tf, c_tf, h_tf, l_tf, emaF_tf, emaS_tf, rsi_tf, atr_tf] =
request.security(syminfo.tickerid, tf,
[time, close, high, low, ta.ema(close, emaFastLen), ta.ema(close, emaSlowLen), ta.rsi(close, rsiStateLen), ta.atr(atrTargetLen)],
barmerge.gaps_off, barmerge.lookahead_off)
```

That’s **7 TFs → 7 security calls** total for the full dashboard + forecasting.

---

# B) Enhancement 1 — Alternate Forecast Targets (Trend Continuation)

You’ll implement a **target selector** and a **per-TF pending queue** so outcomes are only scored when they’re actually known (k/H bars later). This preserves non-repaint semantics and stops “guesswork”.

## B1) Inputs

Add:

```
fcTarget = input.string("NextBar", "Forecast target",
options=["NextBar", "KBarReturn", "KBarATR", "PathTPvsSL"])

kBars = input.int(3, "k bars ahead", minval=1, maxval=20)

atrTargetLen = input.int(14, "ATR len (target)", minval=2)
atrThr = input.float(0.25, "ATR threshold (KBarATR)", step=0.05)

pathH = input.int(6, "Path horizon H bars", minval=1, maxval=50)
tpATR = input.float(0.50, "TP (ATR)", step=0.05)
slATR = input.float(0.30, "SL (ATR)", step=0.05)
noHitPolicy = input.string("Ignore", "No-hit policy", options=["Ignore", "Neutral", "Loss"])
```

## B2) Conditioning variable stays the same: Outlook score

Forecast is conditioned on the **Outlook score** (state descriptor), not raw RSI/EMA.

We maintain two calibrations:

* **N-bin** (stable): `predBins` bins
* **1-mode** (reactive companion): could be 2 bins (sign) or 3 bins but different thresholds; simplest is to keep same bins but different smoothing/thresholds.

## B3) Required per-TF series (from the tuple)

You must have, per TF:

* `t_tf` for TF bar-change detection
* `c_tf` for return-based targets
* `h_tf` / `l_tf` for path targets
* `atr_tf` for ATR scaling
* state fields for score (ema/rsi/location)

## B4) New TF bar detection (must be global, not inside conditionals)

Compute:

```
newTfBar = ta.change(t_tf)
```

IMPORTANT: the `ta.change()` must be computed every chart bar and stored, then used in `if` blocks. Do not bury it inside `if (...) and ta.change(...)`.

---

## B5) Data layout for forecasting queues + calibration arrays

### Option I (recommended): custom type per TF

Pine v6 supports `type`. Use it to avoid duplicated code and keep logic clean.

Type design:

```
type CalTF
    string tf
    int binsN
    float alphaN
    float alpha1
    int minSamples

    int[] cntN
    int[] upN
    int[] cnt1
    int[] up1

    // pending queue fields (parallel arrays)
    float[] qScore
    int[]   qBinN
    int[]   qBin1
    float[] qEntry
    float[] qAtr
    float[] qMaxH
    float[] qMinL
    int[]   qAge

    // last seen TF time for additional safety
    int lastT
```

Constructor pattern (called once):

```
f_newCal(tf, binsN, alphaN, alpha1, minSamples) =>
    CalTF.new(tf, binsN, alphaN, alpha1, minSamples,
        array.new_int(binsN, 0), array.new_int(binsN, 0),
        array.new_int(binsN, 0), array.new_int(binsN, 0),
        array.new_float(), array.new_int(), array.new_int(),
        array.new_float(), array.new_float(),
        array.new_float(), array.new_float(),
        array.new_int(),
        na)
```

You create one instance per horizon TF (1m, 5m, 15m, 30m, 1h, 4h, 1d).

---

## B6) Core helper functions (signatures)

### Score → bin

```
f_bin(score, bins) =>
    u = (score + 1.0) * 0.5
    b = math.floor(u * bins)
    b < 0 ? 0 : b > (bins - 1) ? (bins - 1) : b
```

### Smoothing probability

```
f_prob(up, n, alpha) =>
    (up + alpha) / (n + 2.0 * alpha)
```

### Update calibration

```
f_cal_update(cntArr, upArr, bin, isUp) =>
    n = array.get(cntArr, bin) + 1
    u = array.get(upArr, bin) + (isUp ? 1 : 0)
    array.set(cntArr, bin, n)
    array.set(upArr,  bin, u)
```

### Current-bin counts/prob (for display)

```
f_cal_cur(cntArr, upArr, bin, alpha) =>
    n = array.get(cntArr, bin)
    u = array.get(upArr,  bin)
    p = n == 0 ? 0.5 : f_prob(u, n, alpha)
    [p, n]
```

### Prediction symbol & colors with sufficiency gating

Do not reference `tblText` inside these unless `tblText` is global.

```
f_predSymbolP(pUp, n, canCal, minSamples, upThr, dnThr) =>
    not canCal ? "—" : n < minSamples ? "…" : pUp > upThr ? "▲" : pUp < dnThr ? "▼" : "−"

f_predColorP(pUp, n, canCal, minSamples, upThr, dnThr, colNeutral) =>
    not canCal ? color.new(color.white, 70) :
    n < minSamples ? color.new(color.white, 60) :
    pUp > upThr ? color.lime : pUp < dnThr ? color.red : colNeutral
```

---

## B7) Queue mechanics (per TF), by target type

### Common: push “pending” on each new TF bar

When `newTfBar` is true:

* compute current `score_tf`
* compute `binN`, `bin1`
* push entry state into queue

Queue push function:

```
f_q_push(cal, score, binN, bin1, entry, atrRef) =>
    array.push(cal.qScore, score)
    array.push(cal.qBinN,  binN)
    array.push(cal.qBin1,  bin1)
    array.push(cal.qEntry, entry)
    array.push(cal.qAtr,   atrRef)
    array.push(cal.qMaxH,  entry)   // init
    array.push(cal.qMinL,  entry)   // init
    array.push(cal.qAge,   0)
```

### Each new TF bar, increment ages and update path extremes

For all pending items i:

* age := age + 1
* maxH := max(maxH, h_tf)
* minL := min(minL, l_tf)

Pine doesn’t have for-each; you loop by index from 0..size-1.

### Resolution logic per target

You resolve *old items* when they hit the necessary age.

#### Target: NextBar

Resolve items with age >= 1:

* up = c_tf > entry

#### Target: KBarReturn

Resolve items with age >= kBars:

* up = c_tf > entry  (or close_tf_now > close_tf_then)

#### Target: KBarATR

Resolve items with age >= kBars:

* retATR = (c_tf - entry) / atrRef
* up = retATR >= atrThr

#### Target: PathTPvsSL

Resolve as soon as TP or SL hit, OR on age >= pathH:

* tpPx = entry + tpATR * atrRef
* slPx = entry - slATR * atrRef
* winHit = maxH >= tpPx
* lossHit = minL <= slPx

If both hit in same bar: choose a policy (recommend conservative = treat as loss or neutral). Make this explicit.

If horizon ends without hit:

* Ignore: do nothing
* Neutral: treat as up=false but with different bucket? (binary systems don’t have neutral; easiest is “ignore”)
* Loss: up=false

### Pop and update calibration

When an item resolves:

* read stored binN/bin1
* call f_cal_update() on the appropriate arrays
* remove item from queue

Removal strategy:

* easiest: remove by index; but arrays are O(n). To keep it cheap:

  * resolve only the oldest items from the front (FIFO), so you always remove index 0
  * this is fine because you only resolve on TF closes (not every chart tick)

For PathTPvsSL, items may resolve earlier than pathH; still FIFO works if you only ever resolve from the head. If you need out-of-order resolution, you’ll need a “resolved flag” and periodic compaction. FIFO is strongly recommended for Pine simplicity.

---

# C) Enhancement 2 — Add per-timeframe sample counts in the table

## C1) What to show (best signal-to-noise)

Show the **current-bin sample counts**:

* `nCur(N)` and `nCur(1)` alongside probabilities

This answers: “How much evidence supports this probability right now?”

## C2) How to render without adding columns

Keep the 5 columns and format PUp as:

* “62% n84”  (compact, reliable)
  or
* “62% (n=84)” (more readable, wider)

Implementation:

```
f_pupText(p, n, canCal, minSamples) =>
    not canCal ? "n0" :
    n < minSamples ? ("n" + str.tostring(n)) :
    (str.tostring(p * 100.0, "#.0") + "% n" + str.tostring(n))
```

Then in the table:

* PUp(N) cell uses `f_pupText(pN, nN, canCalN, calMinSamples)`
* PUp(1) cell uses `f_pupText(p1, n1, canCal1, calMinSamples)`

---

# D) Enhancement 3 — Per-timeframe calibration reset (instead of global)

## D1) Inputs (clean UI)

```
resetWhich = input.string("None", "Reset calibration (scope)",
options=["None", "All", "1M", "5M", "15M", "30M", "1H", "4H", "1D"])
resetNow = input.bool(false, "Reset selected calibration now")
```

## D2) Rising-edge detection

```
var bool prevResetNow = false

doReset = resetNow and not prevResetNow
prevResetNow := resetNow
```

Only reset when `doReset` is true.

## D3) Reset function (per CalTF)

```
f_resetCal(cal) =>
    // Clear calibration arrays
    for i = 0 to (cal.binsN - 1)
        array.set(cal.cntN, i, 0)
        array.set(cal.upN,  i, 0)
        array.set(cal.cnt1, i, 0)
        array.set(cal.up1,  i, 0)
    // Clear pending queues
    array.clear(cal.qScore)
    array.clear(cal.qBinN)
    array.clear(cal.qBin1)
    array.clear(cal.qEntry)
    array.clear(cal.qAtr)
    array.clear(cal.qMaxH)
    array.clear(cal.qMinL)
    array.clear(cal.qAge)
```

Reset dispatch:

```
if doReset
    if resetWhich == "All" or resetWhich == cal.tfLabel
        f_resetCal(cal)
```

Note: `cal.tfLabel` can be your `f_tfLabel(tf)` result or just hard-coded mapping.

---

# E) End-to-end flow (per TF) — what runs each chart bar

For each TF row you will execute:

1. Fetch tuple via 1 `request.security`

2. Compute `newTfBar = ta.change(t_tf)` (global var)

3. Compute Outlook state score + bin(s)

4. If `newTfBar`:

   * push pending item (score, bins, entry, atrRef)
   * update existing pending ages/extremes
   * resolve matured items for chosen target, update calibrations

5. Compute display:

   * Outlook: score, symbol, components
   * Forecast:

     * current-bin n/p for N and 1
     * sufficiency gating
     * Pred symbols/colors
     * PUp text including n

6. Render table at bar-close (recommended):
   if showTable and barstate.isconfirmed
   table.clear(...)
   write all cells

---

# F) Table changes needed (minimal + transparent)

## F1) Keep 5 forecast columns

TF | Pred(N) | Pred(1) | PUp(N) | PUp(1)

## F2) Add a footer row describing the target

Example footer text:

* “Target: KBarATR k=3 thr=0.25ATR”
* “Target: PathTPvsSL H=6 TP=0.5ATR SL=0.3ATR NoHit=Ignore”
  This prevents semantic confusion.

## F3) Add sample sufficiency cues

Already supported by:

* Pred shows “…” when `n < calMinSamples`
* PUp shows “nX” even before full probability display

---

# G) Recommended implementation order (so you don’t get stuck)

1. Implement **per-TF sample counts in table** (quick win, zero impact on logic)
2. Implement **per-TF reset** (safe; only touches arrays)
3. Implement alternate targets:

   * start with **KBarReturn** (queue + maturity)
   * then **KBarATR** (same queue, just adds atrRef)
   * then **PathTPvsSL** (adds max/min tracking and policy rules)

---

# H) “Done” criteria + quick validation plan (TradingView Replay)

## H1) Correctness checks

* Forecast counts only increase on TF bar closes (`newTfBar`)
* Outcomes only recorded when matured (age >= k or resolved path)
* No repainting (lookahead_off everywhere)
* No Pine warnings about conditional `ta.change()`

## H2) UI checks

* Table updates on `barstate.isconfirmed` (stable)
* Forecast rows show `…` until `n >= calMinSamples`
* PUp cells display `n` values always (even early)

## H3) Reset checks

* Reset “5M” only zeroes 5m arrays and pending queue
* Other TFs retain calibration

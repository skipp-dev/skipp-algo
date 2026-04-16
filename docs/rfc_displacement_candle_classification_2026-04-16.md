# RFC: Displacement Candle Classification for SMC Context Quality

Stand: 2026-04-16  
Branch: `main`  
Status: **Not yet** — shadow evaluation required before promotion  
Feature-Freeze: Active (15.04.–15.05.2026) — this RFC is analysis only

---

## Purpose

Evaluate whether an explicit displacement-candle classification improves
the quality of already-existing SMC contexts (OB, FVG, Sweep, Reclaim,
BOS/CHoCH) without distorting the product model.

**Core question:** "Verbessert eine explizite Displacement-Klassifikation
die Qualität von bereits bestehenden SMC-Kontexten, ohne das Produktmodell
zu verzerren?"

**This RFC does NOT propose:**
- a new primary signal
- a new entry trigger
- any code changes
- any dashboard surface changes

---

## 1. Current SMC Baseline

The system already handles candle-strength in five distinct places, each
with a different threshold and purpose. These have grown independently
and do not share a common definition.

### 1.1 Explicit classifications in SMC Core Engine

| Concept | Location | Threshold | Purpose |
|---------|----------|-----------|---------|
| `is_impulse_candle` | Core Engine L391–413 | body ≥ 3× ATR(200) | OB quality bonus (+0.15), soft-confirm bypass |
| `is_indecision` | Profile Engine L354 | inside-bar + smaller body, or doji | OB extension guard (opposite pole) |
| `big_candle` | Core Engine `detect_structure()` L777 | body > 2× distance-to-level OR body > ATR(3) | BOS/CHoCH significance filter |
| `has_big_candle` | OB field (Core Engine L70) | inherited from `is_impulse_candle` during extending | OB quality score component |

### 1.2 Displacement in standalone scripts (not in SMC Core)

| Script | Threshold | Components | Notes |
|--------|-----------|------------|-------|
| REV-Ladder L214–226 | body ≥ 0.6× ATR + close-near-high (wick ≤ 25% range) + volume ≥ 1.4× | body + wick + volume | Most complete model; bullish only; standalone |
| CHOCH-Base L287 | body > 0.20–0.35× ATR(14) | body only | Entry filter, not quality gate |
| QuickALGO L3727 | body > 0.7× ATR | body only | Rescue impulse filter |
| USI_Strategy L254 | body > ATR × mult | body only | Counter-trend exit signal |

### 1.3 Regime-level context (not per-candle)

| Source | Field | Level |
|--------|-------|-------|
| HTF Confluence | ATR_REGIME | COMPRESSION / NORMAL / EXPANSION / EXHAUSTION |
| Micro Profiles | SESS_IMPULSE_DIR/STRENGTH | Session-level (currently defaults to NONE/0) |
| Bus Private | `vol_expansion_state` | Regime-level momentum |

### 1.4 What is NOT in the system

1. **No unified per-candle displacement grade** — no function that
   combines body-to-ATR + wick quality + close position into a single
   classification available to the Core Engine.
2. **No displacement qualifier on BOS/CHoCH** — the `big_candle` filter
   in `detect_structure()` is a crude significance gate, not a
   displacement assessment.
3. **No displacement field on the BUS** — companions cannot observe
   "this structural break was backed by displacement".
4. **No displacement grading** — everything is binary (impulse or not).
5. **Threshold gap**: Core Engine uses 3× ATR(200), which is an
   extremely high bar (≈ massive event). REV-Ladder uses 0.6× ATR.
   CHOCH-Base uses 0.2–0.35× ATR. These are effectively three different
   concepts sharing the word "impulse".

---

## 2. Candidate Displacement Definitions

### Definition A: Body-Dominant (simplest)

```
displacement = body ≥ K × ATR(N)
```

- **K**: 0.5–0.8 (much lower than current 3.0, much higher than 0.2)
- **N**: ATR(14) or ATR(50) — shorter than current ATR(200)

**Pro:** Simple, single parameter, already partially implemented.  
**Con:** No wick quality — a long-wick doji with large range passes.
No volume confirmation. Noise-susceptible on small timeframes.  
**Overfit risk:** Medium — threshold K is regime-dependent.  
**Inputs available in Core Engine:** Yes — `candle_body` and `atr` are
already computed.

### Definition B: Body-Dominant + Close-Near-Extreme (recommended)

```
displacement_bull = close > open
                    AND body ≥ K × ATR(N)
                    AND (high - close) ≤ F × range
displacement_bear = close < open
                    AND body ≥ K × ATR(N)
                    AND (close - low) ≤ F × range
```

- **K**: 0.5–0.7
- **F**: 0.20–0.30 (close within top/bottom 20–30% of range)
- **N**: ATR(14) or ATR(50)

**Pro:** Captures the canonical ICT/SMC displacement definition:
strong body + close near extreme = institutional conviction, not just
volatility. Already implemented in REV-Ladder (K=0.6, F=0.25).
Rejects wick-heavy candles that look big but didn't close with
conviction.  
**Con:** Two parameters instead of one.  
**Overfit risk:** Low-to-medium — the close-position check is
structurally motivated, not curve-fitted.  
**Inputs available in Core Engine:** Yes — `open`, `close`, `high`,
`low`, `candle_body`, `atr` are all computed.

### Definition C: Body + Close + Volume (fullest)

```
Definition B + volume ≥ V × volume_sma(M)
```

- **V**: 1.2–1.5
- **M**: 20-bar SMA

**Pro:** Volume adds institutional footprint confirmation.  
**Con:** Volume data quality varies by symbol and exchange. Adds a
third threshold parameter. Volume is already captured separately in the
Orderflow Overlay (`ATS`, `FLOW_DIRECTION`, `REL_VOL`), so combining
at the candle level risks double-counting in quality scores.  
**Overfit risk:** Higher — three parameters increase calibration
surface.  
**Inputs available in Core Engine:** Partially — volume is available
but not currently SMA-smoothed in the candle classification path.

### Preferred definition: B (Body + Close-Near-Extreme)

**Rationale:**
- Matches the canonical displacement concept from ICT/SMC literature
- Already proven in REV-Ladder with stable parameters
- Two-parameter surface is manageable for shadow evaluation
- Volume can be overlaid later from the Orderflow bus field without
  coupling it into the base classification

---

## 3. Mapping to SMC Application Contexts

### 3.1 OB Quality Enhancement

**Current state:** `ob_quality_score()` gives +0.15 for `has_big_candle`
(body ≥ 3× ATR(200)). This is effectively dead for most OBs — 3× ATR is
hit only on extreme event candles (earnings, FOMC).

**Potential value:** Replace or supplement `has_big_candle` with a
displacement classification (Definition B, K=0.6). An OB created by a
displacement candle reflects institutional commitment — the breakout from
the block was backed by conviction, not just random drift.

**Potential harm:** If threshold is too low, most OBs get the bonus and
it becomes meaningless. If it's the only quality driver, it could
overweight candle size vs. structural context.

**Governance risk:** Low — the +0.15 component already exists; changing
its sensitivity is a quality-score recalibration, not a new signal.

### 3.2 FVG Relevance

**Current state:** FVGs are detected by `low - high[2] > fvg_min_size`
(0.2× ATR). No assessment of what caused the gap.

**Potential value:** Moderate — a displacement-backed FVG has higher
fill probability and stronger institutional context than a gap caused
by low-volume drift.

**Potential harm:** FVGs are already high-frequency. Adding a quality
tier risks making the system more complex without clear Brier
improvement.

**Governance risk:** Medium — FVG count/quality changes would alter
zone density on charts.

### 3.3 Sweep-Reclaim Confirmation

**Current state:** Sweeps are detected by price exceeding a prior level
and then returning. No assessment of the reclaim candle's strength.

**Potential value:** High — a liquidity sweep followed by a displacement
candle in the reclaim direction is the canonical SMC "smart money
reversal" pattern. REV-Ladder already implements this exact filter
(`dispOk` + `reclaimLow`), confirming the pattern has operational value.

**Potential harm:** Low — this is a qualifier on an existing event, not
a new trigger.

**Governance risk:** Low — additive quality information.

### 3.4 BOS/CHoCH Quality

**Current state:** `detect_structure()` uses a crude `big_candle` gate
(body > 2× distance-to-level OR body > ATR(3)) to filter insignificant
breaks. This is a significance filter, not a displacement classifier.

**Potential value:** Moderate — a BOS backed by displacement is more
likely a genuine structural break vs. a thin-wick cross. Could reduce
false BOS noise on lower timeframes.

**Potential harm:** Risk of over-filtering — some genuine CHoCHs happen
on moderate candles after absorption. A strict displacement requirement
on structure breaks would be too aggressive.

**Governance risk:** High — this changes structure detection sensitivity,
which is a core product surface. Would need extensive shadow validation.

### 3.5 Summary

| Context | Potential value | Potential harm | Governance risk | Recommendation |
|---------|----------------|----------------|-----------------|----------------|
| OB Quality | High | Low | Low | Shadow-evaluate first |
| FVG Relevance | Moderate | Medium | Medium | Defer — FVG density changes are risky |
| Sweep-Reclaim | High | Low | Low | Shadow-evaluate first |
| BOS/CHoCH Quality | Moderate | Medium-High | High | Not yet — too close to structure core |

---

## 4. Non-Goals

These are explicitly excluded from any future displacement work:

1. **Displacement as standalone entry trigger** — displacement is a
   context qualifier, not a signal. "Strong candle = buy" is exactly
   the heuristic shortcut this RFC rejects.
2. **Displacement as CHoCH replacement** — structural breaks are defined
   by swing structure, not by candle body size. A displacement candle
   without a structural break is noise.
3. **"Earlier entry" because of a strong candle** — the system's
   touch-then-confirm flow exists for a reason. Displacement may
   accelerate soft-confirmation (already does via `big_candle_override`),
   but it must not bypass structure.
4. **Pre-CHoCH feature bundle** — combining displacement + volume + FVG
   into a compound "pre-signal" would be a feature-bundling anti-pattern.
5. **Displacement grading (weak/moderate/strong)** — binary
   classification first. Grading adds calibration complexity without
   proven benefit.

---

## 5. Risks

### 5.1 Real risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Threshold is regime-dependent (0.6× ATR works in normal vol, fails in compression/exhaustion) | Medium | ATR regime guard: only classify displacement in NORMAL/EXPANSION regime |
| Adding a quality factor inflates quality scores, making "good enough" OBs look better than they are | Medium | Normalize: if displacement replaces `has_big_candle`, total score ceiling stays at 1.0 |
| Shadow evaluation requires event labeling that doesn't exist yet | Low | SESS_IMPULSE_DIR/STRENGTH fields exist in micro-profiles; displacement flag can shadow-log alongside |
| Feature freeze violation | Low | RFC is analysis only; implementation blocked until freeze ends |

### 5.2 Imagined risks (not real)

| Risk | Why it's not real |
|------|-------------------|
| "Displacement adds a new signal type" | No — it qualifies existing events. `has_big_candle` already exists; this is a better definition of the same concept. |
| "Two parameters are too many to calibrate" | The system already calibrates ATR period (200, 14, 3, 50), OB size bounds, FVG min size, soft-confirm offset, etc. Two parameters (K, F) are within normal budget. |
| "Volume must be included or it's incomplete" | Volume is already separated into the Orderflow Overlay layer. Mixing it into candle classification would violate the bus separation principle. |

---

## 6. Shadow Evaluation Design

### 6.1 Required label/flag

A single boolean field per bar, computed but not surfaced:

```
shadow_displacement_bull: bool  // close > open, body ≥ K×ATR, wick ≤ F×range
shadow_displacement_bear: bool  // close < open, body ≥ K×ATR, wick ≤ F×range
```

Initial parameters: K=0.6, F=0.25 (matching REV-Ladder's proven values).

### 6.2 Contexts to observe

The shadow flag should be logged alongside these existing events:

| Event | Question |
|-------|----------|
| OB confirmation | Was the confirming bar a displacement candle? |
| OB extension | Was any extending bar a displacement candle? |
| BOS trigger | Was the break candle a displacement candle? |
| CHoCH trigger | Was the break candle a displacement candle? |
| Sweep + Reclaim | Was the reclaim candle a displacement candle? |
| FVG creation | Was the gap-creating candle a displacement candle? |

### 6.3 Metrics to run against

| Metric | Purpose |
|--------|---------|
| `hit_rate` stratified by displacement | Do displacement-backed events have higher hit rates? |
| `time_to_mitigation` stratified by displacement | Do they resolve faster? |
| `mae` (Mean Adverse Excursion) | Do they produce less adverse movement? |
| `invalidation_rate` | Do they get broken less often? |
| Brier score impact | Does adding displacement as a quality factor improve or degrade calibration? |
| ECE impact | Does it shift expected calibration error? |

### 6.4 Decision criteria

| Criterion | Threshold | Consequence |
|-----------|-----------|-------------|
| Displacement-backed OBs have ≥ 5pp higher hit rate | Measured over ≥ 200 events | Proceed to OB quality integration |
| Displacement-backed sweeps have ≥ 3pp lower invalidation rate | Measured over ≥ 100 events | Proceed to sweep-reclaim integration |
| Brier score does not regress > 0.03 | Compared to current non-displacement baseline | Hard gate — regression = abort |
| ECE does not increase > 0.05 | Same | Hard gate — regression = abort |
| Displacement flag fires on 15–40% of relevant candles | If < 15%: too rare to matter; if > 40%: no discriminative value | Adjust K/F thresholds or abort |

### 6.5 Implementation path (not in scope of this RFC)

1. Add `shadow_displacement_bull/bear` computation in Python benchmark
   pipeline (not in Pine)
2. Stratify existing benchmark KPIs by displacement flag
3. Run ≥ 3 CI cycles with shadow logging
4. Compare stratified vs. unstratified metrics
5. If criteria met → promote to OB quality score (replacing
   `has_big_candle` +0.15 with displacement-aware +0.15)
6. If criteria not met → close RFC as "evaluated, not adopted"

---

## 7. Recommendation: Not Yet

### Rationale

1. **The concept is sound.** Displacement is a well-defined institutional
   trading concept. The system already uses a crude version
   (`is_impulse_candle` at 3× ATR(200)) that is too extreme to be
   useful for most OBs. REV-Ladder proves that a more calibrated
   definition (0.6× ATR + close-near-high) works in practice.

2. **The infrastructure gap is small.** The inputs exist
   (`candle_body`, `atr`, `open`, `close`, `high`, `low`). The bus
   field slot exists conceptually. The measurement lane already supports
   stratified KPIs.

3. **But the shadow evidence doesn't exist yet.** The decision criteria
   in §6.4 cannot be evaluated today. The benchmark pipeline does not
   yet log displacement context alongside events. Without measurement,
   adopting displacement is narrative-driven, which this system's
   governance model explicitly rejects.

4. **Feature freeze is active.** Even if evidence existed, implementation
   is blocked until 2026-05-15.

### Decision

| Option | Verdict |
|--------|---------|
| **Go** (implement now) | No — no shadow evidence, feature freeze active |
| **No-Go** (reject permanently) | No — the concept has clear theoretical merit and a proven standalone implementation |
| **Not yet** (pending shadow evaluation) | **Yes** — implement shadow logging in next post-freeze cycle, evaluate against §6.4 criteria, then decide |

### Concrete next steps (post-freeze)

1. Add `shadow_displacement_bull/bear` to Python benchmark event logging
2. Run ≥ 5 CI measurement cycles with shadow data
3. Evaluate §6.4 criteria
4. If positive → RFC addendum with promotion plan
5. If negative → close this RFC as "evaluated, not adopted"

---

## Appendix: Existing Threshold Inventory

For reference, the full landscape of body-size thresholds in the codebase:

| Script | Threshold | ATR Period | Purpose | In SMC Core? |
|--------|-----------|------------|---------|--------------|
| SMC Core Engine | 3.0× | ATR(200) | Impulse candle (OB quality) | Yes |
| SMC Core Engine | 1.0× / 2× dist | ATR(3) | Structure break filter | Yes |
| REV-Ladder | 0.6× | ATR(14) | Displacement (full model) | No |
| CHOCH-Base | 0.20–0.35× | ATR(14) | Entry impulse gate | No |
| QuickALGO | 0.7× | ATR(?) | Rescue impulse | No |
| USI_Strategy | configurable | ATR(exit) | Counter-trend exit | No |

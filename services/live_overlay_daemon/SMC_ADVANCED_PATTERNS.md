# SMC Advanced Patterns: HVB, PPDD, Liquidity, Broken Fractal

**Date:** 2026-07-03  
**Status:** ✅ IMPLEMENTED (12 tests passing)  
**Based on:** makuchaku "Super OrderBlock / FVG / BoS Tools" analysis  

---

## Executive Summary

Implemented 4 advanced Smart Money Concepts (SMC) patterns inspired by makuchaku's professional-grade TradingView toolkit:

| Pattern | Purpose | Integration | Tests |
|---------|---------|-------------|-------|
| **HVB** | Signal quality confirmation | SmcSignalDetector | ✅ 2/2 |
| **PPDD** | Entry bias classification | SmcBoxManager | ✅ 4/4 |
| **Liquidity Clusters** | Confluence detection | Spatial analysis | ✅ 2/2 |
| **Broken Fractal** | Multi-level structure validation | Real-time pattern recognition | ✅ 2/2 |

---

## 1. HIGH VOLUME BAR (HVB)

### Concept

**HVB** = A candle with abnormally high volume (typically >1.5x rolling average).

**Market Implication:**
- High volume at resistance = **Smart Money distribution** (selling pressure)
- High volume at support = **Smart Money accumulation** (buying pressure)
- HVB at OB/FVG formation = **Increased pattern confidence**

### makuchaku's Approach

```
// Super OrderBlock Tool includes HVB detection
- Marks bars with volume > avg_volume × threshold
- Colored differently (brighter) for visual prominence
- Confidence factor: signals at HVB zones are stronger
```

### skipp-algo Implementation

```python
hvb_detector = HVBDetector(lookback=20, hvb_threshold=1.5)
hvb = hvb_detector.detect(
    bar_index=t.bar_index,
    volume=t.volume,
    close=t.close,
    open=t.open,
    high=t.high,
    low=t.low,
)

if hvb.is_hvb:
    signal_strength *= 1.5  # Boost signal strength
    logger.debug(f"HVB at {t.bar_index}: {hvb.volume_ratio:.2f}x avg")
```

### Best-Practices Comparison

| Aspect | makuchaku | skipp-algo |
|--------|-----------|-----------|
| **Volume Lookback** | Configurable (default: 20) | 20 (tunable) |
| **HVB Threshold** | 1.5-2.0x average | 1.5x (standard) |
| **Application** | Visual marker + confirmation | Signal quality multiplier |
| **Risk Mitigation** | Yes (high volume = increased risk) | Yes (tracked) |

---

## 2. PREMIUM / DISCOUNT ORDERBLOCK (PPDD)

### Concept

**Premium** = OB formed in resistance zone (above current price)  
**Discount** = OB formed in support zone (below current price)

**Trading Logic:**
- Discount OBs are more likely to be "swept" → better entries
- Premium OBs represent "old resistance" → stronger psychological zones
- PPDD bias should align with timeframe hierarchy (HTF bias → LTF entries)

### makuchaku's Approach

```
// PPDD classification in Super OrderBlock Tool
if OB_center > current_price:
    OB_type = "Premium" (resistance zone)
    confidence = high (established zone)
else:
    OB_type = "Discount" (support zone)  
    confidence = medium (emerging zone, but more liquid)
```

### skipp-algo Implementation

```python
ppdd_classifier = PPDDClassifier(atr_multiple=2.0)
ob = ppdd_classifier.classify(
    ob_top=110,
    ob_bottom=105,
    direction="bullish",
    current_price=100,
    atr=5,
    hvb_present=True,  # Optional HVB confirmation
)

# ob.bias() → "premium" | "discount" | "neutral"
# ob.strength → 0.0-1.0 (0 = far away, 1.0 = very close)
```

### Best-Practices Comparison

| Aspect | makuchaku | skipp-algo |
|--------|-----------|-----------|
| **Premium Definition** | OB above price | OB center > current_price |
| **Discount Definition** | OB below price | OB center < current_price |
| **Strength Calculation** | Visual distance | ATR-normalized distance |
| **HVB Integration** | Optional marker | Confidence multiplier |

---

## 3. LIQUIDITY CLUSTERS

### Concept

**Liquidity Cluster** = Zone where multiple swing highs/lows congregate.

**Market Implication:**
- Clusters = where **stop-losses and limit orders accumulate**
- When price reaches cluster → likely sweep or rejection
- Multiple confluences = stronger zone

### makuchaku's Approach

```
// Liquidity Visualizer logic
1. Identify all swing highs in lookback window
2. Identify all swing lows
3. Group nearby levels (within ATR distance)
4. Mark zones with 2+ confluences
5. Color by proximity to current price
```

### skipp-algo Implementation

```python
liquidity_detector = LiquidityClusterDetector(
    cluster_distance_atr=0.5,  # Group within 0.5 ATR
    min_confluences=2,         # Require 2+ levels
)

clusters = liquidity_detector.detect_clusters(
    swing_highs=[110.0, 110.5, 109.8],
    swing_lows=[90.0, 89.5, 90.2],
    current_price=100.0,
    atr=5.0,
)

for cluster in clusters:
    # cluster.zone_top / zone_bottom
    # cluster.risk_level → "high" (close) | "medium" | "low"
    # cluster.direction_bias → "bullish" | "bearish" | "neutral"
    pass
```

### Best-Practices Comparison

| Aspect | makuchaku | skipp-algo |
|--------|-----------|-----------|
| **Cluster Distance** | 0.5 ATR (default) | 0.5 ATR |
| **Confluence Count** | 2+ | 2+ |
| **Visualization** | Colors by proximity | Risk level + bias |
| **Use Case** | Entry zone identification | Confluence scoring |

---

## 4. BROKEN FRACTAL

### Concept

**Fractal** = 3-candle extremity pattern (high/low with lower/higher neighbors)  
**Broken Fractal** = When initial fractal is breached + opposite fractal forms + original breaks

**Pattern:**
```
1. Initial fractal (e.g., HIGH with lower neighbors)
2. Opposite fractal forms (LOW with higher neighbors)
3. Initial fractal breaks (price > initial HIGH)
4. Trapped traders at initial fractal exit → liquidity sweep
```

### makuchaku's Approach

```
// Broken Fractal logic
Initial_Fractal_High = 110
Opposite_Fractal_Low = 90
If price > Initial_Fractal_High:
    → Trapped bears exit
    → Strong directional move expected
    → Entry box: [Initial_High, Break_High]
```

### skipp-algo Implementation

```python
fractal_detector = BrokenFractalDetector()

bf = fractal_detector.detect(
    bar_index=t.bar_index,
    high=t.high,
    low=t.low,
    close=t.close,
)

if bf and bf.confirmed:
    # bf.break_direction → "up" | "down"
    # bf.entry_box_top / entry_box_bottom → entry zone
    # bf.trapped_traders_escape → follow-up confirmation
    entry_zone = (bf.entry_box_top, bf.entry_box_bottom)
```

### Best-Practices Comparison

| Aspect | makuchaku | skipp-algo |
|--------|-----------|-----------|
| **Fractal Definition** | 3-candle pattern | Tracked in history |
| **Confirmation** | Close beyond break | Close verification |
| **Entry Zone** | Visual box | entry_box_top/bottom |
| **Trapped Trader Logic** | Implicit (visual) | tracked as boolean |

---

## Integration with SmcSignalDetector

### Workflow

```
process_candle(t):
  1. Core patterns (OB, FVG, RJB)
  2. Advanced patterns:
     a. HVB detection → boost signal strength if present
     b. Broken Fractal → validate with nested structure
     c. Liquidity clusters → confluence scoring
     d. PPDD classification → entry bias
  3. Emit signals with enhanced metadata
```

### Example: Signal Enhancement

```python
# Before: Simple OB signal
signal = SmcSignalDetector.detect_order_blocks(...)

# After: Enhanced with advanced patterns
hvb_present = hvb.is_hvb
ppdd = ppdd_classifier.classify(ob.top, ob.bottom, direction, price, atr)
clusters = liquidity_detector.detect_clusters(highs, lows, price, atr)
bf = fractal_detector.detect(...)

signal_strength = 1.0
if hvb_present:
    signal_strength *= 1.5  # HVB confirmation
if ppdd.strength > 0.7:
    signal_strength *= 1.2  # Good PPDD bias
if clusters:
    signal_strength *= 1.1  # Liquidity confluence

logger.info(f"Enhanced signal: {signal_strength:.2f}x multiplier")
```

---

## Test Coverage

```
tests/test_smc_advanced_patterns.py
├── TestHVBDetector (2 tests) ✅
│   ├── test_hvb_detection_above_threshold
│   └── test_hvb_detection_below_threshold
├── TestPPDDClassifier (4 tests) ✅
│   ├── test_bullish_ob_premium
│   ├── test_bullish_ob_discount
│   ├── test_bearish_ob_premium
│   └── test_hvb_confirmation_strength
├── TestLiquidityClusterDetector (2 tests) ✅
│   ├── test_cluster_detection_from_highs
│   └── test_cluster_risk_classification
├── TestBrokenFractalDetector (2 tests) ✅
│   ├── test_fractal_break_detection_up
│   └── test_fractal_break_confirmation
└── TestLiquidityCluster (2 tests) ✅
    ├── test_contains_price
    └── test_zone_width

Total: 12/12 tests PASSING ✅
```

---

## Calibration Parameters

### HVB Detector

```python
hvb_detector = HVBDetector(
    lookback=20,      # Candles to average volume (default 20)
    hvb_threshold=1.5 # Multiplier for "high volume" (default 1.5x)
)
# Tuning: Increase threshold for less sensitive, decrease for more
```

### PPDD Classifier

```python
ppdd_classifier = PPDDClassifier(
    atr_multiple=2.0  # How many ATR = full strength (default 2.0)
)
# Tuning: Increase to require zones further away for full strength
```

### Liquidity Detector

```python
liquidity_detector = LiquidityClusterDetector(
    cluster_distance_atr=0.5,  # Group within this ATR distance
    min_confluences=2,         # Minimum highs/lows to form cluster
)
# Tuning: Decrease distance to be more selective, increase confluences for stricter zones
```

---

## Next Steps

1. **Integrate into SmcSignalDetector.process_candle()** ✅ Done
2. **Wire into live_signals.py for webhook routing**
3. **Dashboard visualization** (show HVB, PPDD bias, clusters)
4. **A/B testing** (compare signals with/without advanced patterns)
5. **Hyperparameter optimization** (find best lookback/threshold values)

---

## References

- **makuchaku profile:** https://de.tradingview.com/u/makuchaku/#published-scripts
- **Super OrderBlock/FVG/BoS Tools:** https://de.tradingview.com/script/aZACDmTC-Super-OrderBlock-FVG-BoS-Tools-by-makuchaku-eFe/
- **Liquidity Visualizer:** https://de.tradingview.com/script/Rixvcq0y-Makuchaku-s-trading-tools-Liquidity-visualizer/
- **Broken Fractal:** https://de.tradingview.com/script/BYHsrYPG-Broken-Fractal-Someone-s-broken-dream-is-your-profit/

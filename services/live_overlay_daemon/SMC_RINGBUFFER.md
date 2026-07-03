# SMC RingBuffer & Signal Detection Pattern

Optimized O(1) replacement for TradingView's array-based technical analysis pattern.
Replaces the `array.shift()` O(n) antipattern with `collections.deque(maxlen=n)` for O(1) bounded event streaming.

## Architecture

### Three-Layer Stack

```
SmcSignalDetector (orchestrator)
  ↓
SmcBoxManager (state manager)
  ↓
RingBuffer[T] (data structure)
```

### Key Differences from TradingView Script

| Aspect | TradingView Pine | Python (skipp-algo) |
|--------|------------------|---------------------|
| **Eviction** | `array.shift()` → O(n) | `deque(maxlen=n)` → O(1) |
| **Direction Separation** | 4 separate arrays (bullish/bearish × type) | Unified `SmcBoxManager` with routed buffers |
| **Mitigation** | Direct color change | Tracked state + event emission |
| **Pattern Detection** | Predicate per type | Unified `SmcSignalDetector` with candle history |
| **Memory** | Bounded by `max_boxes_count` | Guaranteed by `max_boxes_per_direction` |

---

## Components

### 1. RingBuffer[T]

Generic circular buffer backed by `deque`.

```python
buf = RingBuffer[SmcBox](max_size=10)
box = make_ob_up(...)
evicted = buf.append(box)  # O(1)

# Access
buf.get(0)         # Oldest
buf.get_latest()   # Newest
for item in buf:   # Iteration oldest→newest
    ...
```

**Guarantees:**
- O(1) append
- O(1) access by index
- O(1) full-eviction (oldest item auto-deleted)
- Memory-safe: max_size never exceeded

---

### 2. SmcBox

Core data structure for technical analysis zones.

```python
box = SmcBox(
    left=10, right=15,
    top=100.0, bottom=95.0,
    box_type=BoxType.ORDER_BLOCK,
    direction=Direction.BULLISH,
    created_at=10,
    color="#00FF00",
    strength=1.0,  # Confidence 0.0-1.0 (RJB uses 0.6)
)

# Check breach
if box.is_breached(high=101.0, low=99.0):
    box.is_mitigated = True
    box.mitigated_at = current_bar

# Advance time
box.update_right(20)  # Extend right edge
```

**Breach Detection Guards:**
- NaN-safe (returns False on NaN input)
- Bidirectional (checks both top and bottom pierces)
- State-aware (only mitigates once)

---

### 3. SmcBoxManager

Unified manager for all boxes with direction routing.

```python
mgr = SmcBoxManager(max_boxes_per_direction=10)

# Add box (routed by direction)
box = make_ob_up(...)
evicted = mgr.add_box(box)  # → bullish_boxes buffer

# Check mitigation
mgr.check_mitigation(high=101.0, low=99.0, current_bar=20)

# Advance time
mgr.extend_right_edges(current_bar=20)

# Query
active = mgr.get_active_boxes()          # Unmitigated only
obs = mgr.get_boxes_by_type(BoxType.OB)  # Filter by type
count = mgr.count_active(Direction.BULLISH)
```

**O(n) Operations** (where n = max_boxes_per_direction):
- `check_mitigation()`: scan all boxes for breach
- `get_boxes_by_type()`: filter scan
- `get_active_boxes()`: filter scan

---

### 4. SmcSignalDetector

Real-time streaming detector.

```python
detector = SmcSignalDetector(max_boxes_per_direction=10)

for candle in market_stream:
    signals = detector.process_candle(candle)
    for sig in signals:
        webhook.post({
            "bar_index": sig.bar_index,
            "type": sig.box_type.value,     # "OB" | "FVG" | "RJB" | "BoS"
            "direction": sig.direction.value, # "+" | "-"
            "event": sig.event_type,         # "created" | "mitigated"
            "box": asdict(sig.box),
        })
```

**Detection on Each Candle:**
1. Extend all box right edges
2. Scan for breaches (mitigation events)
3. Detect new patterns (if 3+ candles in history):
   - Order Blocks (OB+, OB-)
   - Fair Value Gaps (FVG+, FVG-)
   - Rejection Blocks (RJB+, RJB-)

**Pattern Predicates** (with NaN guards):
- `is_ob_up(close_t, open_t, close_t1, open_t1, high_t1, high_t2, low_t2)`
- `is_ob_down(...)`
- `is_fvg_up(low_t, high_t2)`
- `is_fvg_down(high_t, low_t2)`
- `is_rjb_down(high_t1, close_t2, high_t2, threshold=0.2)`
- `is_rjb_up(low_t1, close_t2, low_t2, threshold=0.2)`

---

## Performance

### Time Complexity per Candle

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Add box | O(1) | `deque.append()` |
| Check mitigation | O(n) | Scan all boxes; n=20 for 10+10 |
| Extend edges | O(n) | Loop all boxes |
| Pattern detect | O(1) | Predicate evaluation |
| **Total per candle** | **O(n)** | n=20 (typical); negligible at <100µs |

### Memory

Fixed bounded allocation:
- 10 bullish + 10 bearish = 20 boxes
- Per box: ~300 bytes (dataclass overhead)
- **Total: ~6 KB** (vs. TradingView's unlimited arrays)

---

## Integration with skipp-algo

### 1. Live Overlay Daemon (realtime_signals.py)

```python
from services.live_overlay_daemon.smc_signal_detector import (
    SmcSignalDetector,
    Candle,
)
import open_prep.realtime_signals as rs

class RealTimeSignalProducer:
    def __init__(self):
        self.smc = SmcSignalDetector(max_boxes_per_direction=10)
    
    def on_bar_close(self, bar: rs.Bar):
        candle = Candle(
            bar_index=bar.bar_number,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=int(bar.volume),
        )
        
        signals = self.smc.process_candle(candle)
        
        # Route to signal handlers
        for sig in signals:
            if sig.event_type == "created":
                self._route_new_structure(sig)
            elif sig.event_type == "mitigated":
                self._route_mitigation(sig)
    
    def _route_new_structure(self, sig):
        # Bullish OB → bullish bias signal
        # Stacked OB+FVG → strong momentum signal
        # etc.
        pass
```

### 2. SMC Pine Library (smc_smarter_trading.pine)

Replicate pattern detection in Pine, but use RingBuffer for state tracking:

```pine
//@version=5
// SMC pattern detection (already has predicates)
// Integrate Python output via webhook for backtesting

export f_is_ob_up(...) => ... // Already in smc_*.pine libraries
```

Then call from Python:
```python
from services.live_overlay_daemon.smc_ringbuffer import is_ob_up
# Use same predicate logic for consistency
```

### 3. Backtesting Pipeline

```python
from services.live_overlay_daemon.smc_signal_detector import SmcSignalDetector, Candle

def backtest_smc_signals(bars: list[Bar]) -> list[SignalEvent]:
    detector = SmcSignalDetector(max_boxes_per_direction=10)
    all_signals = []
    
    for bar in bars:
        candle = Candle(
            bar_index=bar.bar_index,
            open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=bar.volume,
        )
        signals = detector.process_candle(candle)
        all_signals.extend(signals)
    
    return all_signals
```

---

## Testing

### Run Tests

```bash
# Unit tests for RingBuffer and SmcBox
pytest tests/test_smc_ringbuffer.py -v

# Integration tests for SmcSignalDetector
pytest tests/test_smc_signal_detector.py -v

# All SMC tests
pytest tests/test_smc*.py -v
```

### Test Ledger

Frozen line-number pins (ADR-0009):
- `tests/test_smc_ringbuffer.py`: imports from `services.live_overlay_daemon.smc_ringbuffer` (line TBD)
- `tests/test_smc_signal_detector.py`: imports from `services.live_overlay_daemon.smc_signal_detector` (line TBD)

---

## Differences from TradingView Script

### ✅ What We Keep

- **Bullish/Bearish Separation**: Independent streams per direction
- **Pattern Logic**: Same predicates (OB, FVG, RJB)
- **Mitigation Tracking**: Unmitigated vs. Mitigated state
- **Strength Metadata**: RJB gets `strength=0.6`, OB/FVG get `strength=1.0`
- **Color Management**: Per-box color + transparency

### ❌ What We Fix

- **O(n) array.shift()** → **O(1) deque.append()**
- **No NaN Guards** → **Math guards in every predicate**
- **Magic Numbers** → **Named constants** (e.g., `threshold=0.2` for RJB)
- **No Edge-Case Handling** → **Defensive bounds checking**
- **Unclear State** → **Explicit `is_mitigated` flag + `mitigated_at` timestamp**
- **Four Separate Arrays** → **Unified SmcBoxManager with routed buffers**

---

## Future Extensions

1. **SMC Break of Structure (BoS)** — add `is_bos_up/down()` predicates
2. **Premium/Discount Stacking** — detect OB+FVG combinations
3. **Strength Calibration** — risk-weight by structure age + mitigation distance
4. **Persistence** — serialize box states for dashboard sync
5. **Multi-timeframe** — separate detector instances per TF, aggregate signals

---

## References

- TradingView Script: `Super OrderBlock / FVG / BoS Tools by makuchaku & eFe` (inspiration)
- ADR-0009: Pin Ledger Consolidation (test freeze strategy)
- SMC Concepts: Order Blocks, Fair Value Gaps, Premium/Discount zones

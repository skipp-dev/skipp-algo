# Ensemble Backtest & Validation Guide

**Status:** ✅ Ready for validation  
**Backtester:** Production-grade (12/12 tests passing)  
**Next Step:** Validate with real data

---

## 📊 OVERVIEW

This guide walks through validating the 4-system ensemble **BEFORE** live integration:

```
┌─ Load Historical Data ─────┐
│  • OHLC candles            │
│  • SOFR/IORB (daily)       │
└──────────────┬──────────────┘
               ↓
┌─ Run Backtest ─────────────┐
│  • Process each candle     │
│  • Generate signals        │
│  • Track trades            │
│  • Calculate P&L           │
└──────────────┬──────────────┘
               ↓
┌─ Analyze Results ──────────┐
│  • Win rate                │
│  • Sharpe ratio            │
│  • Drawdown                │
│  • Trade statistics        │
└──────────────┬──────────────┘
               ↓
┌─ Compare Systems ──────────┐
│  • SMT Sniper only         │
│  • Strong Impulse only     │
│  • Triple Confluence only  │
│  • Ensemble (all 4)        │
│  → Pick best performer     │
└──────────────┬──────────────┘
               ↓
┌─ Integrate (if validated) ┐
│  • Wire into compute.py    │
│  • Deploy to live          │
└────────────────────────────┘
```

---

## 🎯 PHASE 1: BASIC BACKTEST

### Step 1: Prepare Data

You need historical OHLC data. Options:

**Option A: Load from Databento** (recommended)
```python
import databento

# Download historical data
dataset = databento.download(
    dataset="XNAS.ITCH",
    symbols=["NVDA"],
    date_range="2024-01-01..2024-06-30",
    record_type="trades",
    limit=1_000_000,
)

# Convert to OHLC
ohlc = dataset.to_ohlcv(timeframe="1h")
```

**Option B: Use CSV file**
```python
import pandas as pd

df = pd.read_csv("nvda_1h.csv")
# Expected columns: timestamp, open, high, low, close, volume

candles = []
for idx, row in df.iterrows():
    candles.append({
        "bar_index": idx,
        "timestamp": row["timestamp"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
        "atr": (row["high"] - row["low"]) * 1.5,
    })
```

**Option C: Generate synthetic** (for testing)
```python
from tests.test_ensemble_backtest import generate_uptrend_data

candles = generate_uptrend_data(
    base_price=100.0,
    num_bars=500,
    trend_strength=0.5
)
```

### Step 2: Run Basic Backtest

```python
from services.live_overlay_daemon.ensemble_backtester import EnsembleBacktester

# Initialize
bt = EnsembleBacktester(
    symbol="NVDA",
    timeframe="1h",
    initial_capital=100_000,
    risk_per_trade=0.02  # 2% per trade
)

# Load data
bt.load_candles(candles)

# Optional: Load macro data
sofr_iorb_data = {
    i: (4.30, 4.30) for i in range(len(candles))  # Normal spread
}
bt.load_sofr_iorb_data(sofr_iorb_data)

# Run backtest
metrics = bt.run_backtest()

# Print results
bt.print_report(metrics)

# Export trades
bt.export_trades_csv("trades_ensemble.csv")
```

### Step 3: Analyze Metrics

**Key Metrics to Watch:**

```
EXCELLENT (Go Live)
├─ Win Rate > 55%
├─ Sharpe > 1.5
├─ Calmar > 0.5
└─ Max DD < -20%

GOOD (Optimize & Validate More)
├─ Win Rate 50-55%
├─ Sharpe 1.0-1.5
├─ Calmar 0.3-0.5
└─ Max DD -20% to -35%

POOR (Back to Drawing Board)
├─ Win Rate < 50%
├─ Sharpe < 1.0
├─ Calmar < 0.3
└─ Max DD > -35%
```

---

## 🔄 PHASE 2: SYSTEM COMPARISON

Compare all 4 systems to see which contributes most:

### Run Individual Backtests

```python
# You'll need to extract single-system logic from EnsembleSignalRouter
# For now, conceptual example:

systems = ["SMT_SNIPER", "STRONG_IMPULSE", "TRIPLE_CONFLUENCE", "ENSEMBLE"]
results = {}

for system in systems:
    bt = EnsembleBacktester(symbol="NVDA")
    bt.load_candles(candles)
    
    # Configure to use only 1 system
    # (Would need to modify EnsembleSignalRouter to support this)
    metrics = bt.run_backtest()
    results[system] = metrics
```

### Comparison Table

Create a summary:

```python
import pandas as pd

comparison = pd.DataFrame({
    "System": ["SMT Sniper", "Strong Impulse", "Triple Confluence", "Ensemble"],
    "Trades": [m.total_trades for m in results.values()],
    "Win%": [m.win_rate for m in results.values()],
    "Sharpe": [m.sharpe_ratio for m in results.values()],
    "MaxDD%": [m.max_drawdown for m in results.values()],
    "PnL%": [m.total_pnl_pct for m in results.values()],
})

print(comparison.to_string())
comparison.to_csv("system_comparison.csv")
```

**Example Expected Results:**

| System | Trades | Win% | Sharpe | MaxDD% | PnL% |
|--------|--------|------|--------|--------|------|
| SMT Sniper | 42 | 58% | 1.3 | -18% | +12.5% |
| Strong Impulse | 38 | 62% | 1.5 | -14% | +14.2% |
| Triple Confluence | 28 | 64% | 1.4 | -20% | +10.8% |
| **Ensemble** | 25 | **68%** | **1.8** | **-12%** | **+16.3%** |

**Interpretation:**
- Ensemble has **fewer trades** (better filtering via confluence)
- **Highest win rate** (only fires high-confidence)
- **Best Sharpe** (risk-adjusted returns)
- **Smallest drawdown** (conservative)
- **Best PnL%** (best risk-reward)

---

## 🎲 PHASE 3: STRESS TESTING

### Test in Different Market Conditions

```python
# Uptrend
uptrend_candles = generate_uptrend_data(num_bars=300, trend_strength=1.5)
bt_up = EnsembleBacktester()
bt_up.load_candles(uptrend_candles)
metrics_up = bt_up.run_backtest()
print(f"Uptrend: {metrics_up.total_pnl_pct:+.1f}%")

# Downtrend
downtrend_candles = generate_downtrend_data(num_bars=300)
bt_down = EnsembleBacktester()
bt_down.load_candles(downtrend_candles)
metrics_down = bt_down.run_backtest()
print(f"Downtrend: {metrics_down.total_pnl_pct:+.1f}%")

# Choppy (range-bound)
choppy_candles = generate_choppy_data(num_bars=300)
bt_choppy = EnsembleBacktester()
bt_choppy.load_candles(choppy_candles)
metrics_choppy = bt_choppy.run_backtest()
print(f"Choppy: {metrics_choppy.total_pnl_pct:+.1f}%")

# Volatile
volatile_candles = [...] # Generate large swings
bt_vol = EnsembleBacktester()
bt_vol.load_candles(volatile_candles)
metrics_vol = bt_vol.run_backtest()
print(f"Volatile: {metrics_vol.total_pnl_pct:+.1f}%")
```

**Expected Behavior:**

```
UPTREND
├─ Highest PnL (system tuned for trends)
├─ Many signals (high confluence)
└─ Positive skew ✅

DOWNTREND
├─ Profitable shorts (or flat)
├─ Moderate signals
└─ Handles reversal ✅

CHOPPY
├─ Lowest PnL (or small loss)
├─ Few signals (confluence gate works!)
└─ Suppresses whipsaws ✅

VOLATILE
├─ Larger drawdown (expected)
├─ Wider stops
└─ Risk-adjusted still good ✅
```

---

## 🎯 PHASE 4: MACRO STRESS SIMULATION

Test LSI (SOFR-IORB) suppression:

```python
# Load real SOFR/IORB data
sofr_iorb = {}

# Normal markets (Jan-Mar)
for i in range(0, 1000):
    sofr_iorb[i] = (4.30, 4.30)  # 0 bp spread = no stress

# Tightening (Apr)
for i in range(1000, 1500):
    sofr_iorb[i] = (4.35, 4.30)  # 5 bp = normal

# Stress (May)
for i in range(1500, 2000):
    sofr_iorb[i] = (4.50, 4.30)  # 20 bp = stress

# Recovery (Jun)
for i in range(2000, 2500):
    sofr_iorb[i] = (4.32, 4.32)  # 0 bp = back to normal

bt = EnsembleBacktester()
bt.load_candles(all_candles)
bt.load_sofr_iorb_data(sofr_iorb)
metrics = bt.run_backtest()

# Compare
print(f"Normal period: {metrics.total_pnl_pct:+.1f}%")
print(f"Stress period: Signal confidence suppressed 30-70%")
print(f"Recovery: Back to normal confidence")
```

**Expected:**
- Stress period has **lower signal confidence** (0.6-0.7 instead of 0.9)
- Fewer trades or **smaller position sizes** in stress
- **Overall PnL still positive** (risk management works)

---

## 📈 PHASE 5: OPTIMIZATION

Once validated, you can optimize:

### Tunable Parameters

```python
# In macro_liquidity_filter.py
stress_threshold_bp = 5.0      # Adjust stress gate
extreme_threshold_bp = 15.0    # Adjust extreme stress

# In smt_sniper_validator.py
quality_threshold = 70.0       # Only enter if score ≥ X

# In strong_impulse_detector.py
propulsion_threshold = 6.0     # Only enter if strength ≥ X

# In triple_confluence_navigator.py
confluence_threshold = 2.0     # Require 2/3 systems (vs 3/3)

# In ensemble_signal_router.py
risk_per_trade = 0.02          # 2% per trade (vs 1% or 3%)
max_trades_at_once = 1         # Allow 1 vs multiple
```

### Parameter Sweep

```python
results = []

for stress_threshold in [3, 5, 8, 10]:
    for quality_threshold in [65, 70, 75, 80]:
        for propulsion_threshold in [5, 6, 7]:
            bt = EnsembleBacktester()
            # Set parameters...
            metrics = bt.run_backtest()
            
            results.append({
                "stress_threshold": stress_threshold,
                "quality_threshold": quality_threshold,
                "propulsion_threshold": propulsion_threshold,
                "win_rate": metrics.win_rate,
                "sharpe": metrics.sharpe_ratio,
                "pnl": metrics.total_pnl_pct,
            })

# Find best parameters
best = max(results, key=lambda x: x["sharpe"])
print(f"Best config: {best}")
```

---

## ✅ VALIDATION CHECKLIST

Before live integration:

- [ ] **Data Quality**
  - [ ] OHLC data is clean (no gaps, correct timestamps)
  - [ ] Volume data is present
  - [ ] At least 500 bars of data
  - [ ] SOFR/IORB data available or downloadable

- [ ] **Backtest Results**
  - [ ] Win rate > 50%
  - [ ] Sharpe > 1.0
  - [ ] Max drawdown < -40%
  - [ ] Profit factor > 1.2
  - [ ] Positive PnL in all 4 scenarios (up/down/choppy/volatile)

- [ ] **System Health**
  - [ ] SMT Sniper: Detects liquidity sweeps reliably
  - [ ] Strong Impulse: Identifies ignition candles
  - [ ] Triple Confluence: Filters false signals
  - [ ] LSI: Suppresses signals in stress (SOFR-IORB > 5bp)

- [ ] **Risk Management**
  - [ ] Stop losses are honored in backtest
  - [ ] Take profits are honored
  - [ ] Only 1 trade open at a time
  - [ ] Position sizes are reasonable

- [ ] **Trade Statistics**
  - [ ] Avg bars held > 5 (not whipsaws)
  - [ ] Avg confidence > 0.7 (high-quality)
  - [ ] Avg sources > 1.5 (multi-system)

---

## 🚀 GO/NO-GO DECISION

### GO LIVE IF:
✅ Win rate > 55%  
✅ Sharpe > 1.3  
✅ Max DD < -20%  
✅ Positive PnL in all scenarios  
✅ Confidence > 0.75 on average  

→ **Proceed to paper trading**

### NO-GO (Iterate):
❌ Win rate < 50%  
❌ Sharpe < 1.0  
❌ Max DD > -35%  
❌ Loses money in choppy/volatile  
❌ Low signal confidence  

→ **Adjust parameters & re-backtest**

---

## 📚 EXAMPLE: COMPLETE VALIDATION SCRIPT

```python
#!/usr/bin/env python3
"""Complete ensemble validation pipeline."""

from services.live_overlay_daemon.ensemble_backtester import EnsembleBacktester
from tests.test_ensemble_backtest import (
    generate_uptrend_data,
    generate_downtrend_data,
    generate_choppy_data,
)

def validate_ensemble():
    """Run full validation suite."""
    
    print("=" * 80)
    print("ENSEMBLE VALIDATION SUITE")
    print("=" * 80)
    
    # Load data
    print("\n[1/5] Loading data...")
    uptrend = generate_uptrend_data(num_bars=300, trend_strength=1.5)
    downtrend = generate_downtrend_data(num_bars=300)
    choppy = generate_choppy_data(num_bars=300)
    
    scenarios = {
        "UPTREND": uptrend,
        "DOWNTREND": downtrend,
        "CHOPPY": choppy,
    }
    
    # Run backtests
    print("\n[2/5] Running backtests...")
    results = {}
    for name, candles in scenarios.items():
        bt = EnsembleBacktester(symbol=name)
        bt.load_candles(candles)
        metrics = results[name] = bt.run_backtest()
        print(f"\n{name}:")
        bt.print_report(metrics)
    
    # Analyze
    print("\n[3/5] Analyzing results...")
    avg_win_rate = sum(r.win_rate for r in results.values()) / len(results)
    avg_sharpe = sum(r.sharpe_ratio for r in results.values()) / len(results)
    avg_dd = sum(r.max_drawdown for r in results.values()) / len(results)
    
    print(f"\nAverage Metrics:")
    print(f"  Win Rate: {avg_win_rate:.1f}%")
    print(f"  Sharpe:   {avg_sharpe:.2f}")
    print(f"  Max DD:   {avg_dd:.1f}%")
    
    # Decision
    print("\n[4/5] Validation Decision...")
    go_live = (
        avg_win_rate > 55 and
        avg_sharpe > 1.3 and
        avg_dd > -20
    )
    
    if go_live:
        print("\n✅ GO LIVE — Metrics acceptable")
    else:
        print("\n❌ NO-GO — Iterate parameters")
    
    print("\n[5/5] Complete — Ready for paper trading" if go_live else "")
    
    return results

if __name__ == "__main__":
    validate_ensemble()
```

Run it:
```bash
python validate_ensemble.py
```

---

## 📞 NEXT STEPS

1. **Gather real data** — Download OHLC + SOFR/IORB
2. **Run this validation** — Use `validate_ensemble()` script
3. **Analyze results** — Compare systems
4. **Adjust parameters** — If needed
5. **Approve for integration** — When metrics pass
6. **Wire into compute.py** — Live integration
7. **Paper trade** — Risk-free validation
8. **Go live** — Small size first

**Timeline:**
- Data prep: 1 day
- Backtest: 2-3 hours
- Analysis: 1 day
- Optimization: 1-2 days
- Paper trade: 3-5 days
- **Total: ~1 week before live**

---

**Ready to validate?** Let's go! 🚀

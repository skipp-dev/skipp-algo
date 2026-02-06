# TradingView Test Checklist — SkippALGO v6.1

## Pre-Flight Checks

### 1. Compilation Test

- [ ] **Indicator**: Paste `SkippALGO.pine` into Pine Editor → No errors
- [ ] **Strategy**: Paste `SkippALGO_Strategy.pine` into Pine Editor → No errors
- [ ] Note any warnings (usually harmless but document them)

### 2. Add to Chart

- [ ] Indicator loads without runtime errors
- [ ] Strategy loads without runtime errors
- [ ] No "Script error" or "Execution timeout" messages

---

## Functional Tests

### 3. Multi-Timeframe Data Loading

Test on different chart timeframes:

| Chart TF | Expected Behavior | Pass |
|----------|-------------------|------|
| 1m | TF1-TF7 show data, no "na" in first columns | [ ] |
| 5m | TF1-TF7 show data | [ ] |
| 15m | TF1-TF7 show data | [ ] |
| 1H | TF1-TF7 show data | [ ] |
| 4H | TF1-TF7 show data | [ ] |
| 1D | TF1-TF7 show data | [ ] |

### 4. Forecast Table Display

- [ ] Table appears in correct position (default: bottom_right)
- [ ] All 7 timeframe rows populate
- [ ] "Up%" or "Edge pp" column shows values (not "—" after warmup)
- [ ] Colors update dynamically (green/red/neutral)

### 5. Calibration Warmup

- [ ] Initial state shows "Warm X/40" during warmup
- [ ] After ~40 bars per bin, shows actual probability %
- [ ] Reliability label changes from "weak" → "ok" → "strong"

### 6. ATR=0 Edge Case

Test on symbols with potential zero ATR:

- [ ] Add to illiquid symbol (penny stock, low-volume crypto)
- [ ] No runtime errors
- [ ] Forecast skips or shows "—" (not crash)

---

## Strategy-Specific Tests

### 7. Entry/Exit Signals

- [ ] Strategy shows trades on chart (triangles/arrows)
- [ ] Long entries trigger when conditions met
- [ ] Short entries trigger when conditions met
- [ ] Exits occur at TP/SL or reversal

### 8. Strategy Tester

- [ ] Open "Strategy Tester" tab
- [ ] "Overview" shows performance metrics
- [ ] "List of Trades" populates
- [ ] No "NaN" or infinite values in metrics

### 9. Backtest Consistency

Run on same symbol/timeframe twice:

- [ ] Same number of trades
- [ ] Same P&L results
- [ ] Deterministic behavior confirmed

---

## Edge Case Tests

### 10. Symbol Types

| Symbol Type | Loads OK | No Errors |
|-------------|----------|-----------|
| Stock (e.g., AAPL) | [ ] | [ ] |
| Crypto (e.g., BTCUSD) | [ ] | [ ] |
| Forex (e.g., EURUSD) | [ ] | [ ] |
| Index (e.g., SPX) | [ ] | [ ] |
| Futures (e.g., ES1!) | [ ] | [ ] |

### 11. Extreme Conditions

- [ ] Gap up/down (>5% open vs previous close)
- [ ] Flash crash simulation (use historical 2010-05-06)
- [ ] Extended hours data (if available)
- [ ] Weekend gaps (crypto vs stocks)

### 12. Time Boundaries

- [ ] First bar of session
- [ ] Last bar of session
- [ ] DST transition days
- [ ] Market holidays (partial data)

---

## Performance Tests

### 13. Calculation Time

- [ ] No "Calculation timeout" on 1-minute chart with max history
- [ ] Script completes in <500ms per bar refresh

### 14. Memory Usage

- [ ] No "Out of memory" on long backtests
- [ ] Array sizes stay bounded (queue management working)

---

## Alerts (Indicator Only)

### 15. Alert Configuration

- [ ] "Create Alert" dialog shows available conditions
- [ ] Buy/Long alert fires correctly
- [ ] Sell/Short alert fires correctly
- [ ] Alert message contains expected info

---

## Regression Checklist

After any code change, verify:

- [ ] All above tests still pass
- [ ] No new compiler warnings
- [ ] Backtest results match previous (if no logic change)

---

## Notes

### Known Limitations

1. TradingView limits: 500 candles for request.security
2. Deep history may show NA values in early bars
3. Some symbols have no ATR on first bars

### Test Symbols

- **High liquidity**: AAPL, MSFT, BTCUSD, EURUSD
- **Low liquidity**: Small-cap stocks, obscure crypto pairs
- **Volatile**: TSLA, NVDA, altcoins

### Version Tested

- Pine Script: v6
- Date: ____________
- Tester: ____________

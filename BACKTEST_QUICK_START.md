# Ensemble Backtest — Quick Start

**Status:** Ready to run  
**Data Source:** FMP (Financial Modeling Prep)  
**Time to Results:** ~5-10 minutes per symbol  

---

## 🚀 RUN BACKTEST NOW

### Step 1: Set FMP API Key
```bash
export FMP_API_KEY="your-fmp-api-key-here"
```

### Step 2: Run Single Symbol Backtest
```bash
# NVDA, 1-hour bars, last 180 days
python run_ensemble_backtest.py --symbol NVDA --days 180 --timeframe 1hour
```

### Step 3: View Results
Results saved to: `./backtest_results/NVDA_1hour_*`
- `NVDA_1hour_metrics.json` — All performance metrics
- `NVDA_1hour_trades.csv` — Individual trade log
- `NVDA_1hour_report.txt` — Human-readable report

---

## 📊 WHAT YOU'LL GET

### Performance Report
```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ENSEMBLE BACKTEST REPORT                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

📊 PERFORMANCE SUMMARY
  Total P&L ............................ +$12,345.67 (+12.35%)
  Total Trades ......................... 42 trades
  Win Rate ............................. 64.3%
  Winning Trades ....................... 27
  Losing Trades ........................ 15

📈 PROFITABILITY
  Avg Win / Trade ....................... +0.65%
  Avg Loss / Trade ...................... -0.42%
  Largest Win ........................... +3.25%
  Largest Loss .......................... -2.10%
  Profit Factor ......................... 2.15x

🎯 RISK METRICS
  Max Drawdown .......................... -14.2%
  Sharpe Ratio .......................... 1.78
  Sortino Ratio ......................... 2.15
  Calmar Ratio .......................... 0.87

⏱️  TRADE DURATION
  Avg Bars Held ......................... 8.5 bars
  Min / Max ............................. 2 / 47 bars

🤖 ENSEMBLE QUALITY
  Avg Confidence ........................ 0.82
  Avg System Agreement .................. 2.1 systems/signal
  Single System Signals ................. 8
  Multi System Signals .................. 34
```

### Validation Decision
```
✅ PASS — Metrics acceptable for paper trading
   Win Rate: 64.3% ✅
   Sharpe:   1.78 ✅
   Max DD:   -14.2% ✅
```

---

## 🎯 COMMAND EXAMPLES

### Single Symbol (Recommended First)
```bash
# NVDA, last 6 months, 1-hour bars
python run_ensemble_backtest.py --symbol NVDA --days 180 --timeframe 1hour

# AAPL, last 3 months, 4-hour bars
python run_ensemble_backtest.py --symbol AAPL --days 90 --timeframe 4hour

# SPY, last year, daily
python run_ensemble_backtest.py --symbol SPY --days 365 --timeframe daily
```

### Multiple Symbols (Compare)
```bash
# Test 5 symbols in one run
python run_ensemble_backtest.py --multi --days 180
# Tests: NVDA, AAPL, MSFT, SPY, QQQ
```

### Custom Output Directory
```bash
python run_ensemble_backtest.py --symbol NVDA --output ./my_results
```

---

## 📈 EXPECTED RESULTS

### Good Performance (Proceed)
✅ Win Rate: 55-70%  
✅ Sharpe: 1.3-2.2  
✅ Max DD: -15% to -25%  
✅ Profit Factor: 1.5x+  

### Acceptable (Monitor)
⚠️ Win Rate: 50-55%  
⚠️ Sharpe: 1.0-1.3  
⚠️ Max DD: -25% to -35%  

### Poor (Needs Work)
❌ Win Rate: <50%  
❌ Sharpe: <1.0  
❌ Max DD: >-35%  

---

## 📊 INTERPRET RESULTS

### Win Rate > 55%
- System is better than random
- Each individual trade has positive expected value
- Confidence in signal quality

### Sharpe > 1.3
- Risk-adjusted returns are good
- Consistent profit with acceptable risk
- Better than buy-and-hold

### Max DD < -25%
- Drawdown is within acceptable range
- System can handle volatility
- Position sizing is reasonable

### Profit Factor > 1.5
- For every $1 lost, gain >$1.50
- Excellent risk/reward ratio
- Sustainable profitability

---

## 🔍 DEEP DIVE: TRADES CSV

Open `NVDA_1hour_trades.csv` to analyze:

| entry_bar | entry_price | direction | stop_loss | take_profit | confidence | exit_bar | exit_price | pnl_pct | win |
|-----------|------------|-----------|-----------|-------------|------------|----------|-----------|---------|-----|
| 100 | 123.45 | long | 119.20 | 131.50 | 0.85 | 108 | 131.50 | +6.58% | True |
| 150 | 124.67 | short | 127.80 | 119.30 | 0.78 | 154 | 119.30 | +4.30% | True |
| 200 | 122.10 | long | 118.50 | 128.90 | 0.92 | 205 | 118.50 | -3.20% | False |

**Analyze:**
- Average bars held: 8.5 (good, not whipsaws)
- Win distribution: Consistent or cluster?
- Stop loss vs TP: Is SL/TP ratio 1:2?
- Confidence: Winning trades have higher confidence?

---

## 💡 TIPS

### If Performance is Good (Win% > 55%, Sharpe > 1.3)
→ **Ready for paper trading**
1. Start with small position sizes
2. Monitor signals for 1-2 weeks
3. Verify live performance matches backtest
4. Gradually increase size
5. Then full live deployment

### If Performance Needs Work
→ **Iterate before paper trading**
1. Check SOFR/IORB data: Is macro suppression working?
2. Analyze losing trades: Are they all short? All in one condition?
3. Adjust parameters:
   - Increase confluence requirement (3/3 instead of 2/3)
   - Increase quality score threshold (75 instead of 70)
   - Increase propulsion threshold (7.0 instead of 6.0)
4. Re-run backtest with new parameters
5. Compare results

### Test Multiple Timeframes
```bash
# 5-minute bars (more trades, higher churn)
python run_ensemble_backtest.py --symbol NVDA --timeframe 5min

# 4-hour bars (fewer trades, larger moves)
python run_ensemble_backtest.py --symbol NVDA --timeframe 4hour

# Daily (trend-following)
python run_ensemble_backtest.py --symbol NVDA --timeframe daily
```

---

## ❓ TROUBLESHOOTING

### "FMP_API_KEY not found"
```bash
export FMP_API_KEY="your-key"
python run_ensemble_backtest.py --symbol NVDA
```

### "No data returned for NVDA"
- Check symbol is correct (use uppercase)
- Check date range is valid
- Check FMP API is working: `curl https://financialmodelingprep.com/api/v3/`

### "Could not load macro data"
- SOFR/IORB not available for this period
- Backtest will proceed without macro data
- Results still valid, just without stress suppression

### Results look too good (Win% > 80%)
- Possible overfitting on backtest period
- Paper trade to validate
- Monitor for slippage and commissions

### Results look too bad (Win% < 40%)
- Check if signal routing is working
- Verify backtest data is correct
- Consider longer historical period
- Try different timeframe

---

## 📞 NEXT STEPS

### After Running Backtest:
1. ✅ Check if metrics pass validation criteria
2. ✅ Analyze trade distribution (winners vs losers)
3. ✅ Compare different symbols/timeframes
4. ✅ If good → Proceed to paper trading
5. ✅ If needs work → Iterate parameters, re-test

### Paper Trading:
1. Set small position size (1-5% of account)
2. Monitor for 1-2 weeks
3. Compare live vs backtest results
4. Adjust if needed
5. Gradually increase size

### Live Trading:
1. Start with micro positions
2. Monitor daily for signal quality
3. Track P&L closely
4. Scale up if performing well
5. Always maintain risk management

---

## 🎯 EXPECTED TIMELINE

```
Day 1:    Run backtest for 5 symbols
          └─ 30 minutes (parallel)

Days 2-3: Analyze results, iterate if needed
          └─ 2-4 hours

Days 4-10: Paper trade (validate with real money risk)
           └─ Monitor daily, 15 min/day

Day 11:   Go live with small size
          └─ Gradually scale up

Week 2+:  Monitor and optimize
          └─ Ongoing management
```

---

## 🚀 READY?

Run your first backtest now:

```bash
export FMP_API_KEY="your-key"
python run_ensemble_backtest.py --symbol NVDA --days 180
```

Results in 5-10 minutes! 📊

---

**Questions?** Check [BACKTEST_VALIDATION_GUIDE.md](BACKTEST_VALIDATION_GUIDE.md) for deep dive.

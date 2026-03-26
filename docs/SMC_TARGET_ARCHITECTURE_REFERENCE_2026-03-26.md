# SMC Target Architecture Reference (2026-03-26)

## Purpose
This document is the implementation reference for the next producer phase.
It records the intended module split, canonical contracts, and rule sources so refactors can be compared against a stable target.

## Primary Functional References
- Structure core (OB/FVG/BOS/qualifiers): Super OrderBlock / FVG / BoS Tools by makuchaku & eFe
- Liquidity levels/sweeps: Liquidity by makuchaku & eFe
- Session/killzone context: ICT Killzones & Pivots [TFO]
- HTF directional context: FVG Trend
- Fractal qualifier: Broken Fractal
- HTF dealing range context: IPDA operating range

## Data Contract (Producer Inputs)
Required bar columns:
- timestamp
- open
- high
- low
- close
- volume

Optional:
- symbol
- timeframe

## Canonical Structure Contract
SmcStructure remains unchanged and contains only:
- bos
- orderblocks
- fvg
- liquidity_sweeps

No session/context/qualifier fields are added to SmcStructure.

## Additive Layers (Outside SmcStructure)
- structure_qualifiers
- session_context
- htf_context
- later optional volume_context

## Module Split
New/target modules:
- scripts/smc_price_action_engine.py
- scripts/smc_liquidity_engine.py
- scripts/smc_structure_qualifiers.py
- scripts/smc_session_context.py
- scripts/smc_htf_context.py

Facade:
- scripts/explicit_structure_from_bars.py remains thin and canonical for structure output.

## Rule Baseline
### Orderblocks (two-candle)
Bullish:
- prev candle down
- current candle up
- current close > prev high
- zone: low=min(prev.low, cur.low), high=prev.high

Bearish:
- prev candle up
- current candle down
- current close < prev low
- zone: low=prev.low, high=max(prev.high, cur.high)

### FVG (three-candle)
Bullish:
- low[i] > high[i-2]
- zone: low=high[i-2], high=low[i]

Bearish:
- high[i] < low[i-2]
- zone: low=high[i], high=low[i-2]

### BOS from pivots
- symmetric pivot detection (pivot_lookup)
- bullish break: crossover(close/high, last pivot high)
- bearish break: crossunder(close/low, last pivot low)
- CHOCH when break direction flips prior structure direction, else BOS

### Liquidity levels and sweeps
Liquidity levels from 3-bar pivot highs/lows.
Sweeps against those pivot levels:
- buy-side: high > level and close < level
- sell-side: low < level and close > level

## Session Defaults
Timezone default: America/New_York
Killzones:
- Asia: 20:00-00:00
- London: 02:00-05:00
- NY AM: 09:30-11:00
- NY Lunch: 12:00-13:00
- NY PM: 13:30-16:00

## Integration Intent
- structure_batch keeps explicit structure producer as canonical path
- service adds qualifiers/context additively in snapshot bundle
- no provider additions
- no IBKR dependency for structure detection
- no L2/DOM assumptions

## Non-goals
- No Pine rendering behavior in Python
- No new fields in SmcStructure
- No synthetic heuristics outside explicit bar rules
- No new subscription requirements

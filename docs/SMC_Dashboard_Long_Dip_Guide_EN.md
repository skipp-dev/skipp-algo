# SMC++ Dashboard Guide for Long-Dip Setups (EN)

## Purpose

This document explains the SMC++ dashboard in plain English.
It is an interpretation and workflow guide, not a standalone buy signal.

Core rule:

- The dashboard is a traffic light and checklist.
- The more fields align, the cleaner the setup.
- A zone by itself is not an entry.

## Dashboard Terms in Plain English

### Trend

The active market structure on the current chart.

- Bullish: structure leans upward
- Bearish: structure leans downward
- Neutral: no clear structural edge yet

### HTF Trend

HTF means Higher Time Frame.
This field shows whether larger timeframes support the trade.

Example:

`3:Bearish | 10:Bullish | 30:Bearish`

That is mixed and not ideal for a conservative long-dip.

### Pullback Zone

Shows whether price is inside a possible reaction zone.

Typical states:

- In OB Zone
- In FVG Zone
- In OB + FVG Zone
- No Long Zone

Important: a zone means watch, not buy.

### Reclaim

Reclaim means price has recovered an important level or zone.
For longs, that matters because it shows buyers are taking control back.

Positive examples:

- OB Reclaimed
- FVG Reclaimed
- Internal Low Reclaimed
- Swing Low Reclaimed

Warning sign:

- No Reclaim

### Long Setup

The operating state of the long setup.

- In Zone: interesting area, but not an entry yet
- Armed: setup is being tracked
- Building: structure is improving
- Confirmed: key confirmation is in place
- Ready: clean, advanced setup
- Blocked or Invalidated: setup is broken

### Setup Age

How old an armed or confirmed setup is.

Examples:

- armed 2
- confirmed 1

Fresh setups are usually better than old ones.

### Long Visual

The visual summary of the long state.

### Close Strength

Shows how strong the current candle closed.

- Strong Close: bullish close
- Weak Close: weak close

### EMA Support

Checks whether price and EMA structure support the long.

- OK: clean tailwind
- No: no clean trend support

### ADX

ADX measures trend strength.
With the extra text you also see who is applying pressure.

Example:

`30 | Bearish pressure`

That means the move has strength, but sellers currently control that strength.

### Rel Volume

Relative volume against average volume.

- 1.2x: above normal participation
- 0.5x: below normal participation
- 0.01x: extremely weak

### LTF Bias

LTF means Lower Time Frame.
This field measures the tendency of the smaller internal structure.

### LTF Delta

Short-term pressure or volume imbalance on the lower timeframe.

- positive: buyer pressure
- negative: seller pressure
- n/a: no useful data base

### Objects

Shows how many OB and FVG objects are visible. This is more orientation than entry logic.

### Swing H/L

Shows major and internal structure highs and lows.

### Long Zones

The currently relevant long zones.

### Long Triggers

The reclaim or confirmation levels for the setup.

### Legend

Dashboard color legend:

- Aqua: Zone
- Orange: Armed
- Gold: Building
- Lime: Confirmed
- Green: Ready
- Red: Fail

## Example Snapshot Interpretation

Example:

- Trend = Bullish
- HTF Trend = 3:Bearish | 10:Bullish | 30:Bearish
- Pullback Zone = In FVG Zone
- Reclaim = No Reclaim
- Long Visual = In Zone
- Close Strength = Weak Close
- EMA Support = No
- ADX = 30 | Bearish pressure
- Rel Volume = 0.01x

Simple read:

- Price is inside a possible long zone.
- But most key confirmations are still missing.

Practical conclusion:

> Interesting long zone, but not a clean long confirmation yet. Waiting is better than entering.

## What You Should Not Do in This State

- Do not buy only because price is inside an FVG or OB zone.
- Do not blindly go long into clear seller pressure.
- Do not overrate `Trend = Bullish` if HTF, reclaim, close, and EMA do not agree.
- Do not enter aggressively on extremely weak volume.
- Do not trade without a clear invalidation level.

## What to Wait For in a Long-Dip

The cleaner sequence is usually:

1. Price reaches a meaningful zone.
2. A reclaim appears.
3. The long setup becomes Armed or Building.
4. Later it becomes Confirmed or Ready.
5. Close, EMA, ADX, and volume stop arguing against the trade.

## Three Phases

### 1. Watch

- Trend bullish or at least not bearish
- Price in an OB or FVG zone
- No reclaim yet
- Long Visual still In Zone

### 2. Prepare

- Reclaim is present
- Long Setup becomes Armed or Building
- Close Strength improves
- EMA Support improves

### 3. Entry

- Trend bullish
- Reclaim present
- Long Setup is Confirmed or Ready
- Strong Close
- EMA Support OK
- ADX not bearish pressure
- Volume not dead

## Traffic Light for Long-Dips

### Green

- Trend bullish
- HTF not clearly against the trade
- Pullback Zone active
- Reclaim present
- Long Setup Confirmed or Ready
- Strong Close
- EMA Support OK

### Yellow

- Zone active
- first reclaim or early internal shift visible
- Long Setup Armed or Building

### Red

- No Reclaim
- Weak Close
- EMA Support No
- ADX bearish pressure
- extremely weak volume
- only In Zone without confirmation

## Five-Point Checklist Before a Long

1. Trend bullish?
2. Price inside a meaningful OB or FVG zone?
3. Reclaim present?
4. Long Setup Confirmed or Ready?
5. Are close, EMA, ADX, and volume not fighting the trade?

If only one or two of these are true, it is usually too early.

## New Long-Dip Alert Presets

The current alert presets in `SMC++.pine` map directly to the workflow:

- `Long Dip Watchlist`: bullish trend plus active pullback zone
- `Long Dip Armed+`: zone, reclaim, and an armed setup
- `Long Dip Early`: early hint with internal structure, strong close, and EMA support
- `Long Dip Clean`: confirmed and filtered setup
- `Long Dip Entry Best`: recommended standard entry alert
- `Long Dip Entry Strict`: later and more selective with HTF and momentum filters
- `Long Dip Failed`: setup invalidated

## Recommended Alert Usage

### For monitoring

- `Long Dip Watchlist`

### For prepared setups

- `Long Dip Armed+`

### For actual entries

- `Long Dip Entry Best`

### For highly selective entries

- `Long Dip Entry Strict`

## Clear Default Recommendation

The best default alert is `Long Dip Entry Best`, because it is not too early and not too late.
It fits the dashboard workflow well:

- trend bullish
- reclaim present
- ready state present
- strong close
- EMA support OK

## One-Line Rule

Only trade a long-dip when:

**Trend is bullish + price is in an OB/FVG zone + reclaim is present + Long Setup is Confirmed or Ready + close is strong + EMA Support is OK**
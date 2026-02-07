# SkippALGO Tuning & Configuration Guide

This guide details advanced configuration options for risk management and signal filtering, including specific "tuning recipes" for strict trading styles.

---

## 1. Dynamic Risk Decay (Tuning)

**Dynamic Risk Decay** is a mechanism that tightens your Stop Loss over time. This prevents a trade from lingering in a loss for too long. Instead of a static "Hard Stop", the stop moves closer to your entry price linearly over the first few bars.

### How it Works

The stop transitions from an **Initial Width** (Wide, to survive entry noise) to a **Sustained Width** (Tight, to enforce invalidation) over a set **Duration**.

### Standard vs. Strict Profiles

| Parameter | Standard (Default) | **Strict (Sniper)** | Effect of Strict Mode |
| :--- | :--- | :--- | :--- |
| **Stop ATR (Initial)** | 2.5 ATR | **2.0 ATR** | Less breathing room at entry. Kills bad entries instantly. |
| **Sustained Stop ATR** | 1.5 ATR | **1.0 ATR** | Very tight invalidation after N bars. |
| **Decay Duration** | 6 Bars | **6 Bars** | Same transition speed. |

#### The "Strict" Decay Curve (Visualized)

* **Bar 0 (Entry)**: Stop is at **2.0 ATR**.
* **Bar 3 (Mid)**: Stop has tightened to **1.5 ATR**.
* **Bar 6 (End)**: Stop is fully tightened to **1.0 ATR**.

**Why use Strict Mode?**
It forces the trade to work *immediately*. If price hangs around the entry or drifts slightly against you effectively invalidating the momentum thesis, the decay will tag you out with a smaller loss than a static stop.

---

## 2. Signal Filtering: `minDirProb`

The `minDirProb` (Minimum Directional Probability) setting controls the "Conviction" required by the Neural Forecast Engine before it permits a trade.

### The Math of the 3-Way Model

The engine predicts three outcomes: **Up**, **Flat**, and **Down**.

* Random Chance = ~33% per outcome.
* Trading Edge = Anything significantly above 33%.

### Tuning Thresholds

| Value | Behavior | Trade Frequency | Reliability |
| :--- | :--- | :--- | :--- |
| **0.34 - 0.40** | **Loose**. Accepts almost any positive bias. | High | Low/Mid |
| **0.42** | **Standard**. Default edge requirement. | Normal | Good |
| **0.46** | **Strict**. Requires clear directional dominance. | Lower | Very Good |
| **0.55+** | **Sniper**. Absolute Majority (>50%). | Rare | Excellent |

* **Tip**: Increasing this to **0.46** (46%) is a great way to filter out "weak" buy signals that might look okay on price action but lack statistical backing.
* **Warning**: Setting this above **0.55** requires the model to think "Up" is more likely than "Flat" and "Down" *combined*, which is a very high bar for financial markets.

---

## 3. Troubleshooting: The Forecast "Safe Mode"

If you change `minDirProb` to a very high value (e.g., 0.68) but **still see Buy Labels**, your Forecast Engine has likely entered **Safe Mode (Disabled)**.

### The "Fail-Safe Open" Mechanism

SkippALGO contains a safety check to prevent calculation errors:
> **Rule**: The **Forecast Timeframe** must be greater than or equal to the **Chart Timeframe**.

If you are on a **5-Minute Chart**, but your settings have "Forecast 1" set to **1 Minute** (Default), the script cannot accurately map the 1-minute forecast data onto the 5-minute bars.

**Result**:

1. The Forecast Engine **Disables itself** to prevent crash/error.
2. The "Forecast Gate" defaults to `open` (True), allowing **ALL** structural signals to pass through.
3. Your `minDirProb` filter is ignored.

### Use Case Fix

Ensure your **Forecast 1** setting matches or is larger than your trading timeframe.

* **Scenario by Mistake**:
  * Chart: 15m
  * Forecast 1 Setting: 1m
  * *Result*: Forecast Disabled. `minDirProb` Ignored.
* **Scenario Corrected**:
  * Chart: 15m
  * Forecast 1 Setting: **15m**
  * *Result*: Forecast Active. `minDirProb` works correctly.

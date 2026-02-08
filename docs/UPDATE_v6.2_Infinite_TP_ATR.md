# Update v6.2.1: Infinite TP & UX Enhancements

**Date:** February 8, 2026
**Status:** Implemented & Verified

## 1. Feature: Infinite Take Profit (Trailing Stop Only)

**User Request:** "Can we have a trailing stop loss instead of a TP? So we get the most out of the spike?"

### Problem

News events and market opens (e.g., 15:30) often create massive directional spikes (impulse candles).

* **Standard Behavior:** The algorithm sets a fixed Risk:Reward target (e.g., 5 ATR). If the spike is huge, the TP is hit early, leaving potential profit on the table as the price continues to run.
* **Desired Behavior:** Remove the ceiling (TP) and strictly follow the price with a Trailing Stop until momentum reverses.

### Solution

Added a new Risk Management setting: **Infinite TP (Trailing Stop Only)**.

* **Toggle:** `useInfiniteTP` (Boolean).
* **Mechanism:**
  * When **Enabled**: The fixed Take Profit (`tpPx`) is set to `na` (or ignored by the exit logic).
  * **Exit Logic**: The trade can *only* close via:
        1. Initial Hard Stop Loss (`stopATR`).
        2. Trailing Stop Loss (`trailATR`).
  * **Visualization**: The Green TP Line is removed from the chart. Only the Red (Stop) and Orange (Trail) lines remain.

### Usage Guide

1. Go to **Settings -> Risk Management**.
2. Enable **"Infinite TP (Trailing Stop Only)"**.
3. Adjust **Trail ATR** (Default: 2.5) to suit the volatility. A wider trail captures larger moves; a tighter trail locks profit sooner.

---

## 2. Feature: Configurable Rescue Impulse

**User Request:** "Can you make the impulse trigger configurable?"

### Problem

The "Reversal Fix" introduced a hardcoded checks for V-shape reversals: `Body > 0.7 ATR`.

* Fixed values are rigid. Some assets/timeframes might need stricter (1.0 ATR) or looser (0.5 ATR) validation.

### Solution

Converted the hardcoded value into a user input.

* **Input Name:** `Rescue Mode: Min Impulse (xATR)`
* **Default:** `0.7` (The "sweet spot" found during testing).
* **Location:** Settings -> Evidence & Gates (near `Rescue Vol`).
* **Logic:** `isImpulse = bodySize > (atr * rescueImpulseATR)`

---

## 3. Feature: Live ATR Display

**User Request:** "Display in the still empty fields in the table the current ATR."

### Solution

Updated the **Strategy Status Table** (top right of chart).

* **New Field:** Added "ATR" to Column 5.
* **Value:** Displays realtime ATR, formatted to the chart's tick precision.
* **Utility:** Allows traders to instantly see the current volatility reading without adding a separate indicator, helping to visualize what "1 ATR" means for Stops/Impulses.

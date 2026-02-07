# Getting Started with SkippALGO Strategy in TradingView

**Date:** 06 Feb 2026
**Version:** v6.2

## Introduction

This guide explains how to transition from the **SkippALGO Indicator** (signals only) to the **SkippALGO Strategy** (backtesting and trade management). Unlike the indicator, the strategy file simulates specific entry and exit rules, allowing you to see historical performance and potential outcomes.

## 1. How to Add the Strategy Script

1. **Open Pine Editor**: At the bottom of your TradingView interface, click the tab labeled `Pine Editor`.
2. **Paste Code**: Copy the entire content of the `SkippALGO_Strategy.pine` file and simple paste it into the editor window (delete any default code first).
3. **Add to Chart**: Click the **"Add to chart"** button in the top right corner of the editor panel.
    * *Result*: You will see standard blue (Long) and red (Short) arrows appear on your chart candles where trades would have occurred.

## 2. Visualizing Your Risk (TP & SL)

Once a position is open (on the chart), the Algo draws lines to show your active risk parameters:

* 🔴 **Red Line (Stop Loss)**: The price level where the trade will be closed to prevent further loss.
* 🟢 **Green Line (Take Profit)**: The target price level where profits will be secured.
* 🟠 **Orange Line (Trailing Stop)**: If active, this line trails behind price to lock in profits as the trend continues.

*Note: These lines act as a visual confirmation of what the internal logic is doing.*

## 3. The "Automation" Reality Check

New users often assume that connecting a broker (like IBKR) to TradingView allowing the Strategy setup to trade automatically. **This is not the case.**

### The Limitation

* **Trading Panel**: The manual trading buttons (Buy/Sell) connect directly to your broker (IBKR).
* **Pine Strategy**: The script runs on TradingView's servers/browser and **does not have permission** to click those manual buttons for you.

### How Automation Actually Works

To automate execution with IBKR (or any broker) via TradingView, you generally need three components:

1. **The Trigger**: A TradingView **Alert** created from your Strategy.
2. **The Messenger**: A **Webhook URL** entered in the Alert settings.
3. **The Executor**: A 3rd-party bridge service (e.g., *Capitalise.ai*, *3Commas*, *TradersPost*) that receives the Webhook signal and then sends the API order to IBKR.

### Recommended Beginner Workflow

Do not rush into complex automation. Start with this workflow:

1. **Validation**: Use the **Strategy Tester** tab (next to Pine Editor) to verify that your settings would have been profitable on recent data.
2. **Signaling**: Set an Alert on the Strategy to notify you (App/Popup/Email) when a signal triggers.
3. **Execution**: When the alert fires:
    * Check the chart.
    * Verify the setup.
    * Manually execute the trade in your IBKR Trading Panel.

This "Semi-Automated" approach is safer and helps you learn the Algo's personality before trusting it with unattended money.

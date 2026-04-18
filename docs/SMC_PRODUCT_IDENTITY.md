# SMC Long-Dip Suite — Product Identity

> Last updated: 2026-04-18 (WP-21 / Product Identity Final Freeze)

## Three Product Sentences

1. **What:** A TradingView indicator suite that detects institutional buying
   zones and enriches them with live regime, news, and earnings intelligence.
2. **For whom:** Active US equity traders who want data-driven confirmation
   before entering long-dip setups.
3. **Why different:** The only SMC system that blends 3 live data providers into
   a deterministic trust-tier quality assessment — not just chart drawings.

## One-Liner

"The institutional-grade long-dip specialist for US equities — powered by live regime, news, and earnings intelligence."

## What it is

A TradingView indicator suite that detects institutional buying zones (Order Blocks, Fair Value Gaps) and enriches them with live market data from 3 data providers (Databento, FMP, Benzinga). It tells you not just WHERE a setup is, but WHETHER to trust it based on regime, news, earnings, and signal quality.

## What it is NOT

- Not a generic SMC indicator (not "another BOS/CHOCH script")
- Not a short-selling system (long-only, short planned separately)
- Not a signal service (no trade recommendations)
- Not a backtesting framework (the strategy is a companion, not the core)
- Not a replacement for trading education

## Target users

- Active US equity traders who understand SMC concepts
- Traders who want more than chart drawings — real data integration
- Intermediate to advanced users willing to learn a system

## Product family

| Product | Role | Tier |
|---|---|---|
| SMC Long-Dip Suite v7 | Main indicator (zones, hero card, alerts) | Lite |
| SMC Long-Dip Dashboard v7 | Dashboard companion | Pro |
| SMC Long-Dip Strategy v7 | Strategy / backtesting | Pro |
| SMC Event Overlay | Macro event markers | Pro |

## Hero Surface (frozen — WP-14)

The **hero surface** is the primary user-facing decision point.  It lives in
`SMC_Core_Engine.pine` (Compact Mode) and consists of:

| Element       | Purpose                                    |
|---------------|--------------------------------------------|
| Action        | What to do: WAIT / PREPARE / READY / ENTER |
| Bias          | Directional lean (bullish / bearish)        |
| Quality       | Trust-tier quality assessment               |
| Why now       | Concise reason for the current state        |
| Main risk     | Single most relevant risk factor            |

The hero surface is the **Lite primary reading layer**.  Everything else —
Dashboard, Strategy, Context overlays — is a companion or diagnostic layer
that exists to *explain or execute* the hero decision, not to compete with it.

### Surface Classification

| Surface                   | File                       | Role                        | Tier   |
|---------------------------|----------------------------|-----------------------------|--------|
| SMC Core Engine           | `SMC_Core_Engine.pine`     | **Hero** (Lite primary)     | Lite   |
| SMC Dashboard             | `SMC_Dashboard.pine`       | Companion (Pro diagnostics) | Pro    |
| SMC Long Strategy         | `SMC_Long_Strategy.pine`   | Companion (execution)       | Pro    |
| SMC Event Overlay         | `SMC_Event_Overlay.pine`   | Companion (macro context)   | Pro    |
| SMC HTF Confluence        | `SMC_HTF_Confluence.pine`  | Research (multi-TF)         | Audit  |
| SMC Liquidity Structure   | `SMC_Liquidity_Structure.pine` | Research (liquidity map) | Audit  |
| SMC *_Context overlays    | `SMC_*_Context.pine`       | Research (domain deep-dive) | Audit  |

**Roles:**
- **Hero** — the only surface the end-user *must* read.
- **Companion** — extends the hero with depth; operator-only bindings.
- **Research / Audit** — internal development and measurement surfaces.

## Key differentiators

1. **Live market intelligence** — VIX, CPI events, earnings, news sentiment
2. **Trust-Tier system** — deterministic 4-level quality assessment
3. **Regime-aware trading** — RISK_OFF = reduced exposure
4. **10 granular alertconditions** — not just "Buy" / "Sell"
5. **Backend pipeline** — 10 enrichment modules, 3 providers, 4500+ tests

## What we do NOT compete on

- Visual beauty (LuxAlgo wins on aesthetics)
- Simplicity (ICT community scripts are simpler)
- Feature count (we have fewer visible features, more data depth)

## Naming

- Product name: **SMC Long-Dip Suite**
- Short name: "SMC Suite" or "SMC v7"
- Pine script title: "SMC Long-Dip Suite v7"
- Library: `smc_micro_profiles_generated`
- Never: "SMC Core" alone (too generic), "SMC Decision Board" (old name), "SkippALGO" (deprecated)

---

## Explicit Non-Goals (WP-21 — Final Freeze)

The following features and directions are **permanently out of scope** for the
SMC Long-Dip Suite.  Adding any of these requires a new product identity
review.

### Feature Exclusion List

| Excluded Feature                   | Reason                                  |
|------------------------------------|-----------------------------------------|
| Short-selling / inverse positions  | Product is long-only by design          |
| Crypto / Forex asset coverage      | US equities only                        |
| AI / ML trade recommendations      | Deterministic trust-tier, not ML-based  |
| Copy-trading / signal service      | Educational overlay, not financial advice|
| Portfolio management / allocation  | Single-ticker analysis only             |
| Options / derivatives strategies   | Equity spot focus                       |
| Automated order execution          | Indicator suite, not a bot              |
| Social trading features            | No social layer planned                 |
| Mobile app / standalone UI         | TradingView-native only                 |

### Scope Boundaries

- **One ticker at a time** — the suite analyzes a single symbol. Multi-symbol
  screening happens in the terminal, not in TradingView.
- **Long-only** — short setups may exist as a separate product later, never
  inside this suite.
- **TradingView-native** — no external app, web portal, or standalone desktop
  client.
- **No trade automation** — alerts inform; they never place orders.
- **Deterministic** — all signals must be reproducible from the same inputs.
  No randomness, no online learning.

### Identity Lock

This document is **frozen** as of WP-21.  Changes to:
- Product sentences
- Hero surface definition
- Surface classification
- Feature exclusion list

…require a formal product identity review with documented rationale.

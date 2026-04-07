# SMC Product Rescue Playbook

## Status

Draft

## Date

2026-04-07

## Purpose

This document turns the current product review into three concrete deliverables:

1. a prioritized rescue backlog for the next two SMC TradingView releases,
2. a visible-copy system for public and operator surfaces,
3. a screen-by-screen first-run redesign plan for Core, Dashboard, and Strategy.

It is intentionally SMC-only. It does not cover IBKR, terminal modules, or SkippALGO platform work outside the SMC TradingView mainline.

## Evidence Base

- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-tradingview-r1-1-migration-and-operator-guide.md`
- `docs/smc-lite-pro-product-cut.md`
- `tests/test_tradingview_decision_first_ui.py`
- `automation/tradingview/reports/screenshots/2026-04-07T19-12-02-525Z-SMC Dashboard-inputs.png`

## Direction

The strategic decision for the next phase is simple:

1. `SMC_Core_Engine.pine` is the only public first-run surface.
2. `SMC_Dashboard.pine` is a linked companion surface, not a public first-touch surface.
3. `SMC_Long_Strategy.pine` is a pro execution surface, not an onboarding surface.
4. Public value must be visible before the user learns any operator mechanics.
5. Internal transport language stays out of public-facing copy.

## Part 1 - Prioritized Rescue Backlog

## Release R1.2 - Make It Feel Like A Product

Goal: remove first-contact friction and make the SMC mainline look and behave like one coherent product.

| Pri | Outcome | Change | Success Signal | Primary Files |
| --- | --- | --- | --- | --- |
| P0 | Lite becomes real default | Make the decision-first hero surface the visible first-run default instead of a hidden visual toggle. | A new user sees Action, Why now, Main risk, and Confidence without touching settings. | `SMC_Core_Engine.pine`, `docs/smc-tradingview-screen-spec.md`, `tests/test_tradingview_decision_first_ui.py` |
| P0 | Public path no longer leaks integration mechanics | Treat Dashboard and Strategy as advanced linked surfaces in onboarding, docs, and validation flows until raw binding friction is no longer exposed. | Public demos, screenshots, and docs start with Core only. | `README.md`, `docs/smc-tradingview-r1-1-migration-and-operator-guide.md`, `docs/smc-validation-status.md`, `automation/tradingview/` |
| P0 | Public copy stops sounding internal | Remove visible public-adjacent terms like `operator`, `BUS`, `diagnostics`, `bindings hidden`, and similar transport language from user-facing labels. | A retail trader can describe the product in trading language rather than implementation language. | `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`, docs |
| P0 | Visual hierarchy becomes obvious | Enforce one hero decision, one risk block, and a lower overlay budget for first-run screenshots and default chart states. | The first screenshot reads in under 3 seconds. | `SMC_Core_Engine.pine`, validation screenshots, screen spec |
| P1 | Dashboard becomes a brief before it becomes a table | Recast the default Dashboard surface as a short decision brief and push audit depth behind an explicit expert view. | Default Dashboard rows feel like explanation, not diagnosis. | `SMC_Dashboard.pine`, `docs/smc-tradingview-screen-spec.md`, tests |
| P1 | Strategy setup becomes readable | Keep visible controls to a small execution setup block and frame the rest as expert mapping only. | A user can explain the purpose of Strategy without seeing raw state wiring first. | `SMC_Long_Strategy.pine`, operator guide, tests |
| P1 | Product validation uses product surfaces | Stop using editor-only screenshots as product evidence. Capture rendered chart states for Core, Dashboard, and Strategy. | Every release review contains real user-facing screenshots. | `automation/tradingview/`, docs, reports |

### R1.2 Exit Criteria

1. Core is the only default onboarding entry point.
2. The first-run screenshot set contains real chart surfaces, not Pine editor captures.
3. Public copy no longer reveals internal plumbing.
4. Dashboard default stays under a short readable row budget.
5. Strategy reads as an execution wrapper, not a transport map.

## Release R1.3 - Earn Trust And Differentiation

Goal: turn the cleaned-up product into a sharper premium system with clearer trust semantics and a stronger market identity.

| Pri | Outcome | Change | Success Signal | Primary Files |
| --- | --- | --- | --- | --- |
| P0 | Confidence feels trustworthy | Move synthetic numeric precision out of the primary hero and lead with a confidence tier plus a plain-language explanation. | Users can answer "How much should I trust this?" without needing score semantics. | `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, screen spec |
| P0 | Brand becomes memorable | Unify public naming for the three surfaces and separate market-facing names from internal implementation names. | One consistent naming family appears in UI, docs, screenshots, and publish flows. | public labels, docs, README |
| P1 | Dashboard earns its premium role | Give the linked companion surface a stronger explanatory point of view: context, pressure, event risk, and trade plan in trader language. | Dashboard feels like a premium explanation layer, not just a tidy row regrouping. | `SMC_Dashboard.pine`, screen spec |
| P1 | Strategy becomes a premium execution wrapper | Translate wrapper controls into execution language and make the expert mapping section visually secondary. | Strategy feels like a plan executor, not a technical add-on. | `SMC_Long_Strategy.pine` |
| P1 | Trust and proof are aligned | Add canonical product screenshots and release evidence that show visible UX quality, not only compile and binding correctness. | Release notes can prove product quality with visuals, not only tests. | docs, release manifests, tradingview validation |
| P2 | Differentiation is visible in 30 seconds | Document and validate the unique promise: action-first, risk-explicit, context-explained, operator depth only when requested. | External reviewer can summarize the difference from generic SMC scripts in one sentence. | docs, screenshots, onboarding copy |

### R1.3 Exit Criteria

1. Public naming is consistent across UI, docs, and validation outputs.
2. Confidence language is plain and believable.
3. Companion and execution surfaces feel premium, not merely technical.
4. The product can be demonstrated without explaining internal transport or setup mechanics first.

## Part 2 - Visible Copy System

## Messaging Rules

1. Lead with the trading decision.
2. Explain the reason in market language.
3. Name the main risk explicitly.
4. Keep transport, pipeline, and binding language off public surfaces.
5. Use one term per concept across all three surfaces.

## Public Naming Recommendation

Use two layers of naming instead of mixing internal and public terms.

| Layer | Recommended Name |
| --- | --- |
| Masterbrand | SkippALGO |
| TradingView product family | SMC |
| Public surface 1 | SMC Core |
| Public surface 2 | SMC Decision Board |
| Public surface 3 | SMC Execution |
| Internal names retained in code/docs when needed | Core Engine, Dashboard, Long Strategy |

This keeps repo continuity while giving the market-facing product a cleaner spoken language.

## Terms To Avoid On Public Surfaces

Avoid these terms outside expert or audit contexts:

- `BUS`
- `operator`
- `diagnostics`
- `bindings`
- `pack`
- `row`
- `source kind`
- `strict gate`
- `engine detail`

## Core Copy Recommendations

| Current | Recommended | Why |
| --- | --- | --- |
| `SMC Core Engine` | `SMC Core` | Product name is shorter and sounds intentional. |
| `Lite Surface` | `Focus View` | Sounds like a product mode, not a technical reduction. |
| `User Preset` | `Trading Style` | User benefit is clearer. |
| `Show companion detail` | `Show Decision Brief` | Explains purpose, not architecture. |
| `Trust: High \| Score 76/100` | `Confidence: High` | Keep primary trust language human and reduce pseudo-precision. |
| `Why now` | `Why now` | Keep. It is strong and readable. |
| `Main risk` | `Main risk` | Keep. It is direct and credible. |

### Core Hero Text Recommendation

Use this order:

1. Action
2. Bias
3. Confidence
4. Why now
5. Main risk

Recommended example:

```text
Action: Prepare long
Bias: Bullish
Confidence: High
Why now: Reclaim held inside active support
Main risk: Thin short-term participation
```

Keep raw numeric score in expert or audit contexts only.

## Dashboard Copy Recommendations

| Current | Recommended | Why |
| --- | --- | --- |
| `SMC Dashboard` / `SMC Dash` | `SMC Decision Board` | Sounds like a premium companion, not a dev shorthand. |
| `Surface Mode` | `View` | Shorter and more product-like. |
| `Companion Summary` | `Decision Brief` | Faster to understand and stronger for conversion. |
| `Pro Diagnostics` | `Audit View` | Cleaner expert term than diagnostics. |
| `Show Companion Table` | `Show Brief Panel` | Describes the visible object. |
| `Show Trade Levels` | `Show Trade Plan` | Sounds more intentional than levels. |
| `Highlight Actionable State` | `Highlight Live Setup` | More trader-readable. |
| `Companion Summary \| Operator bindings hidden` | `Decision Brief \| Linked setup active` | Removes internal language from the public default. |
| `v5.5d Pro Diagnostics \| operator companion` | `Audit View \| Expert review` | Keeps expert framing without exposing implementation posture. |
| `Why Now / Why Blocked` | `Why now` | The state itself can imply blocked when needed. |
| `Short-term Flow` | `Short-term pressure` | More natural trader language. |

### Dashboard Row Language Principles

1. Use plain directional language.
2. Prefer `supports long`, `mixed`, `against long`, `clear`, `thin`, `not ready`.
3. Avoid exposing implementation categories unless the user intentionally enters expert view.

## Strategy Copy Recommendations

| Current | Recommended | Why |
| --- | --- | --- |
| `SMC Long Strategy` | `SMC Execution` | Describes product purpose instead of a narrow implementation name. |
| `1. Strategy Setup` | `1. Execution Setup` | Easier to scan. |
| `2. Wrapper Trade Plan` | `2. Trade Plan` | Public copy should not expose wrapper mechanics. |
| `3. Strategy - Operator Bindings - Entry States` | `3. Expert Mapping - Entry States` | Makes the advanced nature explicit. |
| `4. Strategy - Operator Bindings - Trade Plan` | `4. Expert Mapping - Trade Plan` | Same reasoning. |
| `Execution Stage` | `Entry Stage` | Shorter and clearer. |
| `Minimum Quality Score` | `Minimum Setup Quality` | Focuses on the user decision, not the metric implementation. |
| `Take Profit (R)` | `Profit Target (R)` | More familiar trader wording. |
| `Use Take Profit` | `Enable Profit Target` | More natural toggle language. |
| `Execution Trigger` | `Entry Price` | More legible on chart. |
| `Execution Invalidation` | `Stop Loss` | Trader language beats internal execution terminology here. |
| `Execution Take Profit` | `Profit Target` | Keep language aligned. |

## Part 3 - First-Run Redesign Plan

## First-Run Product Rule

Only one surface is allowed to carry the first-run experience: `SMC_Core_Engine.pine`.

Dashboard and Strategy remain linked follow-up surfaces until the operator-only mapping story is either hidden, templated, or structurally separated from the public path.

## Surface CE-1 - SMC Core First-Run

### CE-1 Objective

Within 3 seconds the user understands:

1. what to do now,
2. why the product says that,
3. what can go wrong.

### CE-1 Default Visible Elements

- one hero card,
- one active zone,
- one primary risk block when actionable,
- at most one entry or exit label per bar.

### CE-1 Default Hidden Elements

- debug overlays,
- deep diagnostics,
- object-history clutter,
- secondary helper labels,
- expert-only precision signals.

### CE-1 Layout Recommendation

```text
+----------------------------------+
| ACTION        PREPARE LONG       |
| Bias          Bullish            |
| Confidence    High               |
| Why now       Reclaim held       |
| Main risk     Thin participation |
+----------------------------------+
```

### CE-1 First-Run Settings Recommendation

Visible by default:

1. Trading Style
2. Focus View
3. Risk Profile
4. Alert Mode
5. Show Decision Brief

All other settings belong in an advanced section.

### CE-1 Acceptance

1. The chart reads like a product, not a toolbox.
2. The user can repeat the action without reading docs.
3. The default screenshot is clean enough for a landing page.

## Surface DB-1 - SMC Decision Board Linked Brief

### DB-1 Objective

Explain the Core decision in a premium companion layer without forcing the user into audit semantics.

### DB-1 Product Position

This is not the first surface a user should see.

This is the second surface the user earns after the Core already proved value.

### DB-1 Default Visible Elements

- Action
- Why now
- Trade plan
- Structure
- Session
- Event risk
- Data quality
- Short-term pressure

### DB-1 Default Hidden Elements

- audit sections,
- debug rows,
- raw gating labels,
- internal grouping names,
- any implementation wording that sounds like transport or QA.

### DB-1 Layout Recommendation

```text
+--------------------------------------+
| Action             Enter long        |
| Why now            Setup confirmed   |
| Trade plan         Entry / stop / tp |
| Structure          Supports long     |
| Session            Mixed             |
| Event risk         Clear             |
| Data quality       Thin              |
| Short-term pressure Neutral          |
+--------------------------------------+
```

### DB-1 Binding Reality Rule

If TradingView still exposes raw source mapping in settings, then the public product story must not pretend that this is a normal first-run script.

That means:

1. keep this surface out of public first-touch flows,
2. show it only as an advanced linked companion,
3. maintain a separate operator setup guide instead of blending setup friction into the product story.

### DB-1 Acceptance

1. Default brief stays short.
2. Expert audit is explicit opt-in.
3. The visible default does not read like a QA table.

## Surface LS-1 - SMC Execution Linked Setup

### LS-1 Objective

Turn Strategy into a premium execution wrapper around the Core decision, not a confusing script that opens with transport controls.

### LS-1 Product Position

This is a pro follow-up surface for users who already trust the Core decision and want execution structure.

### LS-1 Default Visible Elements

- Entry Stage
- Minimum Setup Quality
- Profit Target toggle
- Profit Target multiple

### LS-1 Expert Section

All source mapping stays in an explicit `Expert Mapping` section.

If TradingView limitations prevent full hiding, then the product documentation must keep calling this a pro linked surface rather than a general user surface.

### LS-1 Layout Recommendation

```text
+--------------------------------------+
| Entry Stage          Strict          |
| Minimum Quality      High            |
| Profit Target        Enabled         |
| Target Multiple      2.0R            |
+--------------------------------------+
```

Chart outputs:

- Entry Price
- Stop Loss
- Profit Target

### LS-1 Acceptance

1. The first visible controls are execution decisions, not mappings.
2. A trader can explain what the script does in one sentence.
3. Expert mapping is clearly secondary.

## Validation Changes Required For This Playbook

1. Add release screenshots for rendered Core, Dashboard brief, Dashboard audit, and Strategy execution views.
2. Add regression checks for public copy so internal words do not leak back into public defaults.
3. Keep separate validation expectations for public surfaces and operator-only surfaces.

## Non-Negotiable Rules

1. Do not use Pine editor screenshots as proof of product quality.
2. Do not market linked operator surfaces as if they were frictionless public scripts.
3. Do not put internal transport vocabulary on public-first screens.
4. Do not let the most differentiated surface live behind an off-by-default toggle.

## Short Version

If only three things are done next, they should be these:

1. make Core the true first-run product,
2. remove internal language from visible defaults,
3. demote Dashboard and Strategy to clearly labeled advanced linked surfaces until their setup friction is structurally hidden.

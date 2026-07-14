# Pine Script Naming Convention (SSOT)

> **OWNER: @preuss_steffen — only the owner changes this rule.**
> Everyone else follows it. Changes to the convention itself require the owner's
> explicit approval in the PR that edits this file.

This document is the single source of truth for how TradingView Pine scripts in
this repo are named. It exists because the naming drifted into chaos (one engine
existed under three different names — saved name, code title, and legend label
all disagreed, plus a duplicate copy), which made the dashboard impossible to
wire and wasted hours. Enforced by
[`tests/test_pine_script_naming_convention.py`](../tests/test_pine_script_naming_convention.py).

## The core rule: one identity on all three surfaces

Every user-facing script has **one** name that is identical on the three places
the user sees it:

1. **Saved script name** — the name in TradingView's "Open my script" list and
   the Pine Editor title dropdown.
2. **Code title** — the first argument of `indicator(...)` / `strategy(...)`.
3. **Display / legend** — what shows on the chart and inside consuming panels.

The repo can only assert surface #2 (the code title); the enforcement test pins
it. Surfaces #1 and #3 are set on TradingView and must be kept equal to the code
title by whoever saves the script (see the operator checklist below).

## Main product family

The primary long-dip products share the prefix **`SMC Long-Dip`** so the
indicator and its strategy read as one family:

| Component | Repo file | Canonical code title (== saved name == display) | Shorttitle (≤10, legend) |
|-----------|-----------|--------------------------------------------------|--------------------------|
| Engine / indicator | `SMC_Core_Engine.pine` | **SMC Long-Dip Suite v7** | LD Suite7 |
| Strategy | `SMC_Long_Strategy.pine` | **SMC Long-Dip Strategy v7** | — (strategy) |
| Dashboard | `SMC_Dashboard.pine` | **SMC Long-Dip Dashboard v7** | LD Dash7 |
| Mobile | `SMC_Mobile_Dashboard.pine` | **SMC Long-Dip Mobile v7** | LD Mobile7 |

## Version number

- **`v7`** is the product-line major version and stays in the name.
- The **visible, auto-incrementing** version the user sees is TradingView's own
  save revision, shown as `· N.0` next to the name (e.g. `SMC Long-Dip Suite v7
  · 41.0`). It bumps on every save — no manual version-string maintenance.
- Bump the `v7` major only on a deliberate product-line break, in this file
  first (owner change), then across the family together.

## Component / overlay scripts

Secondary modules (context, overlay, and helper indicators — e.g.
`SMC_Event_Overlay.pine`, `SMC_Liquidity_Context.pine`) are **not** part of the
long-dip product name. They keep concise, descriptive `SMC <Component>` titles,
and — like the main products — their saved name must equal their code title.
They are catalogued in the surface registry
[`scripts/smc_bus_manifest.py`](../scripts/smc_bus_manifest.py).

## Libraries

Private/generated libraries keep **snake_case** names (`smc_utils`, `smc_draw`,
`smc_engine_private`, `smc_micro_profiles_generated`, …). They are internal
imports, never added to a chart by the user, so the product-name rule does not
apply. Their versioning is the published library version resolved by
`import user/lib/N`.

## No duplicates

There is exactly **one** saved script per product. Never keep a second copy
under a different name (the "SMC Core" / "SMC Core Engine" duplicate was the
root of the wiring confusion). If a stale duplicate exists, delete it — do not
rename around it.

## Operator checklist (when saving a script to TradingView)

1. The saved script name must equal the `indicator()/strategy()` code title.
2. If TradingView restored a stale unsaved editor draft, clear it (Cmd+A →
   Delete) and paste the current repo source before saving, so the saved
   version matches the repo SSOT.
3. One product = one saved script. Delete duplicates.

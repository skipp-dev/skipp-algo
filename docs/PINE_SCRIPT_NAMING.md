# Pine Script Naming Convention (SSOT)

> **OWNER: @preuss_steffen — only the owner changes this rule.**
> Everyone else follows it. Changes to the convention itself require the owner's
> explicit approval in the PR that edits this file.

This document is the single source of truth for how TradingView Pine scripts in
this repo are named. It exists because the naming drifted into chaos: the engine
appeared under several disagreeing names (a saved script name, a code title, a
legend label, and a duplicate copy that all disagreed), which made the dashboard
impossible to wire and wasted hours. Enforced by
[`tests/test_pine_script_naming_convention.py`](../tests/test_pine_script_naming_convention.py).

## Three tiers — do not mix them up

A script has names on three different tiers. The mistake that caused the chaos
was treating them as interchangeable. They are **not** — each has its own rule.

### Tier 1 — user-visible identity: ONE name, always identical

The name the user actually sees on TradingView must be **one and the same** in
all three places it appears:

- **Code title** — the first argument of `indicator(...)` / `strategy(...)`.
- **TV saved script name** — the name in "Open my script" and the editor title.
- **Chart / dashboard display** — what shows in the legend and consuming panels.

Format: **`SMC Long-Dip <Component> v7`**. The main products share the
`SMC Long-Dip` prefix so the indicator and its strategy read as one family.

### Tier 2 — shorttitle: a systematic, documented abbreviation

The `indicator()/strategy()` **shorttitle** (2nd arg) is what TradingView shows
in the compact legend. TradingView **hard-limits it to 10 characters**
(`SHORT_TITLE_TOO_LONG` above that), so it **cannot** be identical to the Tier-1
name (`SMC Long-Dip Suite v7` is 21 chars). It is therefore an *abbreviation* —
but a **fixed, systematic** one, never a third free-form name:

> **Shorttitle rule:** `LD <Component>7` — drop `SMC`, abbreviate `Long-Dip → LD`,
> keep the component word and the major version. (Suite → `LD Suite7`,
> Dashboard → `LD Dash7`, Mobile → `LD Mobile7`.) A `strategy()` may omit the
> shorttitle.

### Tier 3 — repo file name: an internal identifier (NOT user-facing)

The repo `.pine` file name (e.g. `SMC_Core_Engine.pine`) is a **git-internal
identifier**, like a library's snake_case name. The user never sees it on
TradingView, and it is referenced by ~130 files (tests, manifest, publishers,
workflows), so it is deliberately **not** renamed to match the title — that
churn would buy zero user-visible benefit and real regression risk. It does not
need to equal the Tier-1 name; instead the file → identity mapping is documented
here so it is never ambiguous.

## Canonical mapping — main products

| Repo file (Tier 3, internal) | User-visible identity (Tier 1) | Shorttitle (Tier 2) |
|------------------------------|--------------------------------|---------------------|
| `SMC_Core_Engine.pine` | **SMC Long-Dip Suite v7** | LD Suite7 |
| `SMC_Long_Strategy.pine` | **SMC Long-Dip Strategy v7** | — (strategy) |
| `SMC_Dashboard.pine` | **SMC Long-Dip Dashboard v7** | LD Dash7 |
| `SMC_Mobile_Dashboard.pine` | **SMC Long-Dip Mobile v7** | LD Mobile7 |

## Version number

- **`v7`** is the product-line major version and stays in the Tier-1 name.
- The **visible, auto-incrementing** version the user sees is TradingView's own
  save revision, shown as `· N.0` next to the name (e.g. `SMC Long-Dip Suite v7
  · 41.0`). It bumps on every save — no manual version-string maintenance.
- Bump the `v7` major only on a deliberate product-line break, in this file
  first (owner change), then across the family together.

## Component / overlay scripts

Secondary modules (context, overlay, and helper indicators — e.g.
`SMC_Event_Overlay.pine`, `SMC_Liquidity_Context.pine`) are **not** part of the
long-dip product name. They keep concise, descriptive `SMC <Component>` Tier-1
titles, and their TV saved name must equal that title. They are catalogued in
the surface registry
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

1. The saved script name (Tier 1) must equal the `indicator()/strategy()` code
   title. The shorttitle (Tier 2) follows the `LD <Component>7` rule.
2. If TradingView restored a stale unsaved editor draft, clear it (Cmd+A →
   Delete) and paste the current repo source before saving, so the saved
   version matches the repo SSOT.
3. One product = one saved script. Delete duplicates.

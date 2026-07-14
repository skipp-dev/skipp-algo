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

## The rule: one name, shown everywhere

Every user-facing script has **exactly one name**, identical on every surface
the user sees:

- **Code title** — the first (and only) string argument of `indicator(...)` /
  `strategy(...)`.
- **TV saved script name** — the name in "Open my script" and the editor title.
- **Chart / dashboard display (legend)** — what shows on the chart and in
  consuming panels.

The three are kept identical by **not fighting them apart**:

- **No shorttitle.** The `indicator()/strategy()` shorttitle (2nd positional
  string) is TradingView's ≤10-char legend label — a *different, shorter* name.
  We **omit it entirely**. With no shorttitle, TradingView shows the full title
  in the legend, so title == saved name == display. One name, never a cryptic
  abbreviation.
- **No version string in the name.** No `v7`, no `v1`. The visible,
  auto-incrementing version is **TradingView's own save revision** appended by
  TradingView next to the name (it bumps on every save). The name stays clean;
  the number comes from TradingView.

Main products share the **`SMC Long-Dip`** prefix so the indicator and its
strategy read as one family.

## Canonical names — main products

| Repo file (internal, see below) | Name (code title == saved name == display) |
|---------------------------------|--------------------------------------------|
| `SMC_Core_Engine.pine` | **SMC Long-Dip Suite** |
| `SMC_Long_Strategy.pine` | **SMC Long-Dip Strategy** |
| `SMC_Dashboard.pine` | **SMC Long-Dip Dashboard** |
| `SMC_Mobile_Dashboard.pine` | **SMC Long-Dip Mobile** |

## Repo file name is internal (NOT user-facing)

The repo `.pine` file name (e.g. `SMC_Core_Engine.pine`) is a **git-internal
identifier**, like a library's snake_case name. The user never sees it on
TradingView, and it is referenced by ~130 files (tests, manifest, publishers,
workflows), so it is deliberately **not** renamed to match the title — that
churn would buy zero user-visible benefit and real regression risk. The file →
name mapping in the table above is the documented cross-reference.

## Component / overlay scripts

Secondary modules (context, overlay, and helper indicators) follow the same
rule: **one descriptive `SMC <Something>` name**, no shorttitle, no version
string, and the name must tell the user what the script does. Current set:

| Repo file | Name |
|-----------|------|
| `SMC_Breakout_Overlay.pine` | SMC Breakout Overlay |
| `SMC_Event_Overlay.pine` | SMC Event Overlay |
| `SMC_Exit_Signal.pine` | SMC Exit Signal |
| `SMC_HTF_Confluence.pine` | SMC HTF Confluence |
| `SMC_Hold_Manager.pine` | SMC Hold Manager |
| `SMC_Imbalance_Context.pine` | SMC Imbalance Context |
| `SMC_Liquidity_Context.pine` | SMC Liquidity Context |
| `SMC_Liquidity_Structure.pine` | SMC Liquidity Structure |
| `SMC_Orderflow_Overlay.pine` | SMC Orderflow Overlay |
| `SMC_Profile_Context.pine` | SMC Profile Context |
| `SMC_Session_Context.pine` | SMC Session Context |
| `SMC_Setup_Check.pine` | SMC Setup Check |
| `SMC_Structure_Context.pine` | SMC Structure Context |
| `SMC_VRVP_Overlay.pine` | SMC Volume Profile Overlay |
| `SkippALGO_Confluence.pine` | SMC Confluence Hub |
| `SMC_TV_Bridge.pine` | SMC Regime & News |

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

1. The saved script name must equal the `indicator()/strategy()` code title —
   no shorttitle, no version string in the name.
2. If TradingView restored a stale unsaved editor draft, clear it (Cmd+A →
   Delete) and paste the current repo source before saving, so the saved
   version matches the repo SSOT.
3. One product = one saved script. Delete duplicates.

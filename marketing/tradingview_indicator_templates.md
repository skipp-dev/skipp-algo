# TradingView Indicator Templates — SMC Quickstart Presets

> **Status:** W1.4c (Plan §1.4). Manual export checklist — TradingView
> Indicator Templates can only be created via the TV UI; this file
> documents the authoring contract so the three templates stay in sync
> with the Pine `quickstart_preset` enum and its BUS contract.
> **Owner:** Steffen.
> **Source of truth for values:** `preset_effective_*(...)` helpers in
> [`SMC_Core_Engine.pine`](../SMC_Core_Engine.pine) (pinned by
> `tests/test_tradingview_decision_first_ui.py::test_core_engine_quickstart_preset_publishes_effective_defaults_contract`).

## Why an Indicator Template at all

The Pine `quickstart_preset` enum already publishes effective defaults
via the BUS plot contract (`BUS PresetClassCode`, `BUS PresetRvolMin`,
…). What the enum does **not** do today: load the curated **secondary
inputs** (event-gate flags, ETH window, ATR multipliers) that aren't
yet behind the preset wire — this is where TradingView Indicator
Templates fill the gap.

Templates are layered *on top* of the Pine input — pick the preset,
then load the matching template. No code change required to update a
template; this is pure operator workflow.

Reference: <https://www.tradingview.com/support/solutions/43000543048-what-are-indicator-templates/>.

## Three templates to ship

For each template, capture the **same** chart frame (default symbol,
default timeframe) so the screenshots stay comparable.

### Template 1 — `SMC · Mega-Cap US Tech`

| Input                          | Value                                  |
|--------------------------------|----------------------------------------|
| Quickstart Preset              | `Mega-Cap US Tech`                     |
| Trading Style                  | `Standard`                             |
| Use Relative Volume            | `true`                                 |
| Relative Volume — Good x       | `1.30` (matches preset floor)          |
| Volatility Regime Filter       | `true`                                 |
| Color Theme                    | `Standard`                             |
| Focus View                     | `true`                                 |

Suggested capture symbols: AAPL, MSFT, NVDA on 15m + 1H.
Calibration evidence in tooltip: AMZN/1H Grade A (84% HR, ECE 0.035).

### Template 2 — `SMC · Financial Services`

| Input                          | Value                                  |
|--------------------------------|----------------------------------------|
| Quickstart Preset              | `Financial Services`                   |
| Trading Style                  | `Standard`                             |
| Use Relative Volume            | `true`                                 |
| Relative Volume — Good x       | `1.20`                                 |
| Volatility Regime Filter       | `true`                                 |
| Color Theme                    | `Standard`                             |
| Focus View                     | `true`                                 |

Suggested capture symbols: JPM, BAC, GS on 15m.
Calibration evidence in tooltip: JPM/15m Grade A (82.6% HR).

### Template 3 — `SMC · Energy`

| Input                          | Value                                  |
|--------------------------------|----------------------------------------|
| Quickstart Preset              | `Energy`                               |
| Trading Style                  | `Standard`                             |
| Use Relative Volume            | `true`                                 |
| Relative Volume — Good x       | `1.10`                                 |
| Volatility Regime Filter       | `true`                                 |
| Color Theme                    | `Standard`                             |
| Focus View                     | `true`                                 |

Suggested capture symbols: XOM, CVX on 15m + 1H.
Note: preset publishes `BUS PresetVolRegimeDef = 1` (HIGH) — once the
vol-regime consumer is wired (Plan F3), the regime default will follow
the preset automatically.

## Export checklist (per template)

1. Load `SMC_Core_Engine.pine` on a clean chart in TV.
2. Select the matching `Quickstart Preset`.
3. Apply the input values from the table above. Leave everything else
   at the indicator default.
4. Open the indicator's settings menu → **Templates** → **Save Indicator
   Template As…** → use the exact template name from the table.
5. Verify the template appears under **Templates** with the canonical
   name.
6. (Optional) Open a fresh chart, load the template, and confirm the
   Hero one-liner shows the expected `Top FAM HR%` for the symbol.
7. Capture a screenshot of the Audit View for the marketing landing
   page (`marketing/landing_v0.md`).

## What templates do **not** cover

- BUS values come from Pine, not the template — a template can only
  store *input values*, not the BUS plot wiring. If a future preset
  adds an axis (e.g. ETH window), update the Pine helper first, then
  re-save the template.
- Template names live in TV's user-scope storage. They are not
  versioned in the repo. The values in the table above **are** the
  versioned source of truth.

## Out of scope (W1)

- Auto-export via Playwright — manual save is faster and the TV UI
  contract for templates is undocumented for automation.
- Sharing via TV's "Copy template link" — defer to W2 once the three
  base templates are stable.
- Preset → template auto-load on selection — TV does not expose this.

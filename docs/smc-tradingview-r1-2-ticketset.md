# SMC TradingView R1.2 Ticketset

## Status

Delivered

## Purpose

This ticketset translates the SMC product rescue review into the smallest
practical R1.2 delivery wave for the active TradingView mainline:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`

The objective is not a new engine. The objective is to make the existing
mainline feel like one coherent product on first contact.

## Scope Guardrails

1. SMC-only.
2. No IBKR work.
3. No terminal-stack work.
4. No new producer logic outside the Core.
5. No binding-contract expansion.

## Release Goal

R1.2 is done when a new user can open the SMC mainline and understand within a
few seconds:

1. what the product wants them to do,
2. why that action is currently justified,
3. what the main risk is,
4. which surfaces are public-first versus expert-linked.

## Must-Ship Tickets

| ID | Pri | Ticket | Surfaces | Done When |
| --- | --- | --- | --- | --- |
| R12-01 | P0 | Core Public Copy Cut | Core | Core uses trader-readable labels like `Trading Style`, `Focus View`, `Show Decision Brief`, and a confidence-first hero. |
| R12-02 | P0 | Dashboard Decision Brief Copy Cut | Dashboard | The default linked companion view reads as a decision brief, not as operator plumbing. |
| R12-03 | P0 | Strategy Execution Copy Cut | Strategy | Visible setup controls and outputs read like execution planning rather than wrapper internals. |
| R12-04 | P0 | Public vs Expert Surface Framing | Core, Dashboard, Strategy, Docs | Docs and validation flows clearly separate public-first Core usage from expert-linked Dashboard and Strategy usage. |
| R12-05 | P0 | Product-Surface Validation Evidence | Docs, validation | Release evidence includes rendered chart surfaces for Core, Dashboard brief, Dashboard audit, and Strategy execution. |
| R12-06 | P1 | R1.2 Operator Guide Realignment | Docs | The active operator and strategy guides use the same visible labels as the product. |
| R12-07 | P1 | First-Run Visual QA Cut | Validation, screenshots | Editor captures are explicitly rejected as product evidence; first-run screenshots are clean and chart-first. |

## Ticket Notes

### R12-01 - Core Public Copy Cut

- Keep `compact_mode` visual-only.
- Make `Focus View` the default first-run surface.
- Upgrade visible copy so the first-run surface reads like a product.
- Prioritize `Action`, `Bias`, `Confidence`, `Why now`, `Main risk`.

### R12-02 - Dashboard Decision Brief Copy Cut

- Default dashboard mode should read as a linked decision brief.
- The expert mode should remain available, but clearly framed as expert review.
- Default row labels must avoid transport and operator phrasing.

### R12-03 - Strategy Execution Copy Cut

- Keep the 8-channel executable contract unchanged.
- Focus visible setup on entry stage, minimum setup quality, and profit target.
- Use chart outputs that traders can understand immediately.

### R12-04 - Public vs Expert Surface Framing

- `SMC_Core_Engine.pine` is the only public first-run surface.
- `SMC_Dashboard.pine` is a linked companion surface.
- `SMC_Long_Strategy.pine` is a linked execution surface.
- TradingView publish names align to `SMC Core`, `SMC Decision Board`, and `SMC Execution`.

### R12-05 - Product-Surface Validation Evidence

- Capture rendered chart screenshots, not Pine editor screenshots.
- Validate first-run Core, linked Dashboard brief, expert Dashboard review, and Strategy execution plan.

## Suggested Delivery Order

1. R12-01 Core Public Copy Cut
2. R12-02 Dashboard Decision Brief Copy Cut
3. R12-03 Strategy Execution Copy Cut
4. R12-04 Public vs Expert Surface Framing
5. R12-05 Product-Surface Validation Evidence
6. R12-06 R1.2 Operator Guide Realignment
7. R12-07 First-Run Visual QA Cut

## Executive Rule

If a change improves internal clarity but does not improve first-run product
readability, trust, or visible public/expert separation, it is not an R1.2
ticket.

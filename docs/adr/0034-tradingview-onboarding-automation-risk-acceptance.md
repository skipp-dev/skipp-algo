# ADR-0034: TradingView onboarding automation — risk accepted, dated

Status: accepted (operator decision, 2026-08-31)

## Context

- 2026-08-29, deep research (operator-commissioned): TradingView's Help Center
  states a house rule — "any kind of automatization … not allowed. All our
  features are for manual use only." House-rule rank; it is NOT in the Terms
  of Use full text.
- 2026-08-31, measured at the artifact: beyond the operator-account CI, the
  customer onboarding packages (`SMC-Onboarding-*`, built by the
  `tv-onboarding-packages` workflow) bundle Playwright, playwright-core and a
  Node runtime around `scripts/tv_onboard_consumers.ts` — TradingView
  automation that runs on the customer's machine against the customer's
  account. The 2026-08-29 scope note ("customer not affected") had counted
  only the Chrome extension.
- Manual initial binding is not a customer path: a consumer carries up to 64
  `input.source` rows, and the operator ruled out manual binding long ago
  (restated 2026-08-31). Without the package there is currently no initial
  setup.
- The RECURRING customer path needs no automation — measured 2026-08-31
  (`docs/TRADINGVIEW_CUSTOMER_UPDATE_PATH.md`): producer updates preserve
  bindings; consumer updates reset them and re-applying a customer-saved
  indicator template restores them. Both are ordinary manual use.

## Decision (operator, 2026-08-31)

- **Keep shipping the onboarding package** for the one-time initial setup.
  The risk that TradingView objects to this use is accepted, dated here.
- **Rejected: asking TradingView for permission or partnership.** Operator,
  2026-08-31: "3 ist keine Option." (No rationale recorded; none invented.)
- The automation surface stays deliberately minimal: one-time onboarding
  only. Everything recurring on the customer side is manual by design
  (accept update; apply template).

## Consequences and bounds

- The house rule is Help-Center rank, not contract text; the enforcement
  risk is borne knowingly and is limited to the onboarding step.
- The operator-account CI automation is a separate, pre-existing exposure
  surfaced by the 2026-08-29 research; this ADR covers the customer-side
  package.
- Monitoring, measured 2026-08-31 (operator corrected this ADR's first
  draft, which claimed no TV watching existed): the repo DOES watch
  TradingView weekly — `pine-release-notes-watch` (Mondays 05:30 UTC) diffs
  the Pine release-notes page against a committed snapshot. The Help-Center
  **house-rules page is not among its targets**, and no other watcher covers
  it. For that page — and only that page — the honest label stands:
  UNGESICHERT — verlässt sich auf menschliches Gedächtnis. A rule change
  there is noticed by humans, not by a tripwire; extending the weekly
  watcher to it is the known mechanization, decided separately.

## Addendum 2026-10-04: strategy-report readout on the operator account

- **What:** `scripts/tv_strategy_report_readout.ts` loads the operator's chart,
  shows the (hidden) `SMC Long-Dip Strategy` in the session, switches its
  execution stage and downloads the strategy report through TradingView's own
  "Download data as XLSX". It saves nothing and adds no instance.
- **Why this is a new use:** it extracts backtest results by script. §3 of the
  Terms of Use ("automated data collection … scripts … data gathering and
  extraction tools", quoted in `docs/tv_house_rules_snapshot.md`) is contract
  rank, not house-rule prose; the 2026-08-31 decision above covered the
  one-time customer onboarding only.
- **Decision (operator, 2026-10-04):** asked before the build, the operator
  chose "Ja, bauen und fahren" over a local Python rebuild and over leaving the
  Long-Dip signals unmeasured; a manual readout was ruled out ("Ich mache
  nichts manuell"). The risk is accepted for this use, dated here.
- **Bounds:** operator account only; run on request, no schedule, no workflow;
  first run 5 symbols × 5 stages × 2 session modes on 15m. Not part of any
  customer package.

# TradingView customer update path — measured behavior

**Measured 2026-08-31 by the operator, by hand**, on a test chart with two
private publications (a mechanism-level probe; invite-only publications use the
same publication/update mechanics — named residual assumption):

- `TEST BUS Producer` — indicator plotting `BUS T1`, `BUS T2`
- `TEST BUS Consumer` — two `input.source()` rows bound to the producer's plots

| Case | Action | Consumer's source bindings after accepting the update |
| --- | --- | --- |
| A | new CONSUMER version published, update accepted | **reset to `Close`** |
| B | new PRODUCER version published, update accepted | **preserved** |
| C | both updated in sequence (the release real case) | **reset to `Close`** |
| D | consumer update that ADDS an input | **reset to `Close`** |

## What this pins down

- Accepting an update of a **consumer** script resets that script's own
  `input.source` bindings — even when the update changes no inputs at all
  (case A was a comment-only change).
- Accepting a **producer** update preserves the consumers' bindings (case B):
  plot references survive because the label texts stay stable — the same
  invariant `docs/PINE_SCRIPT_NAMING.md` and the BUS label discipline protect.
  **Scope (operator correction, 2026-08-31 late):** case B changed code only —
  no library import pin moved. TradingView's own banner for a stale library on
  an existing instance says "re-add the indicator", and re-adding the producer
  cascades into removing **every dependent consumer** (Remove dialog, operator
  observation 2026-08-31) — all bindings gone. A producer release that changes
  a library pin is therefore NOT covered by case B; see follow-up G.
- Therefore **"click update" is sufficient exactly for releases that do not
  republish consumer scripts** — and insufficient for any release that does.

## Case E — template restore (measured 2026-08-31, same session)

The operator saved an **indicator template** of the bound setup, repeated
case A (consumer update, bindings reset to `Close`), then re-applied the
template: **the source bindings were restored.**

The consumer-update reset is therefore a two-click recovery — accept update,
apply template — still manual use. Combined verdict: **"click update" suffices
for producer releases without a library-pin change (case B); consumer releases
additionally need "apply template"; producer releases that bump a library pin
are open follow-up G.**
The customer-facing consequence lives in
`docs/tradingview-onboarding/PREPARE_CHART.md`: save the template once,
right after onboarding.

## Open follow-ups (unmeasured)

- **G:** whether accepting a producer update whose new version bumps a library
  import behaves in place (like case B) or forces the re-add path. TV's
  stale-library banner suggests re-add — and re-adding the producer cascades
  removal of all dependents.
- **H:** whether applying the saved indicator template after such a cascade
  restores the full bound set. Case E measured only the single-consumer reset.
- **F:** whether non-source inputs survive consumer updates (scopes the reset;
  not needed for the BUS question).

## Why this document exists

This question had been answered informally months ago ("update suffices") but
was never pinned anywhere in the repo. The absence of a written, dated
measurement is why the question kept resurfacing. Any future change to this
behavior (TradingView platform change, new probe result) belongs HERE, dated,
next to these numbers — see `docs/tradingview-onboarding/PREPARE_CHART.md` for
the binding contract this measures against.

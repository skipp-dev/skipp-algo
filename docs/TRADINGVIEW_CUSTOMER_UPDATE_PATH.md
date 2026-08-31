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
- Therefore **"click update" is sufficient exactly for releases that do not
  republish consumer scripts** — and insufficient for any release that does.

## Open follow-ups (unmeasured)

- **E:** whether re-applying a customer-saved **indicator template** restores
  source bindings after a consumer update. If yes, the reset becomes a
  two-click recovery — still manual use.
- **F:** whether non-source inputs survive consumer updates (scopes the reset;
  not needed for the BUS question).

## Why this document exists

This question had been answered informally months ago ("update suffices") but
was never pinned anywhere in the repo. The absence of a written, dated
measurement is why the question kept resurfacing. Any future change to this
behavior (TradingView platform change, new probe result) belongs HERE, dated,
next to these numbers — see `docs/tradingview-onboarding/PREPARE_CHART.md` for
the binding contract this measures against.

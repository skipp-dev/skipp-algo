# Phase 1 evidence-truth contract

Status: technical truth gates implemented; prospective family paper evidence
not yet accumulated.

## Why this phase exists

The repository contains several valid but non-interchangeable evidence planes.
Modeled triggered-setup returns, paper execution observations and live outcomes
answer different questions. A commercial claim or promotion gate must never
turn one plane into another by renaming a field or variant.

## Evidence classes

| Class | Meaning | May satisfy C12 live promotion? |
|---|---|---|
| `MODELED_OOS` | Out-of-sample modeled return after the documented fixed-cost rule | No |
| `PAPER` | Prospective paper-incubation lifecycle and closed outcome | No |
| `LIVE` | Prospective live-small/live-full lifecycle and closed outcome | Yes, subject to every other gate |

`live_days` and `n_trades` remain compatibility fields, but the C12 consumer
now requires them to exactly match `evidence.LIVE.days` and
`evidence.LIVE.n_closed_outcomes`. A legacy or mismatched row is blocked.

## Variant ownership

`configs/c13/variant_family_map.json` is an explicit registry:

- `family_variants` maps only a commercial signal variant to BOS, OB, FVG or
  SWEEP;
- `non_family_variants` records known execution or operational streams that
  must be ignored rather than misclassified;
- anything in neither section is unknown and fails strict telemetry emission.

`smc_orb_vwap_hold` is intentionally non-family. It represents the Open Prep
execution-promotion bucket and cannot prove a BOS, OB, FVG or SWEEP edge.

## Execution outcome truth

New incubation audit rows carry `evidence_class`. Closed outcome schema v3
adds:

- `outcome_status=closed`;
- `gross_pnl_usd` and backward-compatible `outcome_pnl_usd`;
- `entry_slippage_bps`, anchored at submitted entry versus realized fill;
- `fees_known` and nullable `fees_usd`;
- `net_pnl_usd` only when fees are known;
- `outcome_r_multiple`, anchored at the realized fill.

Missing fees are `null`, never assumed to be zero.

## Automated gates

The daily C13 workflow:

1. requires the committed ownership registry;
2. runs family telemetry with strict unknown-variant handling;
3. labels modeled returns from the newest committed returns-series artifact;
4. refuses to emit or publish a family-less public report after any family
   telemetry failure;
5. opens the existing operational issue path on a non-zero family or report
   return code.

The telemetry payload exposes `phase1_paper_gate`. It is GREEN only when BOS,
OB, FVG and SWEEP each have at least one closed PAPER outcome.

## Honest remaining gate

The current family-event benchmark is retrospective/model-based and includes
forward windows. It must not be transformed into paper fills. A separate
prospective producer must create commercial family setups at decision time,
then let the existing incubation, reconciliation and outcome stages observe
their lifecycle.

Until that producer is connected and the four-family paper gate turns GREEN,
Phase 1 remains operationally incomplete. The later live gate remains at least
90 live days and 30 closed live trades for one family, acceptable drift and no
kill-switch fire. External commercial approval is an opaque owner-controlled
release gate handled outside this repository.

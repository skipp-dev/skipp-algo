# Phase 1 evidence-truth contract

Status: technical truth gates, a replay-safe broker-free prospective shadow
path and local campaign aggregation are implemented; representative
live-window observations and family paper execution evidence have not yet
accumulated.

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

## Prospective setup producer

`scripts/build_commercial_family_setups.py` consumes one confirmed,
point-in-time market-structure payload and emits at most one current long setup
for each commercial family. It:

- rejects every nested `forward_*` field, future observation and stale input;
- requires stable event identity, symbol, timeframe, source and `as_of`;
- maps only explicit BOS, OB, FVG and sell-side-sweep events to the four owned
  commercial variants;
- writes amber gate, setup and diagnostic artifacts atomically; and
- performs no broker, network or incubation-ledger I/O.

This is an evidence-boundary component, not a deployed paper trader. A strict
audit-only incubation mode now validates its evidence class, freshness and
provenance and preserves those fields in per-intent audit rows. Broker-connected
paper submission remains a separate opt-in and has not been started.

`scripts/run_commercial_family_shadow.py` composes those two stages without
adding broker or network capability. It assigns a canonical identity to the
complete point-in-time input, serializes concurrent runs, skips exact completed
replays, repairs a missing manifest after an audit commit and blocks partial or
inconsistent replay state. These audit-only rows prove pipeline behavior, not a
fill or closed PAPER outcome.

`scripts/run_commercial_shadow_campaign.py` adds a local campaign control
plane around those one-shot observations. It persists immutable attempt
records and rebuilds source-freshness, processing-latency, failure, family
coverage and audit-integrity evidence. An immutable campaign contract prevents
decision parameters or thresholds from drifting between observations. Its
technical observation gate is separate from the product promotion gate. Even
a technical `PASS` leaves promotion at `NO_GO`, because this path has no broker
capability and therefore no fills or closed PAPER outcomes. Representative
live-window operation has not started; tests only prove the controller
contract.

## Honest remaining gate

The current family-event benchmark is retrospective/model-based and includes
forward windows. It must not be transformed into paper fills. The prospective
producer now creates decision-time setup artifacts and the strict audit-only
pilot connects them to the incubation risk/audit stages. It is deliberately not
connected to a broker by default. A controlled paper-account run must still
prove submission, reconciliation and closed outcomes without weakening the
point-in-time boundary.

Until that producer is connected and the four-family paper gate turns GREEN,
Phase 1 remains operationally incomplete. The later live gate remains at least
90 live days and 30 closed live trades for one family, acceptable drift and no
kill-switch fire. External commercial approval is an opaque owner-controlled
release gate handled outside this repository.

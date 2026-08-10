# Phase 1 prospective family paper-producer pilot

Status: producer implemented and locally verified; runtime pilot not connected
or started.

## Purpose

This pilot establishes prospective PAPER evidence for BOS, OB, FVG and SWEEP
without converting retrospective family benchmarks into execution evidence.
It deliberately separates point-in-time signal production from broker-facing
incubation.

## Data path

1. `scripts/pull_databento_edge_input.py` builds a confirmed, point-in-time
   payload with bars, market structure, `as_of` and provenance.
2. `scripts/build_commercial_family_setups.py` validates that snapshot and
   writes setup, amber-gate and diagnostic artifacts atomically.
3. A controlled pilot operator reviews freshness and provenance before passing
   the artifact to `scripts/run_smc_live_incubation.py` in paper mode.
4. Existing fill reconciliation and outcome generation record lifecycle,
   realized fill, fees-known state, slippage and a closed PAPER outcome.
5. `scripts/build_families_telemetry.py` reads those records without mixing
   them with MODELED_OOS or LIVE evidence.

The producer never calls a broker and is not automatically chained to step 3.

## Fail-closed producer contract

The producer returns no tradable output, or exits non-zero, when any applicable
condition fails:

- nested `forward_*` evidence is present;
- an observation or event is later than `as_of`;
- the newest confirmed bar or source event exceeds its freshness budget;
- `trade_date` disagrees with the UTC date of the source snapshot;
- symbol, timeframe, source, stable event ID or usable risk geometry is absent;
- the event is invalidated, inactive, short-directional or outside the four
  explicitly owned commercial families.

For each family it selects the newest valid event and emits at most one setup.
Malformed newer candidates cannot suppress an older valid candidate inside the
same freshness window.

## Pilot launch gates

Before any automated paper submission:

- run the producer in transformation-only shadow mode across a representative
  live market window;
- confirm artifact freshness, deterministic order references and duplicate
  handling through replay/restart tests;
- verify paper-only account routing and a hard live-order prohibition;
- verify closed-outcome reconciliation, including nullable unknown fees;
- confirm every audit row carries `evidence_class=PAPER` plus complete source
  provenance; and
- retain amber status until the family-specific review approves promotion.

The Phase-1 exit gate remains BLOCKED until all four families have at least one
correctly classified closed PAPER outcome and telemetry reports no unknown
variant. No result from this pilot qualifies as a live performance claim.

The external commercial-clearance decision is an opaque owner-controlled gate
handled outside this repository.

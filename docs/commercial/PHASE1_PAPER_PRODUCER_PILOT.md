# Phase 1 prospective family paper-producer pilot

Status: producer and strict audit-only incubation path implemented and locally
verified; broker-connected paper pilot not started.

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

The producer never calls a broker. The existing incubation runner connects the
artifacts to step 3 only when invoked with `--prospective-paper-pilot`. That
mode remains audit-only unless the operator separately supplies
`--place-paper-orders` and every existing paper-account and portfolio gate.

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

Before building an intent, the strict runner additionally requires:

- a variant owned by the four-family producer and a matching `family`;
- `evidence_class=PAPER` and `producer_mode=prospective_pit`;
- a stable event ID and anchor no later than `source_asof_ts`;
- a source snapshot no more than 300 seconds old by default;
- matching setup/provenance symbol and timeframe plus a named source; and
- `trade_date` matching the UTC date of the point-in-time snapshot.

The source fields and full provenance object are copied into normal,
earnings-blocked and portfolio-blocked per-intent audit rows. A commercial
variant cannot be submitted through `--place-paper-orders` unless strict pilot
mode is also active.

## Audit-only invocation

First produce artifacts from a fresh point-in-time payload:

```bash
python -m scripts.build_commercial_family_setups \
  --input artifacts/commercial/pit_input.json \
  --setups-output artifacts/commercial/setups.json \
  --gate-status-output artifacts/commercial/gates.json \
  --diagnostics-output artifacts/commercial/producer_diagnostics.json \
  --trade-date YYYY-MM-DD
```

Then exercise risk, earnings and portfolio-independent incubation without
placing an order:

```bash
python -m scripts.run_smc_live_incubation \
  --phase paper \
  --setups artifacts/commercial/setups.json \
  --gate-statuses artifacts/commercial/gates.json \
  --audit-output artifacts/commercial/incubation_audit.jsonl \
  --prospective-paper-pilot
```

This invocation records `action=audit_only`. It does not create a paper fill
or a closed PAPER outcome and therefore cannot turn the Phase-1 exit gate
green.

## Pilot launch gates

Before any broker-connected paper submission:

- run the producer plus strict audit-only incubation across a representative
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

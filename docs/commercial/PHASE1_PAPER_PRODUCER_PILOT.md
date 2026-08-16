# Phase 1 prospective family paper-producer pilot

Status: producer plus restart-/replay-safe audit-only shadow path and local
campaign evidence aggregation implemented; representative live-window
observation and broker-connected paper pilot not started.

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
3. `scripts/run_commercial_family_shadow.py` runs the producer and strict
   audit-only incubation as one locked observation, or a controlled pilot
   operator passes the reviewed artifacts to `scripts/run_smc_live_incubation.py`.
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

The producer hashes the complete canonical input as `source_snapshot_id`.
Every setup and per-intent audit row carries that identity. One strict batch
cannot mix snapshot identities.

The source fields and full provenance object are copied into normal,
earnings-blocked and portfolio-blocked per-intent audit rows. A commercial
variant cannot be submitted through `--place-paper-orders` unless strict pilot
mode is also active.

## Audit-only invocation

The preferred shadow invocation produces all artifacts and the strict audit in
one broker-free command:

```bash
python -m scripts.run_commercial_family_shadow \
  --input artifacts/commercial/pit_input.json \
  --setups-output artifacts/commercial/setups.json \
  --gate-status-output artifacts/commercial/gates.json \
  --diagnostics-output artifacts/commercial/producer_diagnostics.json \
  --audit-output artifacts/commercial/incubation_audit.jsonl \
  --manifest-output artifacts/commercial/shadow_manifest.json
```

This command has no broker or network switch. It uses a per-audit lock to
serialize concurrent invocations. A complete repeated snapshot is recorded as
`REPLAY_SKIPPED` without duplicate audit rows. If a restart finds the audit
complete but the manifest missing, it reconstructs the manifest. A partial or
inconsistent snapshot audit fails closed for manual review. This includes a
changed quantity, stop or target contract for an already audited source
snapshot. A stale run lock is recoverable after 15 minutes by default.

## Audit-only campaign operation

For repeated observations, the local campaign controller wraps the one-shot
runner without adding provider, network or broker capability:

```bash
python -m scripts.run_commercial_shadow_campaign \
  --input artifacts/commercial/pit_input.json \
  --campaign-dir artifacts/commercial/shadow_campaign
```

The caller must supply an already-local, point-in-time payload for every
invocation. The controller stores immutable attempt records under `attempts/`,
snapshot-scoped producer artifacts under `snapshots/`, the shared strict audit
under `audit/`, an immutable `campaign_contract.json` and an atomically rebuilt
`campaign_report.json`. The contract fixes decision parameters and observation
thresholds for the campaign; changing either requires a new campaign directory.
An exact replay creates a `REPLAY_SKIPPED` attempt but no duplicate audit row.
Replay-only attempts do not dilute the failure-rate or freshness statistics.
If an existing campaign loses its contract, report rebuilding and further
observations fail closed instead of silently creating a replacement contract.

The default technical observation gate requires at least 20 unique audited
snapshots, no missing family, no invalid or duplicate audit row, at most 5%
failed attempts and a source-age p95 of at most 300 seconds. Before the minimum
sample is reached, threshold breaches are visible as warnings while the verdict
remains `PENDING`; an audit-integrity breach fails immediately. These are
operational campaign thresholds, not evidence that any family has a market
edge.

The campaign promotion gate is unconditionally `NO_GO`: the controller is
audit-only, cannot place an order and cannot create fills or closed PAPER
outcomes. A technical observation `PASS` must never be interpreted as product,
capital or public-claim approval. A crash after the shared audit commit can be
recovered by the next replay; consequently attempt records are a durable
operational history, while the audit remains the canonical setup-submission
history.

The equivalent split invocation remains available for inspection. First
produce artifacts from a fresh point-in-time payload:

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
- [x] confirm artifact freshness, deterministic order and snapshot references,
  concurrency exclusion and duplicate handling through replay/restart tests;
- [x] aggregate immutable attempts, family coverage, source age, processing
  latency, failures and audit integrity without enabling network or broker I/O;
- [ ] collect the required unique observations in representative live market
  windows and review the resulting technical observation gate — collection is
  LIVE-OWNED since 2026-08-16: `automation/launchd/run-c13-commercial-shadow.sh`
  runs ~6 audit-only campaign attempts per RTH session; the broker-connected
  stage in the same driver stays dormant behind the double interlock
  (`configs/commercial_paper_submission.json` `enabled` — the recorded review
  decision — AND `campaign_report.json` `observation_gate.verdict == PASS`);
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

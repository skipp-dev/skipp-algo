# ADR-0032: Canonical portfolio state and projected pre-trade risk

| Field | Value |
|---|---|
| Status | Accepted; deterministic aggregation, shadow decisioning and paper-only enforcement implemented. Correlation/sector caps remain unpromoted. |
| Date | 2026-08-08 |
| Scope | IBKR incubation and execution-risk boundary; signal scoring is unchanged |

## Context

Skipp evaluates signals per symbol/family, while its original account risk gate
accepts an already aggregated `AccountState`. The smoke harness separately sums
only the current candidate batch. Neither surface combines existing broker
positions, working entry orders and the next candidate batch into one canonical
projected state.

The repository also contains two adjacent but distinct research surfaces:

- co-firing research measures families that fire on the same symbol/bar; it is
  not cross-symbol portfolio correlation;
- SMT divergence expects an intraday partner's structure/bias. Portfolio risk
  instead needs completed-session returns and effective-dated sector reference
  data. Both may reuse PIT primitives, but must not share a business schema.

## Decision

### 1. Layer boundary

Portfolio risk is downstream of scoring. It may allow, recommend a smaller
size, or reject an order; it may not change a signal score or promote a family.

### 2. Canonical state

`PortfolioSnapshotV1` is the versioned account-scoped source of truth. It holds
broker positions, working orders, equity, capture time, completeness and
provenance. It rejects mixed accounts. Missing market prices, FX conversion,
equity or an unclassified working-order role remain explicit missing fields.
V1 risk amounts are USD-denominated. For an IBKR account whose native base is
not USD, capture may normalize account equity and available funds only when the
broker's USD position market values imply a positive conversion rate with at
most 1% cross-position dispersion. Missing or inconsistent conversion evidence
makes the snapshot incomplete; it is never treated as a 1:1 rate.

`PortfolioProjection` conservatively assumes all working entries and all new
intents fill completely. Protective exits do not create new exposure. Unknown
order roles are never interpreted as zero exposure.

### 3. Decision modes

- `off`: calculate only when explicitly called; no enforcement.
- `shadow`: persist the exact decision but always permit the existing submit
  path.
- `enforce`: block both `reject` and `resize` verdicts. A resize is a
  recommendation, not an automatic order mutation.

Checked-in configuration stays `shadow`. `enforce` is restricted to the paper
phase. Promotion remains a separate human decision after at least 20 clean,
risk-relevant paper sessions.

### 4. Deterministic limits

The first gate can evaluate snapshot freshness/completeness, projected position
count, gross exposure, single-name exposure, pending-entry exposure, single
trade risk, known aggregate risk at stop and stop-risk coverage.

Existing account-level daily-loss/drawdown/consecutive-loss kill switches remain
independent and run first. They are not reimplemented in the portfolio layer.

### 5. Sector and correlation context

`PortfolioRiskContextV1` uses effective-dated sectors and completed-session
returns strictly before the decision session. Future publication timestamps and
same-session closes fail loudly. Missing context is distinct from zero
correlation.

Sector and correlated-cluster caps are `null` in checked-in configuration.
Their calculations and evidence fields exist in shadow, but they cannot block
orders until a later evidence-backed configuration change.

### 6. Evidence and observability

Every evaluated run emits one `portfolio_risk_evaluated` record with its verdict,
reasons, aggregate percentage metrics and context coverage. The publishable audit
omits broker account, equity/USD amounts, symbols, positions and snapshot ID; the
full snapshot stays local. The shadow summarizer reports session coverage and never promotes a limit; it
only becomes `ready_for_human_review` after 20 clean, risk-relevant sessions.
A session is risk-relevant only when at least one evaluated decision has positive
candidate gross exposure, and every such session must have a passing broker
position reconciliation for the same date.

For the C13 paper path, the operational evidence contract is automated:
capture the broker snapshot immediately before submission, emit the portfolio
decision before any submit result for that run, preserve individual execution
IDs locally, capture the after-session snapshot, and reconcile signed position
deltas. Only the incubation audit and a sanitized reconciliation summary are
published to the evidence branch; account IDs, positions, raw snapshots and
execution IDs remain local. Grafana reports readiness/progress and alerts on a
missing decision, snapshot age outside the evaluated limit, new reject verdicts,
missing/failed reconciliation and non-zero reconciliation drift. The exporter
publishes the latest decision-time snapshot age, cumulative decisions labelled
by verdict, and the latest sanitized maximum absolute quantity delta plus its
reconciled state. Unknown evidence has an explicit `*_known=0` companion and is
never interpreted as a measured zero.
None of these signals changes the configured mode.

## Failure semantics

- stale/future/incomplete broker state: reject in enforcement, explicit finding
  in shadow;
- unknown working-order role: reject, never infer entry/exit;
- non-positive equity: reject;
- missing context while a context cap is configured: reject;
- missing context while all context caps are `null`: report coverage, do not
  invent a breach;
- a suggested resize is never silently applied to the order batch.

## Consequences

- Smoke and incubation can converge on one aggregation/risk kernel without
  changing signal semantics.
- The current manual `AccountState` remains compatible while the broker snapshot
  becomes the richer pre-trade source.
- Paper enforcement is available but not enabled by default.
- SMT remains deferred and independently promotable.
- Options, general multi-currency position conversion, automatic resizing and real-money
  submission remain outside v1.

## Promotion checklist

Before changing checked-in mode from `shadow` to `enforce`:

1. At least 20 distinct paper sessions with positive candidate gross exposure
   are present.
2. No stale/future/incomplete snapshot decision remains unexplained.
3. Projected state reconciles to subsequent IBKR position/order snapshots.
4. Every working-order role is classified.
5. Limit calibration and any resize policy receive explicit human approval.
6. Grafana/alert wiring for `live_overlay_portfolio_snapshot_age_seconds`,
   `live_overlay_portfolio_risk_decisions_total{verdict=...}` and
   `live_overlay_portfolio_reconciliation_max_abs_quantity_delta` / `_reconciled`
   is deployed with the configuration change.

Correlation/sector caps additionally require coverage and false-positive
evidence of their own; deterministic-limit promotion does not promote them.

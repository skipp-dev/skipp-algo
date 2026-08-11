# Commercial product baseline and action plan

Status: verified implementation baseline through the Phase-1 audit-only shadow
orchestration, 2026-08-11.

## Executive assessment

SMC already has meaningful product assets: a TradingView mainline, a Lite/Pro
cut, decision-first UX, measurement infrastructure and a credible first-party
direction for timely context. It is not yet a commercially ready multi-user
product and does not yet have a qualifying live performance record.

Current decision:

- broad paid launch: **NO_GO**;
- controlled design-partner preparation: **GO**, subject to the gates below;
- paid pilot: conditional on external approval, customer security and honest
  claims;
- performance marketing: **NO_GO** until evidence-class gates pass.

## Verified corrections to the prior review

| Prior assertion | Verified assessment |
|---|---|
| The whole SMC system is explicitly not a commercial product | Too broad. ADR-0030 scopes only the hosted Operator Terminal. SMC product identity and Lite/Pro product documents already exist. |
| 288 fields with 63 deprecated fields remain | Stale. Current generation produces 202 fields, with 119 consumed by Pine; all other generated fields have explicit ownership and the old deprecated groups were removed. |
| `FVG_NET_IMBALANCE` is orphaned | Stale. It is generated and consumed by current Pine surfaces. |
| All signal families use permutation tests | Overstated. The framework mixes block permutation, PSR and other family-specific methods. |
| There is no live track record | Correct. BOS, OB, FVG and SWEEP currently report zero live days and zero live trades. |
| There is no evidence at all | Incorrect. Modeled OOS and paper evidence exist, but neither is a qualifying live track record. |
| Issue #298 still needs t/F-style detectors implemented | Stale. Welch-t and Brown-Forsythe detectors exist; real-live recalibration remains open. |
| Bus factor is one | Correct and commercially relevant. Independent operational and quantitative review capacity remains a gap. |

## Most important current truth gap

The committed incubation data and the public product-family report are not yet
measuring the same commercial object:

- 140 inspected incubation records are paper records for
  `smc_orb_vwap_hold`;
- the checked-in family map does not map that variant to BOS, OB, FVG or SWEEP;
- unknown variants warn instead of blocking the daily family report;
- the current incubation therefore cannot establish product-family live days
  or live trades.

This is a P0 product-evidence mismatch. Phase 1 must make unknown variants
fail closed for promotion/public reporting and generate correctly classified,
closed outcomes for the four commercial families.

## Readiness score

| Area | Score, 0–5 | Reason |
|---|---:|---|
| Signal and quantitative architecture | 4.0 | Strong methods and governance, incomplete live calibration |
| TradingView product and chart UX | 3.5 | Existing product cut and decision-first surface |
| Qualifying live evidence | 1.5 | No family live days/trades; modeled and paper evidence only |
| Live Decision Mesh readiness | 1.5 | Private prototype direction, no released customer plane |
| Multi-user identity and entitlement | 1.0 | Shared operator-token models are not customer identity |
| Billing, support and commercial operations | 0.5 | No completed customer lifecycle |
| External commercial approval | Opaque owner-controlled gate | Process and conclusions remain outside this repository |

## Phased action plan

### Phase 0 — commercial truth and product boundary

Target: 3–5 working days.

- accept the commercial product/customer-plane ADR;
- preserve the hosted Terminal as the internal operator plane;
- define ICP, job to be done, promise and non-promise;
- establish a consistent product taxonomy;
- establish the claims registry and quarantine stale marketing copy;
- record only an opaque external-clearance launch gate.

Exit criteria: canonical documents exist, contradicting active claims are
marked historical or blocked, and later phases have explicit release gates.

Implementation status on 2026-08-11:

- [x] ADR-0033 accepts the commercial target and separates customer/operator
  planes.
- [x] Product brief defines the initial customer, job, promise and non-promise.
- [x] Canonical product taxonomy aligns the chart, Pro, Mesh and internal
  surfaces without renaming runtime files.
- [x] Claims registry blocks stale performance, provider-delivery and
  availability claims.
- [x] The April landing draft is reduced to an archived tombstone.
- [x] Older product-map/rescue documents are marked historical or
  implementation-scoped.
- [x] The external commercial-clearance process is kept outside the repository;
  only its opaque release state may be referenced.
- [ ] Owner review of the working `Skipp SMC` umbrella before any public brand
  or naming work.

### Phase 1 — evidence truth

Target: 1–2 engineering weeks, followed by calendar-time accumulation.

- fail promotion/public reporting on unknown variants;
- map and produce BOS, OB, FVG and SWEEP commercial setup variants;
- separate MODELED OOS, PAPER and LIVE in every report;
- record fills, fees, slippage, lifecycle and closed outcomes;
- update stale field-audit and issue #298 narratives;
- prove non-zero, correctly classified paper coverage for each family.

First exit gate: at least one closed paper outcome per family, no unknown
variant and complete provenance. The later live calibration gate remains at
least 90 live days and 30 closed live trades for a family, plus acceptable
drift and no kill switch.

Implementation status on 2026-08-11:

- [x] Variant ownership registry distinguishes commercial family variants
  from the known `smc_orb_vwap_hold` execution-only stream.
- [x] Unknown variants fail closed before telemetry is written or a public
  calibration report can be refreshed.
- [x] Family telemetry separates MODELED_OOS, PAPER and LIVE. Compatibility
  live counters must match the LIVE evidence block before C12 can pass.
- [x] New incubation rows carry an explicit evidence class. Outcome schema v3
  records gross PnL, entry slippage, fee-known state and net PnL only when
  fees are actually known.
- [x] The stale April field audit is marked historical and linked to the
  executable current contract.
- [x] The current threshold implementation is documented accurately in-repo:
  Welch-t and Brown-Forsythe exist; real-live recalibration remains gated by
  qualifying evidence.
- [x] A transformation-only producer emits PIT-safe BOS, OB, FVG and SWEEP
  setup artifacts and rejects forward evidence, future/stale observations,
  shorts and unowned variants. It has no broker or ledger side effects.
- [x] Strict audit-only paper-pilot mode connects the producer artifacts to
  incubation risk and audit stages, rejects evidence/provenance drift and
  preserves the source fields in every per-intent audit path.
- [x] A broker- and network-free shadow orchestrator binds every observation to
  a canonical PIT snapshot identity, serializes concurrent invocations, skips
  complete replays and fails closed on partial audit state.
- [ ] Broker-connected paper submission, fill reconciliation and closed
  outcomes have not started. Retrospective modeled events must never be
  relabelled as paper fills.
- [ ] Phase-1 paper gate remains **BLOCKED** until every family has at least
  one correctly classified closed paper outcome with complete provenance.
- [ ] The later 90-day/30-live-trade calibration gate is calendar-bound and
  remains **BLOCKED**.

The telemetry artifact exposes `phase1_paper_gate` so this first exit gate is
machine-readable instead of being inferred from prose.

### Phase 2 — customer plane and entitlement

Target: 3–6 engineering weeks.

- per-user identity and tier entitlement;
- session/device revocation and audit log;
- customer isolation and data minimization;
- separation of provider secrets from customer clients;
- signed Sidecar releases, rollback and signed packets;
- explicit TTL, `asof`, provenance, freshness and fail-closed behavior;
- security threat model and independent review.

Exit gate: two test customers cannot cross access boundaries, revocation is
demonstrably prompt, secrets never reach the client and rollback is proven.

### Phase 3 — controlled design-partner pilot

Target: 2–4 weeks, overlapping evidence accumulation.

- recruit 8–12 users matching the initial customer definition;
- measure onboarding and time to first understandable decision;
- hide operator/BUS/provider plumbing from product UX;
- show evidence class, freshness and uncertainty in product surfaces;
- measure activation, retained use, alert usefulness and support load.

Initial learning targets are defined in `PRODUCT_BRIEF.md`. A pilot is not a
performance promotion.

### Phase 4 — commercial operations

Target: 3–6 engineering weeks.

- packaging, pricing and billing lifecycle;
- cancellation, refund and entitlement revocation;
- support ownership and incident communication;
- backup, restore, RTO/RPO and release rollback drills;
- privacy and customer-data workflows;
- second-maintainer and independent validation coverage.

Exit gate: purchase-to-revocation and refund work end to end, and incident and
restore drills pass.

### Phase 5 — promotion and launch

Minimum: 90 calendar days of qualifying live evidence once Phase 1 is correct.

A broad launch requires affirmative external commercial approval, customer security and
privacy readiness, a reliable released Live Decision Mesh path, adequate live
evidence for every performance claim and working commercial operations.

If the live evidence gate is missing, the product remains a controlled
decision-support pilot with no performance promise.

## Indicative timeline

- week 1: Phase-0 product and governance truth;
- weeks 2–3: evidence-pipeline correction and family incubation start;
- weeks 3–8: customer plane and Sidecar hardening;
- weeks 7–10: design-partner pilot;
- earliest controlled commercial beta: approximately 12–16 weeks;
- earliest honest broader launch: approximately 4–6 months, subject to all
  gates and the irreducible live-evidence window.

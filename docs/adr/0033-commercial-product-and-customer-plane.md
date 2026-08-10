# ADR-0033: Commercial product goal and separate customer plane

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-08-10 |
| Decider | Repository owner |
| Related | ADR-0030; ADR-0031; `docs/SMC_PRODUCT_IDENTITY.md`; `docs/live_decision_mesh_public_boundary.md`; `docs/commercial/COMMERCIAL_PRODUCT_BASELINE_AND_ACTION_PLAN.md` |

## Context

The repository already contains a product-shaped TradingView mainline, a
decision-first user interface, a Lite/Pro cut, measurement infrastructure and
the private prototype direction for the Skipp Live Decision Mesh. The previous
architecture decision for the hosted Terminal deliberately stopped at a
single-operator workbench. That decision was sometimes read too broadly as if
the whole SMC system could never become a product.

The owner has now made the missing class decision: the target is a commercial
product with external users. This changes the required identity, isolation,
support, evidence and release standards. It does not turn the existing
operator Terminal into a customer application by implication.

## Decision

### 1. The commercial target is accepted

Skipp will develop the SMC system into a commercial decision-support product
for external users. Commercial readiness is a gated target, not a claim about
the current runtime.

### 2. Operator plane and customer plane remain separate

ADR-0030 remains in force for the hosted Terminal. The Terminal stays an
internal research, operations and support surface. It must not become a public
customer surface by accumulating signup, billing or customer state.

The commercial product receives a separate customer plane with individual
identity, entitlements, revocation, isolation, auditability and customer-safe
observability. A shared operator token is never a customer authentication
model.

### 3. Product surfaces have distinct jobs

| Surface | Commercial role | Current maturity |
|---|---|---|
| SMC Long-Dip Suite | Primary chart-native TradingView indicator for structured long-dip decisions | Existing mainline |
| SMC Decision Board | Optional Pro companion for deeper context and evidence | Existing mainline |
| Skipp Live Decision Mesh | First-party companion for timely proprietary context, freshness and provenance | Private prototype; not released |
| SMC Long-Dip Strategy | Research and evaluation companion | Existing, but not part of the initial performance promise |
| Hosted Operator Terminal | Internal research, monitoring, operations and support | Internal only under ADR-0030 |

The initial commercial product remains decision support. It does not place,
size or modify live orders and does not make personalized recommendations.

### 4. TradingView is a customer surface, not an upstream provider

No TradingView data-provider or Pine HTTP integration is planned. Pine-native
information remains on the chart. Time-sensitive proprietary context belongs
in the first-party Live Decision Mesh companion. Static library refresh remains
a control-plane mechanism, not a low-latency event transport.

### 5. Evidence classes must never be collapsed

Modeled out-of-sample returns, paper execution and live execution are separate
evidence classes. A commercial claim must state its class, observation date,
sample size and method. Paper or modeled evidence must not be called a live
track record. Missing evidence is visible and blocks the corresponding claim.

### 6. External commercial clearance stays outside this repository

The repository stores no analysis, inputs, reasoning or conclusions for the
external commercial-clearance process. Release governance records only an
opaque owner-controlled state: commercial release is blocked until that state
is affirmative.

### 7. Launch is gate-driven

A broad paid launch requires all of the following:

1. affirmative external commercial clearance;
2. per-user identity, entitlement, isolation and revocation;
3. customer-safe security, privacy and operational readiness;
4. a reliable released path for the promised Live Decision Mesh value;
5. evidence sufficient for every performance-related claim;
6. end-to-end purchase, cancellation and support operations.

A controlled design-partner pilot may start earlier only within the narrower
scope and claim policy defined in `docs/commercial/CLAIMS_REGISTRY.md`. It does
not imply production promotion.

## Consequences

### Positive

- Product work has an explicit customer and commercial objective.
- Existing TradingView value is preserved without exposing the operator
  workbench or reviving an impossible provider path.
- The distinctive live-context capability has a first-party product home.
- Evidence and claims can accumulate without pretending the current system is
  already commercially ready.

### Negative and accepted costs

- Multi-user identity, entitlements, support and privacy are new first-class
  systems rather than small Terminal additions.
- Commercial launch cannot be scheduled from engineering completion alone;
  external approval and live evidence have irreducible lead time.
- Some existing marketing and identity documents must be treated as historical
  until their claims are revalidated.

## Enforcement

This ADR is initially documentation-enforced. Phase 1 must add machine-readable
evidence-class and variant-coverage gates. Phase 2 must add automated
customer-isolation, entitlement and revocation tests. Marketing and release
work must use the claims registry from Phase 0.

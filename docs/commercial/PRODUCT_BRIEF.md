# Phase-0 commercial product brief

Status: internal product baseline, 2026-08-10.

## Product thesis

Active US-equity traders can identify a long-dip setup on a chart but still
have to assemble structure, regime, event risk, freshness and catalyst context
from disconnected sources. Skipp should reduce that synthesis burden while
showing what is known, how fresh it is and why the system reached its current
assessment.

## Initial customer

The initial customer is an intermediate or advanced active US-equity trader
who:

- already understands basic market-structure concepts;
- uses TradingView as the primary charting workspace;
- evaluates discretionary long-dip entries rather than delegating execution;
- values transparent context and invalidation more than a binary buy signal;
- accepts that measured evidence can be insufficient or inconclusive.

The initial scope is intentionally narrower than “all retail traders”. It does
not target beginners who need trading education, automated execution customers,
short-only strategies, non-US primary markets or institutional order-management
workflows.

## Job to be done

> When a potential long-dip setup appears, help me decide whether it deserves
> attention, what supports it, what invalidates it and which contextual risks
> are fresh enough to trust—without forcing me to leave my chart and manually
> reconcile several disconnected feeds.

## Product promise

Skipp provides a decision-first view of a structured long-dip setup and its
current context. It prioritizes clarity, provenance, freshness, invalidation
and honest uncertainty.

It does not promise profitability, guaranteed accuracy, personalized financial
advice or automated order execution.

## Product composition

### 1. SMC Long-Dip Suite

The primary chart-native surface. It owns structure, zones, the Focus/Hero
decision, invalidation and Pine-native alerts. It is the first-run customer
surface and should remain useful on its own.

### 2. SMC Decision Board

The optional Pro companion. It explains the decision with deeper context and
evidence. It must not require customers to understand internal BUS fields,
provider plumbing or operator diagnostics.

### 3. Skipp Live Decision Mesh

The planned first-party companion for time-sensitive external context that Pine
cannot receive as arbitrary HTTP data. Its product contract is freshness,
provenance, explicit unknown states and reliable delivery—not a TradingView
provider integration. It is still a private prototype and is not part of the
current release claim.

### 4. Internal surfaces

The hosted Operator Terminal remains internal. SMC Long-Dip Strategy remains a
research/evaluation companion until a later release decision defines its
customer role and evidence requirements.

## Working taxonomy

| Level | Canonical name | Rule |
|---|---|---|
| Commercial family | Skipp SMC | Umbrella used in planning; final brand clearance is separate |
| Chart product | SMC Long-Dip Suite | Existing Pine identity and primary customer surface |
| Pro chart companion | SMC Decision Board | Customer-facing chart companion name |
| Live companion | Skipp Live Decision Mesh | First-party context and delivery plane |
| Internal operations | Skipp Operator Terminal | Never marketed as the customer product |
| Retired umbrella | SkippALGO | Historical repository name, not a new customer-facing product name |

Source filenames and historical documents are not renamed merely to make the
taxonomy look complete. Any runtime or publication rename requires its own
compatibility and release plan.

## Initial commercial scope

The intended first complete commercial experience is:

1. receive individual access;
2. add the chart product in TradingView;
3. reach the first understandable decision in less than 15 minutes;
4. optionally open the Decision Board for explanation;
5. receive timely Live Decision Mesh context with visible freshness and
   provenance;
6. revoke access cleanly when the entitlement ends.

Billing, exact tier boundaries and prices remain undecided. They must follow
customer research, delivery cost measurement and the external approval gate.

## Product success signals

For the design-partner pilot, initial targets are:

- at least 80% complete onboarding without individual installation support;
- median time to first understandable decision below 15 minutes;
- at least 50% of activated design partners still use the product in week 4;
- zero critical customer-isolation or secret-exposure incidents;
- qualitative evidence that freshness/provenance improves the decision process.

These are product-learning targets, not trading-performance claims.

## Hard launch blockers

- external commercial approval has not been recorded as affirmative;
- customer identity or entitlements still use a shared operator token;
- one customer can access another customer's data or entitlement;
- the promised Live Decision Mesh surface is not reliably released;
- marketing requires a performance claim not permitted by the claims registry;
- support, cancellation or incident handling has no owned workflow.

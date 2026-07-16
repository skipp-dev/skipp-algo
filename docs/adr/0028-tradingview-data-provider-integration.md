# ADR-0028: Qualify a real TradingView data-provider integration

| Field | Value |
|---|---|
| Status | Proposed — M0 packet prepared; qualification required before implementation |
| Date | 2026-07-16 |
| Deciders | skipp-dev + TradingView partnership owner |
| Related | `services/live_overlay_daemon`; `spec/smc_live_overlay.schema.json` |

## Context

The live-overlay service produces useful derived series and exposes them through
`/{token}/smc_live`, but TradingView Pine v6 has no documented arbitrary HTTP
client. The former repo consumers called `request.raw()` or described
`request.get()`; neither call exists in Pine's documented `request.*` namespace.
The saved private script consequently failed with `CE10271`, and production saw
zero endpoint requests even while the US market was open.

TradingView webhooks solve the opposite direction: alerts send HTTP POSTs *from*
TradingView. Pine Seeds is end-of-day GitHub-backed data and new repositories are
currently suspended. TradingView Advanced Charts has a JavaScript Datafeed API,
but that puts data into a chart embedded on our own website; it does not make a
series available on tradingview.com or to Pine scripts there.

Official constraints:

- [Pine request namespace](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
- [Webhook direction](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)
- [Advanced Charts Datafeed API](https://www.tradingview.com/charting-library-docs/latest/connecting_data/)
- [TradingView data/API FAQ](https://www.tradingview.com/widget-docs/faq/data/)
- [Broker integration programme](https://www.tradingview.com/brokerage-integration/)

TradingView does not publish a general self-service specification for onboarding
arbitrary derived-data providers. The first deliverable is therefore a formal
qualification, not an invented adapter protocol.

## Decision

Pursue a **TradingView-hosted provider integration** whose accepted end state is:

1. Skipp series are onboarded into TradingView's own data infrastructure under
   approved symbols/fields and entitlements.
2. Those series are available on tradingview.com and consumable by Pine through
   a documented mechanism, expected to be `request.security()` if TradingView
   confirms that model.
3. Historical and real-time delivery, corrections, market-session semantics,
   latency, and redistribution rights are contractually specified.

An Advanced Charts Datafeed integration may be built later as a separate Skipp
web product, but it does **not** satisfy this decision and may not be reported as
the Pine/tradingview.com integration.

Until TradingView accepts the provider path, `/smc_live` remains a supported API
for non-Pine clients only, its market-traffic expectation stays `0`, and no Pine
script may contain `request.raw`, `request.get`, or `request.post` placeholders.

## Qualification packet and questions

The partnership owner prepares a qualification packet containing:

- company/product identity, expected users, regions, and target launch window;
- a data dictionary with provenance, units, update cadence, correction policy,
  and sample history for every proposed series;
- the pilot universe and expected real-time/historical throughput;
- entitlement model and proof of redistribution/derived-data rights;
- operational contacts, uptime target, incident process, and retention needs.

The maintained non-confidential packet and exact routing request are:

- [`docs/tradingview_provider_qualification_packet.md`](../tradingview_provider_qualification_packet.md)
- [`docs/tradingview_provider_qualification_request.md`](../tradingview_provider_qualification_request.md)

The packet deliberately marks source rights as unverified until written legal
and vendor evidence exists. The initial support message contains no formulas,
credentials, contract excerpts, sample payloads or other confidential material.

TradingView must answer these gates in writing:

1. Does an onboarding programme exist for our derived alternative-data product?
2. Can the onboarded series be used on tradingview.com **and from Pine**? Through
   which documented Pine API and symbol model?
3. Which partner protocol/schema, conformance suite, environments, SLAs, and
   certification steps apply?
4. Are custom non-price numeric fields supported, or must every metric be a
   separate synthetic symbol? Semantic packing into OHLC fields is forbidden
   unless TradingView explicitly approves and documents it.
5. How are realtime updates, backfill, revisions, corporate actions, sessions,
   time zones, symbol lifecycle, permissions, and user entitlements represented?
6. Which commercial, display, audit, and redistribution terms apply?

Any unclear or negative answer to questions 1–3 is a **no-go** for Pine delivery.
Use TradingView's authenticated support route or business contact; do not start
protocol implementation from assumptions.

## Implementation workstreams after qualification

### M0 — Provider acceptance

- Obtain the programme owner, NDA/terms, official technical specification, and
  explicit confirmation of Pine consumption.
- Legal review covers Databento, FMP, news, event, and every derived input. A
  right to consume data is not automatically a right to redistribute it.

### M1 — Product and contract

- Select a deliberately small pilot universe and metric set with TradingView.
- Define canonical identifiers, units, null semantics, session calendar,
  timestamp meaning, update cadence, history depth, corrections, and entitlements.
- Version the provider contract separately from `smc-live-overlay/1`; that JSON
  endpoint is not presumed to be the partner wire format.

### M2 — Delivery adapter and storage

- Materialize normalized, immutable time-series observations from the existing
  overlay computations into a replayable store.
- Build the adapter against TradingView's supplied protocol with idempotent
  realtime delivery, deterministic backfill, correction replay, retry/backoff,
  rate limits, and a dead-letter path.
- Keep credentials server-side. Pine scripts contain no provider secret.

### M3 — Conformance and sandbox

- Pass TradingView's schema/protocol certification and reconcile a golden pilot
  dataset end to end: source observation → adapter → TradingView → chart/Pine.
- Test late data, duplicate delivery, gaps, corrections, market closures,
  daylight-saving changes, symbol changes, and entitlement denial.

### M4 — Limited pilot

- Release to an allowlisted pilot cohort.
- Measure delivery lag, freshness, completeness, correction rate, query success,
  entitlement failures, and Pine-visible value parity.
- Retain Grafana and source-side reconciliation; dashboard health alone is not
  evidence that TradingView users received correct values.

### M5 — Production

- Expand only after the agreed soak period and error budget pass.
- Arm a provider-specific consumer watchdog based on acknowledged provider
  delivery/query telemetry. Do not reuse `/smc_live` request counts unless the
  final architecture genuinely produces those requests.

## Acceptance criteria

Production is complete only when all are true:

- TradingView has approved the provider and Pine access in writing.
- Legal has approved every source and derived field for the intended use.
- Historical and realtime conformance pass on the pilot corpus.
- A Pine script using only documented APIs reads the exact expected values on
  tradingview.com, including null/stale and correction cases.
- End-to-end reconciliation, alerts, runbooks, ownership, rollback, and user
  entitlement tests are live.
- The production watchdog measures the actual provider path and has been tested
  with a controlled delivery stop.

## Fallback if TradingView declines

Keep the derived data in supported surfaces such as Grafana and server-side APIs.
A separately branded Advanced Charts application is a valid product option but
must be described as an embedded Skipp chart, not as Pine or tradingview.com data
availability. Pine features remain Pine-native and use documented TradingView
data only.

## Enforcement

- `tests/test_pine_tv_bridge_fail_closed.py` rejects unsupported arbitrary HTTP
  calls throughout the active Pine surface and pins the retirement of both old
  consumers.
- `tests/test_tradingview_provider_integration_plan.py` pins the qualification,
  licensing, conformance, Pine-access, and Advanced-Charts non-goal gates.
- `tests/test_tradingview_provider_qualification_packet.py` pins the concrete
  pilot, rights blockers, non-confidential contact route, Pine gate, and exact
  Advanced-Charts/broker non-goals.

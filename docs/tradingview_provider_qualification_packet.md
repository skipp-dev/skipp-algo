# TradingView data-provider qualification packet

| Field | Value |
|---|---|
| Status | Prepared for non-confidential routing inquiry; not yet submitted |
| Owner | skipp-dev |
| Decision record | [ADR-0028](adr/0028-tradingview-data-provider-integration.md) |
| Contact channel | TradingView authenticated support chatbot / support ticket |
| Last updated | 2026-07-16 |

## Purpose and requested outcome

Skipp produces derived decision-support time series for US equities. We want to
qualify whether TradingView can onboard those series into TradingView's own data
infrastructure so that approved users can:

1. find the series as properly identified symbols or fields on
   **tradingview.com**; and
2. read the same series from Pine through a **documented** mechanism, expected
   to be `request.security()` only if TradingView confirms that model.

This is **not** an Advanced Charts Datafeed API request. That API connects our
backend to a chart we host ourselves; it does not publish data to
tradingview.com. This is also **not** a broker integration request, and Skipp
will not use unsupported Pine HTTP calls or encode unrelated metrics into OHLC
fields without explicit TradingView approval.

The initial inquiry is intentionally non-confidential. TradingView's policies
state that material sent through contact or feedback channels is not treated as
confidential. Detailed formulas, source contracts, credentials, sample data,
and commercial terms must therefore wait for the appropriate partner process
and confidentiality terms.

## Product summary

- **Product:** Skipp, a decision-support and observability product for derived
  US-equity signals.
- **Data class:** Derived numeric observations; not orders, brokerage services,
  or a redistribution of TradingView content.
- **Target surface:** TradingView-hosted data on tradingview.com with documented
  Pine access.
- **Candidate users and regions:** To be supplied as part of commercial
  qualification; no scale claim is made in the routing inquiry.
- **Target launch:** Only after TradingView acceptance, source-rights clearance,
  conformance, and an allowlisted pilot.

Before a commercial qualification call, the partnership owner must also supply
the applicant's legal entity, registered jurisdiction, authorized commercial
and legal contacts, expected user count and regions, and target launch window.
Those facts are not invented in this packet and are not needed for the initial
routing question.

## Candidate pilot

The proposed pilot is deliberately small and remains subject to TradingView's
product and technical guidance.

| Dimension | Candidate scope |
|---|---|
| Instruments | AAPL, MSFT, NVDA |
| Session | US regular trading session, exchange calendar and time zone declared explicitly |
| Resolution | 15-minute observations |
| History | Up to 90 calendar days after rights clearance |
| Realtime target | One idempotent update per completed interval, plus documented corrections |
| Access | Allowlisted test cohort with explicit entitlements |

Candidate series:

| Series | Meaning | Unit / range | Null and correction semantics |
|---|---|---|---|
| `news_strength` | Magnitude of the aggregate signed news reading; direction is intentionally not encoded in this value | Unitless, 0 to 1 | Null means no fresh reading; later source revisions may produce a timestamped correction |
| `flow_rel_vol` | Current volume relative to its declared baseline | Ratio, 0 or greater | Null means no fresh reading; baseline definition is versioned in the partner contract |
| `global_heat` | Aggregate directional news reading | Unitless, -1 to 1 | Null means no fresh reading; later source revisions may produce a timestamped correction |

These are candidate non-price series, not synthetic prices. TradingView must
confirm whether each metric is represented as its own symbol, as an approved
custom field, or by another documented semantic model. The existing
`smc-live-overlay/1` JSON payload is not proposed as TradingView's wire format.

## Data-rights qualification

A right to consume source data does not imply a right to redistribute raw or
derived observations. The repository contains no contract evidence that clears
the proposed TradingView use. No pilot data may be transmitted until each row
below has written legal and vendor clearance.

| Source or right | Contribution | Current evidence | Required action | Gate |
|---|---|---|---|---|
| Databento | Market bars, volume and microstructure inputs | **UNVERIFIED** for TradingView redistribution or derived-data display | Review subscription agreement and obtain written clarification for the exact derived fields, audience, history and realtime use | BLOCKED |
| Financial Modeling Prep (FMP) | Market-wide, quote, calendar or news inputs used by applicable derived fields | **UNVERIFIED** for TradingView redistribution or derived-data display | Map each pilot field to endpoints and plan terms; obtain written permission where required | BLOCKED |
| Benzinga, NewsAPI.ai and other news/event sources | News, sentiment and event inputs used by applicable derived fields | **UNVERIFIED** for TradingView redistribution or derived-data display | Produce field-level provenance and obtain vendor/legal clearance for derived output and history | BLOCKED |
| Skipp transformations and identifiers | Derived calculations, field definitions and product naming | Ownership and licensing chain not yet documented for partner delivery | Legal review of contributors, dependencies, marks and commercial licensing authority | BLOCKED |
| TradingView content | None proposed as an input | Skipp must not extract, repackage or redistribute TradingView data | Confirm the provider feed is composed only from Skipp-owned or appropriately licensed sources | REQUIRED |

Before technical integration, legal must produce a field-level rights register
containing the source contract, raw-versus-derived classification, allowed
users and regions, realtime/history rights, display and Pine rights, retention,
audit obligations, and written approver.

## Questions TradingView must answer in writing

1. Is there a content or market-data provider onboarding programme that accepts
   derived alternative-data series from a non-broker product such as Skipp?
2. Can accepted series be hosted in TradingView's own infrastructure and made
   discoverable on **tradingview.com**, rather than only in a self-hosted
   Advanced Charts instance?
3. Can Pine scripts read those series? If yes, which documented Pine API,
   symbol identifier and entitlement model apply?
4. Are non-price scalar series supported? Must each metric be a separate symbol,
   can approved custom fields be defined, or is another semantic model required?
5. Which delivery protocol, schemas, environments, conformance suite,
   certification steps, throughput limits, uptime targets and support process
   apply?
6. How must timestamps, sessions, time zones, delayed or missing observations,
   corrections, backfill, corporate actions and symbol lifecycle be represented?
7. Which history depth, realtime cadence, retention, audit and reconciliation
   requirements apply?
8. How are provider name, symbology, user permissions, regions, plan tiers and
   commercial entitlements represented?
9. Which source-rights attestations, vendor permissions, audits and indemnities
   are required for derived series?
10. Which TradingView team owns this qualification, and what information may be
    shared before versus only after confidentiality terms are in place?

## Decision rule

| Result | Meaning |
|---|---|
| GO | TradingView confirms a provider programme, tradingview.com hosting, documented Pine access, an acceptable semantic model, and a path to source-rights approval |
| HOLD | A suitable programme exists but commercial qualification, confidentiality terms, legal evidence or a revised pilot is still required |
| NO-GO | The available path is Advanced Charts-only or broker-only, Pine access is unavailable or undocumented, derived non-price series are rejected, or source rights cannot be cleared |

No adapter implementation starts on a HOLD. Questions 1 through 3 must all be
answered positively and unambiguously before the project can move beyond M0.

## Contact and evidence log

The only public general support path identified is TradingView's authenticated
chatbot, which can create a support ticket for complex questions. TradingView
states that contacting the team requires a paid plan and that it has no direct
support email, phone or social-media support channel. The routing request is maintained in
[`tradingview_provider_qualification_request.md`](tradingview_provider_qualification_request.md).

| Evidence | Value |
|---|---|
| Official Advanced Charts scope | <https://www.tradingview.com/charting-library-docs/latest/connecting_data/datafeed-api/> |
| Official support contact path | <https://www.tradingview.com/support/solutions/43000648248-how-to-get-in-touch-with-the-support-team/> |
| Official support-channel limits | <https://www.tradingview.com/support/solutions/43000698097-how-to-get-help-support-on-tradingview/> |
| Non-confidential submission warning | <https://www.tradingview.com/policies/> |
| Submitted at | Pending |
| TradingView ticket / case ID | Pending |
| TradingView owner / team | Pending |
| Written answers archived at | Pending |

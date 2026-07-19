# Live Decision Mesh — public repository boundary

Status: factual architecture boundary, 2026-07-18.

This public repository contains the Skipp producers, Pine-native calculations,
library-refresh control plane, and server-side live-overlay services. It does
not contain the confidential Sidecar lab, private TradingView probes, relay
credentials, or user-specific browser state.

## Transport truth

- TradingView is not a Skipp data provider and no provider/datafeed integration
  is planned.
- Pine scripts do not use arbitrary HTTP or undocumented network calls. The
  retired consumer and its roadmap are not a supported delivery path.
- Library refresh/publish remains a code, schema, and static-reference control
  plane. It is not a low-latency event transport and users must update the
  script/library version to receive a refresh.
- The supported public runtime boundary is the existing server-side live
  overlay and its documented clients. Any future first-party browser Sidecar
  or user-confirmed Pine projection is developed in a separate private lab
  until the repository is private and a release decision has been recorded.

## Phase status

| Phase | Status in this public repository |
| --- | --- |
| 0 — truth freeze and contract | Public retirement/tombstone is complete; private experiments are not copied here. |
| 1 — alert ingress and Sidecar pilot | Private local prototype only; no public webhook endpoint or credential is committed. |
| 2 — durable delivery and signatures | Private local hardening only; production signatures are required before promotion. |
| 3 — producer/catalyst adapters | Existing backend producers remain authoritative; no new consumer claim is implied by this document. |
| 4 — Pine-native/Courier pilot | Private probes and explanatory-only experiments; no publication or directional claim. |
| 5 — observation and evidence | Local, manifest-bound shadow observation; no promotion before the predeclared evidence gates pass. |

This document is intentionally a boundary, not a product announcement. It
must not be read as evidence that a TradingView webhook, a public relay, or a
production Sidecar is deployed.

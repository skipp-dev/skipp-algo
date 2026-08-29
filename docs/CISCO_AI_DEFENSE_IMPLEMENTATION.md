# Cisco AI Defense for skipp-algo

Status: merged and live.  Tenant rollout and live runtime controls verified on
2026-07-20 in the dedicated, private Railway service `skipp-terminal-ai`; the
LLM egress path has since moved to the Producer, and the key state was
re-measured there on 2026-08-20 (see "Key state re-measurement").

## Objective

Every generative-AI prompt must be inspected before it reaches a model, and
every model response must be inspected before it is cached or shown.  Missing
credentials, unsupported regions, transport failures, and malformed Cisco
decisions block the provider call.  There is no application runtime `off`
mode.

This control is independent of PRE-A0/A0 model promotion.  Cisco AI Defense
protects generative-AI exchanges and AI supply-chain assets; it does not turn a
candidate PRE-A0 model into an approved trading model.

## Verified current AI surface

| Surface | Current implementation | Protection |
| --- | --- | --- |
| Terminal AI Insights | Raw OpenAI chat-completions call in `terminal_ai_insights.py` | Request and response inspection |
| FMP AI Insights | Raw OpenAI chat-completions call in `terminal_fmp_insights.py` | Request and response inspection |
| OpenAI provider probe | `GET /v1/models`, no prompt or completion | Credential/availability probe only; no content to inspect |
| PRE-A0/A0 inference | Local deterministic model artifact | Existing model-governance and MLflow gates; not an LLM exchange |
| Claude Agent SDK | Dependency present, no first-party invocation found | No active runtime path yet |
| MCP | No first-party MCP client invocation found | Add Cisco `agentsec` before enabling an agent/MCP runtime |
| Codex, Claude Code, GitHub Copilot UI | Runs outside the repository process | Requires an in-path enterprise control; repository code cannot intercept it |

The regression guard `tests/test_ai_defense_egress_guard.py` fails if a new
LLM generation endpoint or provider SDK import appears without an explicit
Cisco boundary.  It also fails when a first-party agent or MCP client is
activated before its dedicated runtime design has been reviewed.

Since 2026-08-29 the guard matches provider **hosts** (`api.openai.com`,
`api.anthropic.com`, `openai.azure.com`,
`generativelanguage.googleapis.com`, `api.mistral.ai`, `api.cohere.*`)
instead of one exact route, and provider/agent imports match on a dotted
prefix, so `from openai.types import ...`, `import openai.resources`,
`POST /v1/responses` and an Azure deployment URL are no longer invisible to
it — the demo review on 2026-08-28 measured all four slipping through the
previous exact-match version while the guard reported success.  A production
file that reaches a provider host must be either in the inspected generation
inventory (`terminal_fmp_insights.py`) or in the reviewed content-free
inventory (`scripts/probe_providers.py`, the `GET /v1/models` probe); a
second test re-proves that no file in the content-free inventory contains a
completion-carrying route, so the exemption cannot be used to smuggle an
uninspected call in.  Five positive controls feed synthetic offenders through
the same matching helpers, because a guard whose corpus contains no offender
is otherwise green whether or not it can still detect one.

## Protection scope decision (2026-07-20)

The target is **organization-wide AI protection through two distinct control
planes**, not the inaccurate claim that one repository wrapper protects every
AI tool.  Cisco describes AI Defense as the control for first-party AI
applications and Secure Access AI Access as the control for third-party and
shadow-AI use.  We keep those ownership boundaries explicit:

| Surface | Desired disposition | Enforcement owner | Current status | Gate before trusted use |
| --- | --- | --- | --- | --- |
| Terminal AI Insights and FMP AI Insights | Required now | Repository wrapper plus Cisco Inspection API | Covered by request and response inspection | Unit guard, Cisco event, blocked-provider proof, and blocked-UI proof |
| Any future first-party LLM API call | Required before merge or deployment | Repository runtime using a supported AI Defense enforcement point | Not present beyond the two terminal calls | Egress inventory updated; request and response protection; fail-closed tests; live synthetic allow/block evidence |
| Future first-party agent or MCP client | Default deny until designed and verified | AI Defense runtime enforcement plus least-privilege agent/tool identity; MCP supply-chain scanning where supported | No active first-party runtime | Dedicated threat model; tool/action policy; MCP/skill scan; prompt, response, tool-call, and failure tests; auditable Cisco events |
| Codex conversations, GitHub Copilot, Claude Code, and other developer AI clients | Required organizationally, but outside repository enforcement | Cisco Secure Access AI Access or another verified in-path enterprise control | Not covered by PR #3803 | Traffic is steered through the control; the exact client is visible; DLP/guardrail policy applies; synthetic prompt and response block tests succeed |
| Browser-based third-party AI tools | Required organizationally, but outside repository enforcement | Cisco Secure Access AI Access with sanctioned-app and data policy | Not covered by PR #3803 | Browser traffic is in path; sanctioned/unsanctioned behavior is proven; synthetic data-loss and harmful-response tests succeed |
| PRE-A0/A0 inference | Explicitly outside LLM runtime inspection | Existing MLflow, artifact provenance, promotion, drift, and model-governance controls | Correctly separate | Do not call it Cisco runtime-protected; add AI supply-chain/model scanning only for a supported asset type with returned evidence |
| Provider availability probes such as `GET /v1/models` | Outside content inspection | Credential and provider-health controls | Probe only | Must carry no prompt, completion, tool call, or user content |

### Binding invariants

1. Every first-party generative-AI request, response, cached answer, agent
   action, and MCP tool invocation that can affect a trusted output must cross
   a supported, fail-closed enforcement point before the effect occurs.
2. New first-party agent or MCP imports remain blocked by the repository guard
   until a reviewed implementation replaces the default-deny rule.  A package
   dependency alone is not an active runtime and does not count as coverage.
3. Repository code cannot claim coverage for traffic emitted by Codex,
   Copilot, Claude Code, an IDE extension, or a browser.  Each client remains
   `not covered` until its real traffic is visible at the enterprise
   enforcement point and a harmless synthetic block test succeeds.
4. Discovery, DNS visibility, an application inventory entry, or a permitted
   TLS connection is not equivalent to prompt/response enforcement.  Record
   the actual level as `discovered`, `access-controlled`, or
   `content-enforced`.
5. Until a developer client is content-enforced, it must receive only public,
   synthetic, or deliberately redacted data.  Repository secrets, provider
   payloads, customer information, private research, and production incident
   data remain prohibited inputs.
6. PRE-A0/A0 promotion evidence remains independent.  Cisco model or supply-
   chain scanning may add evidence, but cannot approve a trading model or
   replace MLflow and promotion gates.

### Coverage acceptance record

A surface may move to `covered` only when the record names the client or
runtime, enforcement point, policy, test time, synthetic test class, Cisco
event or transaction ID, observed block point, and operator.  Never use real
credentials, customer data, licensed provider payloads, or private prompts as
test content.

## Runtime architecture

```text
user/question + market context
            |
            v
  Cisco Inspection API (request)
            |
       Allow / Block
            |
            v
       OpenAI provider
            |
            v
  Cisco Inspection API (response)
            |
       Allow / Block
            |
            v
       cache and UI
```

`cisco_ai_defense.py` uses the official `cisco-aidefense-sdk==2.1.3`.
The wrapper adds two intentional hardening rules around the SDK:

1. A decision is trusted only when both `is_safe` and `action` are present and
   consistent.  This compensates for the SDK parsing a missing `is_safe`
   value as `True` — still the case on 2.1.3, measured 2026-08-06 in a
   throwaway venv: `runtime/inspection_client.py` builds the response with
   `is_safe=response_data.get("is_safe", True)`, so an answer that omits the
   field reads as *safe*.
2. Logs contain decision metadata only.  Prompt text, response text, Cisco
   explanations, and keys are never logged by the application boundary.
3. The optional `Metadata.created_at` field is omitted.  The SDK accepts a
   Python `datetime` in that field but fails to JSON-serialize it on a real
   inspection request — re-measured on 2.1.3 (2026-08-06):
   `Metadata(created_at=datetime.now(UTC))` still constructs, and serializing
   it still raises a `TypeError` naming an unserializable `datetime`.
   Cisco timestamps the event server-side; a regression
   assertion pins this workaround until the SDK contract changes.

## Verified rollout state (2026-07-20)

| Control | Verified state |
| --- | --- |
| Tenant region | `eu-central-1`, proven by an authenticated live inspection; the US endpoint rejected the same key |
| Application | `skipp-algo`, type `API` |
| Connection | `skipp-algo-runtime-openai`, Cisco AI Defense SaaS data plane |
| Guardrail profile | `skipp-algo-strict-runtime-profile-v1`; security 4/4 configured to block, privacy 3/3 enabled, safety 8/8 enabled, medium filter strength |
| Policy | `skipp-algo-strict-runtime-v1`, enabled and attached to the dedicated connection |
| Inspection key | `skipp-algo-runtime-openai-railway`, 64 characters, finite expiry on 2026-08-19 — superseded; see the 2026-08-20 re-measurement below |
| Railway runtime | `skipp-terminal-ai`, one replica, timeout `10`, final mode `enforce`; public ingress is permitted only through the fail-closed access proxy documented below |
| Monitor smoke | safe request allowed; synthetic injection recorded with `Prompt Injection` and `General Harms` rules |
| Enforcement smoke | safe request allowed; the same synthetic injection raised `AIDefenseBlockedError` before provider egress |
| Logging | decision/event metadata only; no key or inspected content emitted by the wrapper |

The temporary local credential entry created during setup was removed after it
was found to contain an invalid value.  The valid Inspection key is held by
Cisco and Railway only.  The dedicated Railway SSH public key used for the
smoke test is named `codex-skipp-cisco-smoke`; review or remove it when remote
operator access is no longer required.

## Key state re-measurement (2026-08-20)

All four rows were measured live on 2026-08-20, one day after the originally
documented Inspection-key expiry, with content-free synthetic probes run
inside the `smc-signals-producer` container via `railway ssh` (no prompt,
response, or key material in any output).

| Check | Measured state |
| --- | --- |
| Inspection key on `smc-signals-producer` | VALID — a synthetic `ping` inspection against `eu-central-1` authenticated and returned a complete decision (`is_safe=True`, `Action.ALLOW`); mode `enforce`. The 2026-08-19 expiry above did not strike, so the active key was rotated or extended after 2026-07-20. |
| Actual expiry of the active key | NOT READABLE from repo or runtime. The Management API rejects the deployed management credential (below), so the expiry is visible only in the AI Defense dashboard (Administration → API Keys / connection keys). |
| `CISCO_AI_DEFENSE_MANAGEMENT_API_KEY` on `smc-signals-producer` | INVALID and unconsumed — `GET https://api.eu.security.cisco.com/api/ai-defense/v1/connections` and `/applications` with the documented `x-cisco-ai-defense-tenant-api-key` header both return `401 {"code":16, "message":"failed to authenticate and authorize"}`, and no repo code, workflow, or doc references the variable. It also contradicts the operator-only blast-radius rule in "Secret handling and rotation". Remove it from the service, or replace it with a valid key stored operator-side only. |
| `CISCO_AI_DEFENSE_API_KEY/_MODE/_REGION/_TIMEOUT_SECONDS` on `skipp-terminal-ai` | DEAD COPY — the terminal AI tab routes exclusively through the Producer's private `/ai-insights` (`ProducerAIInsightsClient`); no code path in the terminal image calls `inspect_messages`. A stale duplicate of the Inspection key with no mechanism keeping it in sync with the Producer's copy. Candidate for removal (removal triggers a terminal redeploy). |

Expiry monitoring on 2026-08-20: none existed. `scripts/credential_health_check.py`
does not cover the Cisco Inspection key, and the producer log window inspected
on 2026-08-20 contained no AI Defense traffic, so a silent key death would have
surfaced only as fail-closed AI Insights errors for end users. Superseded by
the self-probe below (2026-08-21).

### Key state re-measurement (2026-08-21)

Measured live with the Management API from inside both producer containers:

| Check | Measured state |
| --- | --- |
| `CISCO_AI_DEFENSE_MANAGEMENT_API_KEY` | Replaced by the operator with a working Management key; verified live (HTTP 200 on `/applications` and `/connections`) inside `smc-signals-producer` AND `smc-signals-producer-databento-shadow`. The values are hash-identical on both services — two runtime copies means two places every future rotation must touch. |
| Tenant application | Renamed in the tenant to `smc-signals-producer` (was `skipp-algo`; updated 2026-08-21T10:51Z). The object names in "Cisco tenant objects" below are the original rollout names. |
| Active Inspection key | `my-app-ai-key`, created 2026-07-20T19:23Z, `expiry: null` — it **never expires**. Planned expiry is therefore no longer a death mode; revocation and region/tenant changes are. |
| Documented key `skipp-algo-runtime-openai-railway` | REVOKED on 2026-08-19T08:32Z (it did not lapse; it was revoked). |
| Hybrid connector | Railway service `aidefense-connector` runs Cisco's `proxyrelayclient:26.8.3` against `eu.cloudgw.aidefense.security.cisco.com:443`; no public domain; healthz `SERVING` over private networking. The operator installed the connector API key at 11:25Z; the tunnel has been CONNECTED to the relay since 2026-08-21T11:25:41Z (worker pools + ping sender up, zero reconnects observed). NO traffic is routed through it yet. Routing LLM egress through the connector would be a separate, reviewed change to the enforcement architecture. |

### Key state re-measurement (2026-08-28)

Measured live while validating the customer-demo runbook.  Railway variable
*names* were read per service; values are quoted only where they are not secret.

| Check | Measured state |
| --- | --- |
| Runtime modes on `smc-signals-producer` | `CISCO_AI_DEFENSE_MODE=enforce`, `CISCO_AI_DEFENSE_RESPONSE_MODE=monitor`, region `eu-central-1`, timeout `10`. The response phase therefore **records and delivers** a policy violation, and the delivered answer is positively cached. Enforce on the response phase is a separate, explicit decision. |
| "Dead" Cisco copy on `skipp-terminal-ai` | REMOVED 2026-08-28 — and it was **not dead**. See the incident below: the Producer's mode/region/timeout resolved from those entries. The terminal container now carries no `CISCO_AI_DEFENSE_*` and no `OPENAI_API_KEY`, which is the intended end state; the Producer needed its own literals. |
| `CISCO_AI_DEFENSE_MANAGEMENT_API_KEY` on both producers | REMOVED 2026-08-28 from `smc-signals-producer` and `smc-signals-producer-databento-shadow`, both redeployed and verified inside the new containers. It was unconsumed (its only reference anywhere in the repository was this document) and contradicted the operator-only blast-radius rule in "Secret handling and rotation". |
| Active inspection key | `my-app-ai-key`, `expiry: null` — unchanged. Planned expiry is not a death mode; revocation and region/tenant changes are, and the self-probe is what observes them. |

Two application-layer defects found while validating the demo claims, fixed in
the same change:

1. The negative cache stored an AI Defense **policy block** and a provider or
   inspection **failure** under one sentinel.  A blocked prompt repeated inside
   the 30 s TTL was therefore reported as a failure, and `/ai-validation` maps a
   failure to `502 validation backend unavailable` — Cisco's validator would
   have scored a working guardrail as application downtime.  The suppression is
   unchanged; the reason is now preserved, so a replayed block answers exactly
   like the first block.
2. `event_id` was logged only on a violation, so an *allowed* transaction could
   be correlated to the Cisco event log by timestamp only.  It is now logged on
   allow decisions too (`none` when Cisco returns no event).
3. `transaction_id` named a single inspection, not the transaction.  Each
   `inspect_messages` call minted its own uuid, so the request and the response
   decision of one user query could not be joined — measured in the live
   Producer log, where one terminal query at 2026-08-28T22:32Z produced
   `transaction_id=7fb089e7…` for the request phase and `81b8f43e…` for the
   response phase.  `new_transaction_id()` now mints one id per exchange and
   both phases carry it, in the log line and in the Cisco
   `client_transaction_id` metadata.  A cache delivery is one exchange too, so
   its two re-inspections share an id as well.

#### Incident 2026-08-28 22:24–22:28Z: the "duplicate" variable was the Producer's source

Deleting the four `CISCO_AI_DEFENSE_*` entries from `skipp-terminal-ai` — the
row recorded on 2026-08-20 as a DEAD COPY, and genuinely unread by any terminal
code path — left `CISCO_AI_DEFENSE_MODE`, `_REGION` and `_TIMEOUT_SECONDS`
**empty in the Producer's variable store**.  `_mode()` rejects an empty mode, so
every AI Insights and `/ai-validation` request fails closed with
`AIDefenseConfigurationError`.

What is proven, and what is not:

* **Proven — the values changed under that deletion.**  All three read
  `enforce` / `eu-central-1` / `10` before it and empty after.
* **Proven — the management-key deletion did not cause it.**  The identical
  `railway variable delete CISCO_AI_DEFENSE_MANAGEMENT_API_KEY` ran on *both*
  producers, and the shadow's other Cisco variables are untouched
  (`enforce` / `eu-central-1` / `10`).  That controlled comparison leaves the
  terminal deletion as the only candidate.
* **Proven — `CISCO_AI_DEFENSE_RESPONSE_MODE` survived.**  It is the one name
  the terminal never carried.
* **Proven, 2026-08-29 — the exact linkage.**  The three were Railway
  **reference variables pointing at the terminal service**.  The deployment
  snapshot of the failing run (`c173457b`, created 22:23:44Z) records them
  verbatim:

  ```
  CISCO_AI_DEFENSE_MODE             = ${{8f2902cd-…-4475b1263101.CISCO_AI_DEFENSE_MODE}}
  CISCO_AI_DEFENSE_REGION           = ${{8f2902cd-…-4475b1263101.CISCO_AI_DEFENSE_REGION}}
  CISCO_AI_DEFENSE_TIMEOUT_SECONDS  = ${{8f2902cd-…-4475b1263101.CISCO_AI_DEFENSE_TIMEOUT_SECONDS}}
  ```

  `8f2902cd-45f1-4c0a-be8e-4475b1263101` is `skipp-terminal-ai`.  Deleting the
  variables there left three live references with nothing to resolve to, which
  is why they read as empty rather than missing.  `RESPONSE_MODE` survived
  because it is a literal and the terminal never carried that name;
  `CISCO_AI_DEFENSE_API_KEY` survived because it is a service-level literal on
  the Producer.  The audit log does not record variable mutations at all — the
  window 21:00–23:30Z contains only Deployment, SSHSession, ContainerAccess and
  Backup entries — so the deployment snapshot, not the audit log, is where this
  is visible.

  Note that the reference is stored by service **UUID**, not by service name, so
  a search for "terminal" in the Producer's configuration would not have found
  it either.

Timing, and why the blast radius stayed small:

* A variable change does **not** restart a running container.  The Producer kept
  serving with its old, correct environment for roughly half an hour after the
  deletion.
* The outage began when the Producer was redeployed for the management-key
  removal: container up `22:24:58Z`, first log line
  `Cisco key self-probe failed error_type=AIDefenseConfigurationError consecutive=1`
  390 ms later.
* Restored as explicit literals on the Producer (`enforce`, `eu-central-1`,
  `10`), redeployed, container up `22:28:03Z`, followed one second later by
  `Cisco AI Defense allowed phase=request source=cisco-self-probe` and
  `Cisco key self-probe ok`.  End-to-end `/ai-validation` from inside the
  container: `HTTP 200`, `answer="OK"`, `error=""`.
* Total exposure **3 min 6 s**, outside market hours.

Three lessons that outrank the incident itself:

1. **"No code reads it" is not "nothing depends on it."**  The 2026-08-20 row
   proved the terminal copy was unread by terminal *code* and concluded it was
   dead.  Configuration can be consumed by the platform rather than by the
   process; those are two different questions and only the first was asked.
2. **The self-probe earned its keep.**  It turned a silent misconfiguration into
   a logged failure within one second of container start — exactly the watchdog
   gap it was built for on 2026-08-21.  The paired Grafana rule
   (`sp-cisco-probe-stale`, last success older than 2 h) correctly did *not*
   fire for a three-minute outage: the probe is the detector, the alert is for a
   sustained failure.
3. **The CLI cannot show you a reference.**  `railway variables --kv` and
   `--json` report *resolved* values, so a reference is indistinguishable from a
   literal — and a reference whose target was deleted is indistinguishable from
   an empty literal.  This is precisely why the mechanism could not be proven
   while it was happening.  Two things do show it:

   ```bash
   # raw definitions for one service (shows ${{...}})
   curl -s -X POST https://backboard.railway.com/graphql/v2 \
     -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
     -d '{"query":"query($p:String!,$e:String!,$s:String!){ variables(projectId:$p, environmentId:$e, serviceId:$s, unrendered:true) }", ...}'

   # what a specific deployment actually received
   -d '{"query":"query($d:String!){ deploymentSnapshot(deploymentId:$d){ createdAt variables } }", ...}'
   ```

   Before deleting a variable, query it `unrendered` on **every** service in the
   environment and check whether any of them reference it.  After the change,
   read it back inside the new container (the store and the running container
   disagree until a redeploy) and require one `Cisco key self-probe ok` line
   before calling the change done.

Secret-hygiene follow-up: while diagnosing this, the Producer's
`CISCO_AI_DEFENSE_API_KEY` value was printed to an operator terminal by a
variable dump that did not mask it.  Rotate that Inspection key with the overlap
procedure in "Secret handling and rotation".

### Inspection-key self-probe (mechanism, 2026-08-21)

The watchdog gap above is closed by a producer self-probe instead of a second
secret store: `open_prep/cisco_probe.py` runs one content-free synthetic
inspection (`ping`, request phase, source `cisco-self-probe`) every
`RT_CISCO_PROBE_SECS` (default 3600, floor 300, no off switch) on a daemon
thread started by the serve path. A blocked decision counts as success; only
configuration errors, transport failures, and malformed decisions — the states
in which the runtime guard fails closed — count as failures. Results are
exported as `signals_producer_cisco_probe_*` on the existing `/metrics`
surface (already scraped by Alloy as job `signals_producer`) and consumed by
two Grafana rules in
`services/live_overlay_daemon/infra/grafana/alert-rules.yaml`:
`sp-cisco-probe-stale` (last success age > 2h) and `sp-cisco-probe-missing`
(series absent while the producer is up).
`tests/test_cisco_probe_alert_rules.py` pins the metric names against the
rules file so exporter and alert cannot drift apart silently.

## Runtime configuration

| Variable | Required | Value |
| --- | --- | --- |
| `CISCO_AI_DEFENSE_API_KEY` | Yes when any LLM call is possible | 64-character Inspection API key generated for the application connection; never use the Management API key here |
| `CISCO_AI_DEFENSE_REGION` | Yes | `eu-central-1`, `us-west-2`, `ap-northeast-1`, or `me-central-1`; must match the tenant region |
| `CISCO_AI_DEFENSE_MODE` | No | `enforce` by default; `monitor` permits policy violations but still blocks unavailable or invalid inspection |
| `CISCO_AI_DEFENSE_TIMEOUT_SECONDS` | No | Integer 1–60; default `10` |
| `RT_CISCO_PROBE_SECS` | No | Inspection-key self-probe interval in seconds; default `3600`, floor `300`, no off switch (see "Inspection-key self-probe") |
| `AI_VALIDATION_TOKEN` | Yes for dashboard validation | Dedicated 32–512 byte bearer token accepted only by the Producer's public `/ai-validation` application target |
| `TERMINAL_PRODUCER_FEED_URL` | Yes for centralized news | `http://${{smc-signals-producer.RAILWAY_PRIVATE_DOMAIN}}:8080/news-feed.json` |
| `TERMINAL_PRODUCER_FEED_TOKEN` | With producer URL | Railway reference to the producer's `SIGNALS_INTERNAL_TOKEN` |
| `TERMINAL_PRODUCER_AI_TIMEOUT_S` | No | Private `/ai-insights` timeout; default `150` seconds |
| `TERMINAL_DIRECT_NEWS_PRIMARY` | No | `0`: Producer news primary/direct fallback; `1`: direct news primary/Producer fallback |

The production Terminal normally consumes the Producer's private
`/news-feed.json` snapshot, while retaining FMP/Benzinga credentials for a
failure fallback or an operator-selected direct-primary mode. Exactly one news
path is called per successful cycle. The private client accepts only loopback
or direct `*.railway.internal` hosts, sends no redirects, rejects
stale/oversized/unknown-schema responses, and preserves the last good Terminal
feed when a refresh fails.

Interactive AI Insights is separate from news ingestion. The Terminal builds a
bounded context from available news, Databento OHLCV, FMP fundamentals,
technicals, social/analyst, and macro layers, then posts it to the Producer's
private `/ai-insights` endpoint. `OPENAI_API_KEY` and Cisco AI Defense settings
exist only on the Producer. The Producer performs request inspection, calls
OpenAI only after an allow decision, inspects the response, and returns the
bounded schema to the Terminal. Prompts and model responses are never written
to application request logs.

If an OpenAI key exists but the Cisco key or region is absent, AI Insights
fails closed before OpenAI receives any content.

## Cisco Validation application target

The public Producer exposes a narrow application-validation boundary without
exposing provider credentials, model selection, or the private Producer API:

| Cisco field | Value |
| --- | --- |
| Name | `Skipp AI Insights` |
| Target type | `Application` |
| Provider | `Custom endpoint` |
| Data plane | `Cisco AI Defense SaaS` |
| Endpoint | `https://smc-signals-producer-production.up.railway.app/ai-validation` |
| Method | `POST` |
| Request body | `{"prompt":"{{prompt}}"}` |
| Response path | `answer` |
| Headers | `Authorization: Bearer <AI_VALIDATION_TOKEN>` and `Content-Type: application/json` |

`AI_VALIDATION_TOKEN` is distinct from `SIGNALS_INTERNAL_TOKEN`,
`TERMINAL_ACCESS_TOKEN`, the OpenAI key, and both Cisco API-key types. The route
accepts only a bounded prompt, supplies the application-owned system prompt and
validation context internally, and returns the same inspected AI boundary used
by Terminal AI Insights. Provider/model changes stay behind this stable target.
Missing or malformed authentication fails before LLM egress, and provider or
inspection failures return a non-2xx response without exposing upstream error
details. A policy block is different: it returns a generic successful
application response stating that Skipp blocked the request, so the validator
can score the guardrail rather than misclassifying it as backend downtime.

## Public Railway ingress

The container exposes a small access proxy on Railway's `PORT`; Streamlit
listens only on `127.0.0.1:8501` behind it. `TERMINAL_ACCESS_TOKEN` is required
and must contain 32-512 non-whitespace bytes. The container exits before
listening when it is missing or malformed.

- `GET /health` is the only unauthenticated success path and reports process
  liveness only.
- `/ready`, `/_stcore/health`, `/metrics`, the terminal UI, WebSocket traffic,
  and all AI functions require `Authorization: Bearer <token>` or the secure
  session cookie created by the login form.
- An unauthenticated HTML request receives the local login form with status
  `401`. The token is posted to `/_access/session`, checked in constant time,
  and exchanged for an `HttpOnly`, `Secure`, `SameSite=Strict` cookie. It is
  never put in a URL.
- Authorization headers and the access-session cookie are removed before the
  request reaches Streamlit. The proxy does not log headers, request bodies,
  prompts, response bodies, or rejected token values.
- Cisco AI Defense remains a separate mandatory request-and-response guard in
  the application layer. Proxy authentication never bypasses its fail-closed
  behavior.

Operator smoke test (do not paste the real token into shell history; source it
from a protected environment or password manager):

```bash
curl -i "$TERMINAL_URL/health"                         # 200
curl -i "$TERMINAL_URL/ready"                          # 401
curl -i -H 'Authorization: Bearer deliberately-wrong' \
  "$TERMINAL_URL/ready"                                # 401
curl -i -H "Authorization: Bearer $TERMINAL_ACCESS_TOKEN" \
  "$TERMINAL_URL/ready"                                # 200
```

## Cisco tenant objects to create

The following names make the resulting events and credentials unambiguous:

- Application: `skipp-algo`
- Connection type: `API`
- Connection: `skipp-algo-runtime-openai`
- Inspection key: `skipp-algo-runtime-openai-railway`
- Policy: `skipp-algo-strict-runtime-v1`

Attach the policy to the connection.  Do not pass ad-hoc `enabled_rules` from
the application once a dashboard policy is attached; Cisco documents those as
mutually exclusive.

Start with a short `monitor` calibration window using synthetic and redacted
test prompts.  Review false positives caused by financial news, tickers, URLs,
and JSON context.  Then change the Railway variable to `enforce`.  The
application code itself already defaults to enforce, so the monitor phase must
be explicit and time-bounded.

Minimum policy categories to evaluate in the dashboard:

- Prompt Injection
- PII, PCI, and PHI
- Malicious URL Detection
- Tool Exploitation for future agent/MCP paths
- applicable safety rules for harmful generated content

The exact rule action is a tenant policy decision.  Preserve separate request
and response events so an input attack and output data leak remain
distinguishable.

## Secret handling and rotation

- Store the Inspection API key only in Railway/project secrets and a local
  secret manager; never commit it or place it in `.env` examples.
- Keep the Management API key separate.  It can create applications,
  connections, policies, scans, and validation jobs and therefore needs a
  narrower operator-only blast radius.
- Prefer a finite expiry and rotate with overlap: create the replacement key,
  update Railway, verify a safe and a blocked inspection, then revoke the old
  key.
- Cisco states that an Inspection API key and a Management API key are not
  interchangeable.

## Rollout gates

1. Unit and structural tests pass.
2. Cisco application, API connection, key, and policy exist in the correct
   region.
3. Railway secrets are set with `CISCO_AI_DEFENSE_MODE=monitor`.
4. Safe synthetic prompt: request and response decisions are visible.
5. Synthetic prompt-injection and synthetic PII tests produce Cisco events;
   no real secret or customer information is used.
6. Application logs contain event/transaction IDs but no inspected content.
7. Switch to `enforce` and prove the provider is not called for a blocked
   request and the UI does not receive a blocked response.
8. Add Cisco application validation to CI only after the application ID and
   separate Management API credential are available.
9. Add AIBOM/model/MCP scans only for supported asset types; do not label a
   plain PRE-A0 JSON contract as scanned until Cisco returns evidence for it.

## Protecting developer AI interactions

The code integration cannot intercept this Codex conversation, a Copilot chat,
or another SaaS UI because those requests originate outside the skipp-algo
process.  The selected control plane for these third-party clients is Cisco
Secure Access AI Access, subject to confirmed licensing, traffic steering,
TLS/application support, and client-specific validation.  AI Access provides
the sanctioned-app, shadow-AI, access, DLP, and guardrail layer; the repository
Inspection API remains the enforcement point for our own application code.

For a future first-party agent or MCP runtime, select a supported AI Defense
runtime enforcement point and pair it with agent/tool least privilege and the
available MCP supply-chain scanning.  The current pinned Python SDK does not
contain the previously assumed `aidefense.runtime.agentsec` module, so this
runbook and the egress guard do not treat that import as a valid control.

Whether the tenant license includes Secure Access AI Access, Gateway, hybrid,
or MCP features must be confirmed in Security Cloud Control.  Do not claim
complete developer interaction coverage until controlled tests from Codex,
Claude Code, GitHub Copilot, and each approved browser tool appear in the
relevant telemetry and a harmless block test succeeds for each client.

## Skill- und MCP-Scan der Entwicklerumgebung (2026-08-22)

Die Zeile "Future first-party agent or MCP client" oben nennt "MCP/skill scan"
als geforderte Kontrolle.  Sie läuft seit dem 2026-08-21 real, aber **nicht** im
Repository-Prozess: der Cisco AI Security Scanner ist eine VS-Code-Extension
(`cisco-ai.cisco-ai-security-scanner` 1.0.6, darin `mcp-scanner` 4.6.0 und
`skill-scanner` 2.0.9).  Sie prüft MCP-Konfigurationen und Agent-Skills auf der
Entwicklermaschine, nicht Produktions-Code.  Dieser Abschnitt hält fest, was
gemessen wurde und welche Befunde bewusst stummgeschaltet sind.

### Grundgesamtheit und Messung

Die Extension scannte mit `scanScope: global` nur `~/.claude/skills` und
`~/.codex/skills` — **16 Skills, 24 Befunde**.  Die Workspace-Skills des
Repositories (`.claude/skills/`, `.github/skills/`) waren damit nie erfasst.
Die vollständige Menge wurde am 2026-08-22 über alle vier Wurzeln gefahren:

```bash
skill-scanner scan-all <wurzel> --recursive --use-behavioral --use-trigger \
  --policy configs/skill_scan_policy.yaml --format json
```

**35 Skills, 63 Befunde** vorher — also rund die Hälfte der Menge ungesehen.
Nach den Fixes und der Policy: **21 Befunde**, keine Severity-Klasse gestiegen.

| Severity | vorher | nachher |
| --- | --- | --- |
| CRITICAL | 3 | 1 |
| HIGH | 6 | 4 |
| MEDIUM | 18 | 16 |
| LOW | 1 | 0 |
| INFO | 35 | 0 |

### Behobene Befunde (kein Mute)

- **2× CRITICAL `COMPOUND_FIND_EXEC`** in `~/.claude/skills/pre-push-guard`: der
  Bytecode-Purge war ein rekursives Shell-Delete aus dem Arbeitsverzeichnis mit
  unterdrücktem stderr.  Ersetzt durch einen auf die Git-Wurzel verankerten
  Python-Purge, der die Anzahl meldet.  Die Regel ist nicht abgeschaltet.
- **1× MEDIUM `TOOL_ABUSE_UNDECLARED_NETWORK`** und die Dokumentationsforderung
  zu `DATA_EXFIL_NETWORK_REQUESTS` in `~/.claude/skills/prove-over-population`:
  das Skill deklariert seine zwei Ziele jetzt im `compatibility`-Feld.
- **1× LOW `PYCACHE_FILES_DETECTED`**: `__pycache__/` entfernt, und die
  dokumentierte Aufrufform nutzt `python -B`, damit es nicht wiederkommt.
- **2× HIGH `MDBLOCK_PYTHON_EVAL_EXEC`, 1× MEDIUM `MDBLOCK_PYTHON_SUBPROCESS`**
  in `.github/skills/security-review/references/`: die Verwundbarkeits-Kataloge
  waren als `python` ausgezeichnet.  Sie sind Muster-Listen, kein lauffähiger
  Code, und stehen jetzt in `text`-Blöcken.  Beide Regeln bleiben überall scharf.

### Stummgeschaltet: `configs/skill_scan_policy.yaml`

Aktiv nur mit `skill-scanner.scanPolicy: "custom"` plus
`skill-scanner.scanPolicyFile` auf diese Datei — ohne den ersten Schalter wird
die Datei ignoriert.  Abgeschaltet ist genau eine Regel:
`MANIFEST_MISSING_LICENSE`.  Sie feuerte auf 35 von 35 Skills, betrifft die
Vertriebshygiene veröffentlichter Skill-Pakete und trennt bei 100 % Trefferquote
nichts.  Der Wächter `tests/test_skill_scan_policy.py` verlangt für jede weitere
Zeile eine Begründung im selben File.

Zwei gemessene Fallen stehen als Kommentar in der Policy und als Test dahinter:

1. Eine Liste in der Policy **ersetzt** die Preset-Liste, sie ergänzt sie nicht.
   `skip_in_docs` mit zwei Einträgen zu schreiben hätte die 14 Einträge des
   `balanced`-Presets still gelöscht — der Scan wäre grüner **und** blinder
   geworden, und beides sieht in der Oberfläche gleich aus.
2. `skip_in_docs` wirkt nur auf Regeln des `static`-Analyzers.  Die
   `MDBLOCK_*`-Regeln stammen aus dem behavioral analyzer, der die
   Policy-Scoping-Felder nicht liest; ein Eintrag dort wäre folgenlos gewesen.

### Verbleibende 21 Befunde

- **8× MEDIUM `DATA_EXFIL_NETWORK_REQUESTS`** in `prove-over-population` sind
  **richtig**: das Skill führt authentifizierte Ausgangsaufrufe mit einem
  Keychain-Token.  Sie bleiben sichtbar; die Ziele sind im Manifest deklariert.
  Eine Regel dieser Klasse auf eigenem, aktiv bearbeitetem Werkzeug
  stummzuschalten wäre der falsche Mute.
- **1× HIGH `RESOURCE_ABUSE_INFINITE_LOOP`** in `~/.codex/skills/gh-address-comments`:
  eine Paginierungsschleife, die am leeren Seiten-Ergebnis bricht.  Fremdcode,
  geprüft, harmlos — pfadweise stumm über `mcp-scanner.allowlist.skills`.
- **12× in `~/.codex/skills/.system/`** (`plugin-creator`, `openai-docs`,
  `imagegen`, `skill-installer`).  Beim ersten Durchgang wurden diese zwölf
  **gar nicht gemeldet** — die Extension stieg in diesen Pfad nicht ab.  Seit
  dem Nachtrag unten wird er gescannt, jeder Befund wurde einzeln an der Quelle
  geprüft, und die vier Skills sind hash-gebunden stummgeschaltet.

### Beide Abdeckungslücken geschlossen (2026-08-22, Nachtrag)

Der erste Durchgang ließ zwei Lücken offen. Beide sind jetzt zu.

**1 — `~/.codex/skills/.system/` wird beobachtet.**  Ursache war eine Zeile in
`scanSkillsDirectory`: `if (o.name.startsWith(".")) continue;` überspringt jedes
Kind, dessen Name mit einem Punkt beginnt.  Beim Scan von `~/.codex/skills` fiel
`.system` damit heraus — die sechs dort installierten Codex-System-Skills laufen
im Agent-Kontext des Entwicklers und waren nie erfasst.  Als eigener Eintrag in
`skill-scanner.globalSkills.customPaths` ist `.system` selbst das
Scan-Verzeichnis; seine Kinder sind nicht versteckt und werden gelesen.  Damit
wächst das Sichtfeld der Oberfläche von 16 auf 22 Skills.

Die 12 Befunde dort wurden einzeln an der Quelle geprüft, nicht pauschal
abgetan.  Alle zwölf sind Fehlalarme: bei `plugin-creator` treffen beide Regeln
dieselbe Zeile Ablauf-Prosa; `skill-installer` baut seine URLs an **beiden**
Aufrufstellen aus GitHub-Konstanten (einzige Ziele im ganzen Skill:
`api.github.com`, `codeload.github.com`, `github.com`); `openai-docs` liest die
Quelle, die der Aufrufer per `--source` übergibt; `imagegen` prüft nur, *ob*
`OPENAI_API_KEY` gesetzt ist.  Die Einzelbegründungen stehen in
`configs/skill_mute_registry.json` — samt dem einen verbliebenen Restrisiko
(der GitHub-Token-Header überlebt bei `skill-installer` eine Weiterleitung;
Fremdcode, nicht änderbar, deshalb notiert statt verschwiegen).

**2 — Kein Mute mehr ohne Inhalts-Bindung.**  `mcp-scanner.allowlist.skills`
blendet ein ganzes Skill aus, dauerhaft und unabhängig davon, was später darin
steht.  Genau diese Pfade sind Fremdcode, den Codex bei jedem Update ersetzt.
Der Satz „bei einem Update erneut prüfen" wäre hier eine Zukunfts-Zusage ohne
Mechanismus.  Stattdessen:

| Teil | Ort | Aufgabe |
| --- | --- | --- |
| Registry | `configs/skill_mute_registry.json` | je Mute Grund, Datum, Eigentümer, abgedeckte Regeln und der sha256 des Skill-Baums zum Zeitpunkt der Freigabe |
| Audit | `scripts/audit_skill_mutes.py` | Drift, unbegründeter Mute, toter Eintrag; Exit 0/3/**9**, wobei 9 („konnte nicht messen") bewusst von 0 getrennt ist |
| Auslöser | `~/.claude/hooks/skill-mute-drift-warn.sh` | SessionStart — läuft bei **jeder** Sitzung und schreibt den Befund vor den Agenten, der die Mutes gerade benutzt |
| Vertrag | `tests/test_skill_mute_registry.py` | 18 Tests; jede Befund-Klasse als Positivkontrolle synthetisch hergestellt |

Der Hash deckt den ganzen Baum ab — auch `.pyc`, auch Punktdateien, und ein
Symlink geht mit seinem Ziel-*Pfad* ein, damit eine Umbiegung nach außen ihn
verändert.  Es gibt bewusst **kein** `--bless`: ein Mute neu zu erteilen heißt,
den Fremdcode erneut zu lesen; ein Ein-Befehl-Neusegen würde genau den Schritt
wegautomatisieren, für den der Wächter da ist.  Der neue Hash kommt über
`--print-hash` und wird von Hand übernommen.

Arbeitsteilung, damit keine Hälfte für die andere gehalten wird: CI prüft den
**Vertrag** (die Pfade unter `~/.codex/…` existieren auf einem Runner nicht),
der Hook prüft den **Ist-Zustand** auf der Maschine.

Der wiederholbare Volllauf:

```bash
for w in ~/.claude/skills ~/.codex/skills <repo>/.claude/skills <repo>/.github/skills; do
  skill-scanner scan-all "$w" --recursive --use-behavioral --use-trigger \
    --policy configs/skill_scan_policy.yaml --format json --output-json "/tmp/$(basename $w).json"
done
```

## Documentation review (2026-08-29)

A multi-source pass over Cisco's own documentation, run to give the customer
demo a fact base and to check this runbook's claims.  Every item below is
either confirmed from a primary Cisco source or marked as measured-here.
Where the documentation and the SDK disagree, the SDK wins: it is what runs.

### Confirmed by Cisco's documentation

| Claim we make | Status |
| --- | --- |
| Inspection and Management are separate planes with separate key classes and separate headers (`X-Cisco-AI-Defense-API-Key` vs `x-cisco-ai-defense-tenant-api-key`) | Confirmed, and corroborated in Cisco's own SDK source |
| The two key classes are not interchangeable | Confirmed for Management → Inspection ("You cannot use this key for the AI Defense Inspection API"). The reverse direction is **nowhere stated** |
| `event_id` is minted only on a violation | Confirmed — so an ALLOW line carrying `event_id=none` is expected, not a defect |
| `client_transaction_id` is echoed for correlation | Confirmed as an echo. There is **no documented way to search the event log by it**, so do not promise that in a demo |
| Inspection keys are minted per connection and support an expiry | Confirmed: Applications → [app] → API Connections → Add Connection → Add API key, with "Expire on" or "Never Expire", shown once; regeneration invalidates the previous key immediately |

### Where the documentation is silent, and we measured instead

* **Wrong-class key.** No Cisco source states what a wrong-class key does.
  Measured 2026-08-29 on the live tenant: a Management key returns **401** from
  the Inspection API in both `eu` and `us`, and **200** from the Management API.
  That asymmetry is the fastest way to tell the two apart — they are otherwise
  indistinguishable, both being 64 hex characters.
* **Key format.** The 64-character length this wrapper enforces is **not
  documented** by Cisco for either key class; it rests on our own measurement.
  The check is fail-closed, so the risk is refusing a valid key of a future
  format, not accepting a bad one.
* **`action` in the response.** Cisco's published `InspectResponse` schema lists
  eight properties and **`action` is not among them**; its `required` array
  names `classification`, which is not one of the eight either (the property is
  `classifications`).  Formally, no response field is guaranteed.  The field is
  nonetheless real: the SDK reads it from the response body
  (`runtime/inspection_client.py:257`), it is not derived from `is_safe`.  Our
  two-field contract is therefore two independent signals, and deliberately
  stricter than what Cisco documents.

### Where the documentation and the SDK disagree

Measured per region in a **fresh process** — `Config` is a process-wide
singleton that silently ignores later parameters, so a single-process probe
returns one host for every region and looks perfectly plausible:

| Region | Cisco docs | SDK (measured) |
| --- | --- | --- |
| `us-west-2` | `us.` | `us.` |
| `eu-central-1` | `eu.` | `eu.` |
| `ap-northeast-1` | region named `ap-ne-1`, host `ap.` | **`apj.`** — and `ap-ne-1` raises `ValueError: Invalid region` |
| `me-central-1` | not documented at all | **`uae.`** — supported |

Consequences, both now pinned by `tests/test_cisco_ai_defense.py`:

1. An operator following Cisco's published table and setting `ap-ne-1` would
   configure a value the SDK cannot use.  This wrapper rejects it first, with
   its own configuration error.
2. `me-central-1` works despite being undocumented.  The documentation review
   concluded no Middle-East host exists; removing it on that basis would have
   deleted a functioning region.  The endpoint table is the counter-evidence,
   and the test fails if a future SDK stops resolving any of the four.

### The `Config` singleton, as a standing hazard

`Config` keeps the first instance for the life of the process and logs
`Config singleton already initialized. Ignoring different parameters` for every
later one.  `_get_client` is `lru_cache`d on `(api_key, region, timeout)`, so a
process that ever inspected against two regions would get a second cache entry
whose client still talks to the **first** region.  Not reachable today — each
service runs one region — but it is a silent-wrong-answer failure mode, not a
loud one, and it is the reason the region table above had to be measured one
process at a time.

### Not answered by this review

Enforcement points and deployment modes (Gateway, the hybrid connector /
`proxyrelayclient`, MCP Gateway), agent and MCP runtime protection, the SDK's
version history, and the boundary between AI Defense and Secure Access
"AI Access" produced **no claims that survived verification**.  That is a gap in
the sources, **not** a negative finding: it does not mean those features are
absent.  Our own measurement that the pinned SDK contains no `agentsec` module
stands on its own and is unaffected.

## Official references

- Cisco AI Defense Inspection API: <https://developer.cisco.com/docs/ai-defense-inspection/>
- Cisco AI Defense Management API: <https://developer.cisco.com/docs/ai-defense-management/>
- Cisco AI Defense data sheet: <https://www.cisco.com/c/en/us/products/collateral/security/ai-defense/ai-defense-ds.html>
- Cisco Secure Access AI Access: <https://www.cisco.com/site/us/en/products/security/secure-access/ai-access/index.html>
- Cisco AI Defense Python SDK: <https://github.com/cisco-ai-defense/ai-defense-python-sdk>
- Cisco AI Defense MCP Scanner: <https://github.com/cisco-ai-defense/mcp-scanner>
- PyPI release: <https://pypi.org/project/cisco-aidefense-sdk/>

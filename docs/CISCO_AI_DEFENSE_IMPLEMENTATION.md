# Cisco AI Defense for skipp-algo

Status: tenant rollout and live runtime controls verified on 2026-07-20 in the
dedicated, private Railway service `skipp-terminal-ai`.  Repository merge and
general availability remain gated by Draft PR review and CI.

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
known LLM generation endpoint or provider SDK import appears without an
explicit Cisco boundary.  It also fails when a first-party agent or MCP client
is activated before its dedicated runtime design has been reviewed.

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

`cisco_ai_defense.py` uses the official `cisco-aidefense-sdk==2.1.2`.
The wrapper adds two intentional hardening rules around the SDK:

1. A decision is trusted only when both `is_safe` and `action` are present and
   consistent.  This compensates for SDK 2.1.2 parsing a missing `is_safe`
   value as `True`.
2. Logs contain decision metadata only.  Prompt text, response text, Cisco
   explanations, and keys are never logged by the application boundary.
3. The optional `Metadata.created_at` field is omitted.  SDK 2.1.2 accepts a
   Python `datetime` in that field but fails to JSON-serialize it on a real
   inspection request.  Cisco timestamps the event server-side; a regression
   assertion pins this workaround until the SDK contract changes.

## Verified rollout state (2026-07-20)

| Control | Verified state |
| --- | --- |
| Tenant region | `eu-central-1`, proven by an authenticated live inspection; the US endpoint rejected the same key |
| Application | `skipp-algo`, type `API` |
| Connection | `skipp-algo-runtime-openai`, Cisco AI Defense SaaS data plane |
| Guardrail profile | `skipp-algo-strict-runtime-profile-v1`; security 4/4 configured to block, privacy 3/3 enabled, safety 8/8 enabled, medium filter strength |
| Policy | `skipp-algo-strict-runtime-v1`, enabled and attached to the dedicated connection |
| Inspection key | `skipp-algo-runtime-openai-railway`, 64 characters, finite expiry on 2026-08-19 |
| Railway runtime | `skipp-terminal-ai`, one replica, timeout `10`, final mode `enforce`; public ingress is permitted only through the fail-closed access proxy documented below |
| Monitor smoke | safe request allowed; synthetic injection recorded with `Prompt Injection` and `General Harms` rules |
| Enforcement smoke | safe request allowed; the same synthetic injection raised `AIDefenseBlockedError` before provider egress |
| Logging | decision/event metadata only; no key or inspected content emitted by the wrapper |

The temporary local credential entry created during setup was removed after it
was found to contain an invalid value.  The valid Inspection key is held by
Cisco and Railway only.  The dedicated Railway SSH public key used for the
smoke test is named `codex-skipp-cisco-smoke`; review or remove it when remote
operator access is no longer required.

## Runtime configuration

| Variable | Required | Value |
| --- | --- | --- |
| `CISCO_AI_DEFENSE_API_KEY` | Yes when any LLM call is possible | 64-character Inspection API key generated for the application connection; never use the Management API key here |
| `CISCO_AI_DEFENSE_REGION` | Yes | `eu-central-1`, `us-west-2`, `ap-northeast-1`, or `me-central-1`; must match the tenant region |
| `CISCO_AI_DEFENSE_MODE` | No | `enforce` by default; `monitor` permits policy violations but still blocks unavailable or invalid inspection |
| `CISCO_AI_DEFENSE_TIMEOUT_SECONDS` | No | Integer 1–60; default `10` |
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

## Official references

- Cisco AI Defense Inspection API: <https://developer.cisco.com/docs/ai-defense-inspection/>
- Cisco AI Defense Management API: <https://developer.cisco.com/docs/ai-defense-management/>
- Cisco AI Defense data sheet: <https://www.cisco.com/c/en/us/products/collateral/security/ai-defense/ai-defense-ds.html>
- Cisco Secure Access AI Access: <https://www.cisco.com/site/us/en/products/security/secure-access/ai-access/index.html>
- Cisco AI Defense Python SDK: <https://github.com/cisco-ai-defense/ai-defense-python-sdk>
- Cisco AI Defense MCP Scanner: <https://github.com/cisco-ai-defense/mcp-scanner>
- PyPI release: <https://pypi.org/project/cisco-aidefense-sdk/>

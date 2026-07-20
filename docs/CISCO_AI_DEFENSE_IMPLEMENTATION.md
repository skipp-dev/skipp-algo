# Cisco AI Defense for skipp-algo

Status: code integration prepared; Cisco tenant objects, secrets, and live
enforcement still require an operator-approved rollout.

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
explicit Cisco boundary.

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

## Runtime configuration

| Variable | Required | Value |
| --- | --- | --- |
| `CISCO_AI_DEFENSE_API_KEY` | Yes when any LLM call is possible | 64-character Inspection API key generated for the application connection; never use the Management API key here |
| `CISCO_AI_DEFENSE_REGION` | Yes | `eu-central-1`, `us-west-2`, `ap-northeast-1`, or `me-central-1`; must match the tenant region |
| `CISCO_AI_DEFENSE_MODE` | No | `enforce` by default; `monitor` permits policy violations but still blocks unavailable or invalid inspection |
| `CISCO_AI_DEFENSE_TIMEOUT_SECONDS` | No | Integer 1–60; default `10` |

If an OpenAI key exists but the Cisco key or region is absent, AI Insights
fails closed before OpenAI receives any content.

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
process.  Complete coverage requires one of these in-path approaches:

- Cisco AI Defense Gateway for supported model/provider endpoints;
- Cisco Secure Access or Multicloud Defense with AI-aware egress controls;
- Cisco `agentsec.protect()` inside any first-party agent process, imported
  before its supported LLM and MCP clients.

Whether the current licenses include the required gateway/SSE enforcement
point must be confirmed in Security Cloud Control.  Do not claim 100% developer
interaction coverage until a controlled test from each client (Codex, Claude,
Copilot, browser) appears in Cisco telemetry and a block test succeeds.

## Official references

- Cisco AI Defense Inspection API: <https://developer.cisco.com/docs/ai-defense-inspection/>
- Cisco AI Defense Management API: <https://developer.cisco.com/docs/ai-defense-management/>
- Cisco AI Defense Python SDK: <https://github.com/cisco-ai-defense/ai-defense-python-sdk>
- PyPI release: <https://pypi.org/project/cisco-aidefense-sdk/>

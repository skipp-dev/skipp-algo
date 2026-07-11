# Composio ops integrations

Cross-app automation for skipp-algo ops, via [Composio](https://composio.dev)
(one API key → Slack, GitHub, Outlook, …). Four use cases:

| # | What | Where it runs | Channel |
|---|------|---------------|---------|
| 1 | Credential-health alert → operator | `credential-health-check.yml` | Slack DM (adds to existing gh issue) |
| 2 | Date-gated reminders → calendar | one-time (done live) | Outlook events |
| 3 | Grafana alert → fan-out | live-overlay daemon (FastAPI) | Slack + opt-in GitHub issue |
| 4 | Daily ops digest | `ops-digest-daily.yml` | Outlook email |

## Architecture

* **#2 is already done** — the three reminder events were created directly in
  the operator's Outlook calendar via the Composio MCP tools in a live session.
  Nothing recurring runs for it.
* **#1, #3, #4 run unattended** (GitHub Actions cron; the Railway daemon). They
  call the **Composio REST API over stdlib `urllib`** — no SDK, no dependency —
  through one fail-soft wrapper: [`scripts/composio_ops.py`](../../scripts/composio_ops.py).
  `POST {base}/api/v3/tools/execute/{slug}` with an `x-api-key` header.

Choosing REST over the SDK is deliberate: the daemon runs from the hash-locked
terminal image and the CI runners install nothing extra, so a pure-stdlib
transport keeps every context identical and avoids Composio's heavy transitive
tree (openai/pandas/pyarrow). The wrapper **never raises and never hard-fails a
job**: with no `COMPOSIO_API_KEY` every helper returns
`DeliveryResult(skipped=True)` and the caller logs a no-op. Everything is
**inert until provisioned**.

## What you must provision (one-time)

### 1. Composio **project** API key + connected accounts

1. app.composio.dev → **Settings → API Keys** (project settings, *not* the org
   page). The key you need is the **project API key** with prefix **`ak_`** —
   NOT the Organization Access Token (`oak_`), which Composio's API rejects with
   HTTP 401. The full value is only shown once at creation; copy it then.
2. In the **same project**, connect the toolkits you need: **slack** (min for
   #3), **github** (only for opt-in issues), **outlook** (only for #4). Use
   Composio-managed OAuth. Note the connection's **`user_id`** (entity) — the
   REST call must pass the same one via `COMPOSIO_USER_ID`.
3. A key with **zero connections in its project** authenticates fine but every
   send fails with "no connected account" — verify the connections show up under
   the key's project.

### 2. GitHub Actions secrets/vars (for #1 and #4)

Repo → Settings → Secrets and variables → Actions. **`COMPOSIO_API_KEY` must be
a SECRET, never a variable** (a variable is world-readable).

| Name | Kind | Used by | Notes |
|------|------|---------|-------|
| `COMPOSIO_API_KEY` | **secret** | #1, #4 | the `ak_…` project key; master switch |
| `COMPOSIO_USER_ID` | var | #1, #4 | the entity the connections belong to |
| `SLACK_ALERT_USER_ID` | var | #1 | Slack member id `U…` for the DM (preferred) |
| `SLACK_ALERT_CHANNEL` | var | #1 | fallback channel if no user id |
| `COMPOSIO_SLACK_ACCOUNT_ID` | var | #1 | optional connected-account pin (`ca_…`) |
| `OPS_DIGEST_EMAIL_TO` | var | #4 | recipient of the daily digest |
| `COMPOSIO_OUTLOOK_ACCOUNT_ID` | var | #4 | optional connected-account pin |

### 3. Railway env on `live_overlay_daemon` (for #3)

The daemon reads env from Railway (not GitHub). No build change is needed — the
REST transport is stdlib.

| Name | Notes |
|------|-------|
| `GRAFANA_WEBHOOK_TOKEN` | shared secret embedded in the webhook URL; unset ⇒ endpoint returns 503 |
| `COMPOSIO_API_KEY` | the `ak_…` project key |
| `COMPOSIO_USER_ID` | entity the Slack connection is under (else the send finds no account) |
| `SLACK_ALERT_USER_ID` / `SLACK_ALERT_CHANNEL` | DM target / channel fallback |
| `COMPOSIO_SLACK_ACCOUNT_ID` | optional `ca_…` pin |
| `GITHUB_ISSUE_REPO` | default `skipp-dev/skipp-algo` |

Then point a Grafana contact point (webhook type) at
`https://<daemon-host>/<GRAFANA_WEBHOOK_TOKEN>/grafana-webhook`. To also open a
GitHub issue for a specific alert, add the label `composio_issue: "true"` to
that alert rule — routine alerts stay Slack-only.

## Verification

The Slack REST path was verified live 2026-07-11 (real DM delivered via
`SLACK_OPEN_DM` + `SLACK_SEND_MESSAGE`). To re-verify each surface after
provisioning:

* **#1** — `workflow_dispatch` `credential-health-check` (fires only on
  warn/error) and confirm the Slack DM.
* **#3** — `POST https://<daemon-host>/<token>/grafana-webhook` with a firing
  payload (or Grafana's contact-point Test) and confirm the Slack message.
* **#4** — `workflow_dispatch` `ops-digest-daily` (`dry_run=true` first to
  preview) and confirm the Outlook email.

## Files

* `scripts/composio_ops.py` — shared fail-soft REST wrapper (stdlib urllib)
* `scripts/credential_health_notify.py` — #1
* `scripts/ops_digest.py` — #4
* `services/live_overlay_daemon/grafana_composio_fanout.py` — #3 router
* workflows: `credential-health-check.yml` (step), `ops-digest-daily.yml`

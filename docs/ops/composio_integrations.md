# Composio ops integrations

Cross-app automation for skipp-algo ops, via [Composio](https://composio.dev).
Production and development use different projects; every toolkit has separate
read and write auth configs and explicitly pinned connected accounts.

| # | What | Where it runs | Channel |
|---|------|---------------|---------|
| 1 | Credential-health alert → operator | `credential-health-check.yml` | Slack DM (adds to existing gh issue) |
| 2 | Date-gated reminders → calendar | one-time (done live) | Outlook events |
| 3 | Grafana alert → fan-out | live-overlay daemon (FastAPI) | Slack + opt-in GitHub issue |
| 4 | Daily ops digest | `ops-digest-daily.yml` | Outlook email |
| 5 | Slack ChatOps | live-overlay daemon | read-only status and incidents |
| 6 | Incident lifecycle | Grafana fan-out | dedupe/update/resolve GitHub issues |
| 7 | Calendar sync | `composio-publish.yml` | reviewed Outlook reminders |
| 8 | Research digest | `composio-publish.yml` | weekly Notion page |

## Security and version contract

* `configs/composio_tools.json` is the executable allow-list. Every tool pins
  the live version, access class and required arguments.
* `configs/composio_auth_policy.json` defines least-privilege OAuth scopes.
* Calls without an environment-specific key/user and access-specific `ca_…`
  account ID skip fail-closed. Implicit "first account" selection is forbidden.
* `composio-canary.yml` validates live schemas and runs non-mutating identity
  probes against all read connections every day.
* Slack ChatOps is allow-listed and read-only (`help`, `status`, `incidents`).
  It cannot dispatch workflows, deploy, promote a model or place an order.

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
job**: with no environment-specific project API key every helper returns
`DeliveryResult(skipped=True)` and the caller logs a no-op. Everything is
**inert until provisioned**.

## What you must provision (one-time)

### 1. Composio **project** API key + connected accounts

1. app.composio.dev → **Settings → API Keys** (project settings, *not* the org
   page). The key you need is the **project API key** with prefix **`ak_`** —
   NOT the Organization Access Token (`oak_`), which Composio's API rejects with
   HTTP 401. The full value is only shown once at creation; copy it then.
2. Create two projects named `skipp-algo-prod` and `skipp-algo-dev`, each with
   its own key and entity/user ID.
3. In each project create separate `*-read` and `*-write` auth configs using
   `configs/composio_auth_policy.json`, then connect Slack, GitHub, Outlook and
   Notion once per access class. For Notion, grant only the research parent.
4. A key with **zero connections in its project** authenticates fine but every
   send fails with "no connected account" — verify the connections show up under
   the key's project.

### 2. GitHub Actions secrets/vars (for #1 and #4)

Repo → Settings → Secrets and variables → Actions. **`COMPOSIO_PROD_API_KEY` must be
a SECRET, never a variable** (a variable is world-readable).

| Name | Kind | Used by | Notes |
|------|------|---------|-------|
| `COMPOSIO_PROD_API_KEY` | **secret** | all prod flows | prod-project `ak_…` key |
| `COMPOSIO_PROD_USER_ID` | var | all prod flows | prod entity |
| `SLACK_ALERT_USER_ID` | var | #1 | Slack member id `U…` for the DM (preferred) |
| `SLACK_ALERT_CHANNEL` | var | #1 | fallback channel if no user id |
| `COMPOSIO_SLACK_WRITE_ACCOUNT_ID` | var | #1/#3 | mandatory write connection |
| `OPS_DIGEST_EMAIL_TO` | var | #4 | recipient of the daily digest |
| `COMPOSIO_OUTLOOK_WRITE_ACCOUNT_ID` | var | #4/#7 | mandatory write connection |

The canary additionally requires `COMPOSIO_<TOOLKIT>_READ_ACCOUNT_ID`; every
connection should have the corresponding `*_AUTH_CONFIG_ID` variable. Dev uses
`COMPOSIO_DEV_API_KEY` and `COMPOSIO_DEV_USER_ID` locally or in a separate
GitHub environment.

### 3. Railway env on `live_overlay_daemon` (for #3)

The daemon reads env from Railway (not GitHub). No build change is needed — the
REST transport is stdlib.

| Name | Notes |
|------|-------|
| `GRAFANA_WEBHOOK_TOKEN` | shared secret embedded in the webhook URL; unset ⇒ endpoint returns 503 |
| `COMPOSIO_PROD_API_KEY` | prod `ak_…` project key |
| `COMPOSIO_PROD_USER_ID` | prod entity |
| `SLACK_ALERT_USER_ID` / `SLACK_ALERT_CHANNEL` | DM target / channel fallback |
| `COMPOSIO_SLACK_WRITE_ACCOUNT_ID` | mandatory Slack write `ca_…` pin |
| `COMPOSIO_GITHUB_READ_ACCOUNT_ID` / `COMPOSIO_GITHUB_WRITE_ACCOUNT_ID` | incident lifecycle |
| `COMPOSIO_CHATOPS_WEBHOOK_TOKEN` | secret endpoint token |
| `COMPOSIO_CHATOPS_ALLOWED_USERS` / `COMPOSIO_CHATOPS_ALLOWED_CHANNELS` | comma-separated IDs |
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

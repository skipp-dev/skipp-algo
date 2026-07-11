# Composio ops integrations

Cross-app automation for skipp-algo ops, via [Composio](https://composio.dev)
(one API key → Slack, GitHub, Outlook, …). Four use cases:

| # | What | Where it runs | Channel |
|---|------|---------------|---------|
| 1 | Credential-health alert → operator | `credential-health-check.yml` | Slack DM (adds to existing gh issue) |
| 2 | Date-gated reminders → calendar | one-time (done live) | Outlook events |
| 3 | Grafana alert → fan-out | live-overlay daemon (FastAPI) | Slack + opt-in GitHub issue |
| 4 | Daily ops digest | `ops-digest-daily.yml` | Outlook email |

## Architecture: two execution contexts

* **#2 is already done** — the three reminder events were created directly in
  the operator's Outlook calendar via the Composio MCP tools in a live session.
  Nothing recurring runs for it.
* **#1, #3, #4 run unattended** (GitHub Actions cron; the Railway daemon), where
  the interactive Composio MCP endpoint is unavailable. They use the **Composio
  Python SDK** (`composio>=0.17`) driven by an API key, via a single fail-soft
  wrapper: [`scripts/composio_ops.py`](../../scripts/composio_ops.py).

The wrapper **never raises and never hard-fails a job**: with no
`COMPOSIO_API_KEY`, or the SDK not installed, every helper returns
`DeliveryResult(skipped=True)` and the caller logs a no-op. So all of this is
**inert until you provision it** — merging the PR changes nothing operationally.

## What you must provision (one-time)

Nothing works until these are set. All are optional to the code (fail-soft), but
required to actually deliver.

### 1. Composio API key + connected accounts

1. Create an API key at <https://app.composio.dev>.
2. Authorize the toolkits you want: **slack**, **github**, **outlook** (Outlook
   is already connected for #2; reuse or reconnect for the server-side key).
3. Note each **connected-account id** if you want to pin them explicitly
   (otherwise the default account for `COMPOSIO_USER_ID` is used).

### 2. GitHub Actions secrets/vars (for #1 and #4)

Repo → Settings → Secrets and variables → Actions.

| Name | Kind | Used by | Notes |
|------|------|---------|-------|
| `COMPOSIO_API_KEY` | secret | #1, #4 | the master switch; unset ⇒ everything skips |
| `COMPOSIO_USER_ID` | var | #1, #4 | Composio user/entity (default `default`) |
| `SLACK_ALERT_USER_ID` | var | #1 | Slack member id `U…` for the DM (preferred) |
| `SLACK_ALERT_CHANNEL` | var | #1 | fallback channel if no user id |
| `COMPOSIO_SLACK_ACCOUNT_ID` | var | #1 | optional connected-account pin |
| `OPS_DIGEST_EMAIL_TO` | var | #4 | recipient of the daily digest |
| `COMPOSIO_OUTLOOK_ACCOUNT_ID` | var | #4 | optional connected-account pin |

### 3. Railway env on `live_overlay_daemon` (for #3)

| Name | Notes |
|------|-------|
| `GRAFANA_WEBHOOK_TOKEN` | shared secret embedded in the webhook URL; unset ⇒ endpoint returns 503 |
| `COMPOSIO_API_KEY` | enables actual delivery |
| `COMPOSIO_USER_ID`, `SLACK_ALERT_USER_ID`/`SLACK_ALERT_CHANNEL` | as above |
| `GITHUB_ISSUE_REPO` | default `skipp-dev/skipp-algo` |

Also add `composio>=0.17,<0.18` to the daemon build (e.g. append
`requirements-composio.txt`) — the SDK is imported lazily, so the daemon boots
without it, but delivery needs it installed.

Then point a Grafana contact point (webhook type) at
`https://<daemon-host>/<GRAFANA_WEBHOOK_TOKEN>/grafana-webhook`. To also open a
GitHub issue for a specific alert, add the label `composio_issue: "true"` to
that alert rule — routine alerts stay Slack-only.

## Verification boundary

The calendar events (#2) were created and verified live. The #1/#3/#4 code is
**unit-tested with the SDK mocked** but has **not** been run against a live
`COMPOSIO_API_KEY` — no live delivery has been exercised. After provisioning,
verify each:

* **#1** — `workflow_dispatch` `credential-health-check` (or wait for a real
  warn/error) and confirm the Slack DM arrives.
* **#3** — send a Grafana test notification to the webhook URL; confirm Slack.
* **#4** — `workflow_dispatch` `ops-digest-daily` and confirm the Outlook email;
  use the `dry_run` input first to preview the render without sending.

## Files

* `scripts/composio_ops.py` — shared fail-soft SDK wrapper
* `scripts/credential_health_notify.py` — #1
* `scripts/ops_digest.py` — #4
* `services/live_overlay_daemon/grafana_composio_fanout.py` — #3 router
* `requirements-composio.txt` — optional SDK pin
* workflows: `credential-health-check.yml` (step), `ops-digest-daily.yml`

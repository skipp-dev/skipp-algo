# SMC Live Overlay Daemon — Operations Guide

<!-- markdownlint-disable MD060 MD033 -->

One-stop reference for running, deploying, and debugging the SMC Live Overlay
Daemon on Railway + Grafana Cloud.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Railway](#railway)
3. [Grafana](#grafana)
4. [UptimeRobot Bridge](#uptimerobot-bridge)
5. [GitHub Workflow Bridge](#github-workflow-bridge)
6. [Platform Interaction Matrix](#platform-interaction-matrix)
7. [Credentials](#credentials)
8. [Quick Reference](#quick-reference)

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SMC Live Overlay Daemon                            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────────┐  │
│  │  Databento  │───▶│   feed.py   │───▶│  cache.py / compute.py          │  │
│  │  db.Live()  │    │  (thread)   │    │  (overlay compute + storage)    │  │
│  └─────────────┘    └─────────────┘    └─────────────────────────────────┘  │
│           │                                       │                          │
│           ▼                                       ▼                          │
│   live_overlay_feed_healthy            live_overlay_overlay_fresh           │
│   live_overlay_worker_*_alive          live_overlay_smc_live_latency_*      │
│                                        live_overlay_provider_*              │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         FastAPI (main.py)                            │   │
│   │  GET /health    GET /metrics    GET /{token}/smc_live                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                             │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────┐
              │   Grafana Alloy (metrics proxy)   │
              │  - scrapes /metrics every 30s    │
              │  - basic-auth via OVERLAY_SECRET_TOKEN                       │
              │  - remote-writes to Grafana Cloud Prometheus                 │
              └──────────────────┬───────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────┐
              │      Grafana Cloud                │
              │  - Dashboard (visualisation)      │
              │  - Alert rules (alert-rules.yaml) │
              └──────────────────────────────────┘
                                 ▲
                                 │
              ┌──────────────────┴───────────────┐
              │   UptimeRobot API Bridge          │
              │  - optional free-tier polling    │
              │  - exposes per-monitor status    │
              └──────────────────────────────────┘
                                 ▲
                                 │
              ┌──────────────────┴───────────────┐
              │   GitHub Workflow Bridge          │
              │  - monitors workflow run status  │
              │  - cached TTL polling            │
              └──────────────────────────────────┘
```

### What Alloy scrapes

Alloy polls the daemon's `/metrics` endpoint and forwards the series to Grafana
Cloud Prometheus. The job name seen in Grafana is `live_overlay`.

Required Alloy environment variables:

| Variable | Source | Purpose |
|----------|--------|---------|
| `OVERLAY_SECRET_TOKEN` | Same as daemon | Basic-auth password for `/metrics` |
| `OVERLAY_SERVICE_URL` | Railway host:port without scheme, e.g. public `liveoverlaydaemon-production.up.railway.app` or private `liveoverlaydaemon.railway.internal:<PORT>` | Scrape target host:port |
| `GRAFANA_CLOUD_PROM_URL` | Grafana Cloud stack settings | Remote-write URL |
| `GRAFANA_CLOUD_USER` | Grafana Cloud stack settings | Remote-write user |
| `GRAFANA_CLOUD_API_KEY` | Grafana Cloud API key | Remote-write password |

Alloy config file: `services/live_overlay_daemon/infra/alloy/config.alloy`

---

## Railway

### Service configuration

File: `services/live_overlay_daemon/railway.toml`

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "services/live_overlay_daemon/Dockerfile"

[deploy]
startCommand = "uvicorn services.live_overlay_daemon.main:app --host 0.0.0.0 --port $PORT --workers 1 --http h11 --loop asyncio"
healthcheckPath = "/health"
healthcheckTimeout = 60
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3

[[services]]
name = "live_overlay_daemon"
```

### Environment variables

#### Daemon (`live_overlay_daemon`)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABENTO_API_KEY` | yes | — | Databento live feed API key |
| `OVERLAY_SECRET_TOKEN` | yes | — | HMAC + `/metrics` basic-auth secret |
| `PORT` | yes | Railway injects | HTTP listen port |
| `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` | no | `0` | Set to `1` in production deployments that should receive TradingView/Pine `/smc_live` traffic during US market-open windows; arms the first-zero traffic alert |
| `LIVE_OVERLAY_INGEST_QUEUE_MAX` | no | 10000 | Max queued bars before drop |
| `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` | no | `0` | Set to `1` in production deployments that should receive TradingView/Pine `/smc_live` traffic during US market-open windows. Arms the first-zero traffic alert. Leave `0` for local/dev/warm-standby. |
| `LIVE_OVERLAY_RESTART_CAUSE` | no | — | Label for `live_overlay_daemon_restart_cause_*_total` |
| `LOG_LEVEL` | no | `INFO` | Python log level |
| `OVERLAY_FLOW_REFRESH_SECS` | no | — | Flow refresh interval |
| `OVERLAY_MAX_FEED_FAILURES` | no | — | Circuit breaker threshold |
| `OVERLAY_MAX_STALE_SECS` | no | — | Staleness threshold |
| `OVERLAY_MAX_SYMBOLS` | no | — | Symbol limit |
| `OVERLAY_NEWS_CACHE_TTL_SECS` | no | — | News cache TTL |
| `NEWS_SNAPSHOT_URL` | no | — | Optional HTTPS URL for live news snapshot |
| `NEWS_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `NEWS_SNAPSHOT_URL` |
| `NEWS_SNAPSHOT_PATH` | no | `artifacts/live_overlay/news_snapshot.json` | Local news snapshot path; point at the volume (`/data/...`) for write-through persistence |
| `SIGNALS_SNAPSHOT_PATH` | no | — | Local realtime-signals snapshot path |
| `SIGNALS_SNAPSHOT_URL` | no | — | Optional HTTPS URL for realtime-signals snapshot |
| `SIGNALS_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `SIGNALS_SNAPSHOT_URL` |
| `SIGNALS_SERVICE_URL` | no | — | Internal Railway hostname/URL of `smc-signals-producer`; takes precedence |
| `SIGNALS_INTERNAL_TOKEN` | no | — | Bearer token used when calling `SIGNALS_SERVICE_URL` |
| `OVERLAY_SIGNALS_CACHE_TTL_SECS` | no | — | Signals snapshot cache TTL |
| `OVERLAY_SIGNALS_MAX_AGE_SECS` | no | — | Signals staleness threshold |
| `EXPERIMENT_SNAPSHOT_PATH` | no | `artifacts/live_overlay/plan_2_8_tf_family_rollup.json` | Local daily experiment rollup snapshot path |
| `EXPERIMENT_SNAPSHOT_URL` | no | — | Optional HTTPS URL for experiment rollup snapshot |
| `EXPERIMENT_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `EXPERIMENT_SNAPSHOT_URL` |
| `EXPERIMENT_HISTORY_PATH` | no | — | Local daily experiment history JSONL path |
| `EXPERIMENT_HISTORY_URL` | no | — | Optional HTTPS URL for experiment history JSONL |
| `EXPERIMENT_HISTORY_URL_TOKEN` | no | — | Optional bearer token for `EXPERIMENT_HISTORY_URL` |
| `OVERLAY_EXPERIMENT_CACHE_TTL_SECS` | no | — | Experiment rollup/history cache TTL |
| `OVERLAY_EXPERIMENT_MAX_AGE_SECS` | no | — | Experiment snapshot staleness threshold |
| `OVERLAY_EXPERIMENT_HISTORY_MAX_DAYS` | no | — | Max history days exposed as metrics |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_PATH` | no | `artifacts/live_overlay/credential_health.json` | Local daily credential-health report (TradingView storage-state age) |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` | no | — | Optional HTTPS URL for the credential-health report |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` |
| `OVERLAY_TRADINGVIEW_CREDENTIAL_CACHE_TTL_SECS` | no | — | Credential-health report cache TTL (default 3600) |
| `OVERLAY_REFRESH_SECS` | no | — | Full compute refresh interval |
| `OVERLAY_ROLLING_BARS` | no | — | Rolling bar window |

#### Bridges (optional, co-deployed in same service)

| Variable | Bridge | Purpose |
|----------|--------|---------|
| `UPTIMEROBOT_API_KEY` | UptimeRobot | Free-tier API key |
| `UPTIMEROBOT_MONITOR_IDS` | UptimeRobot | Comma-separated monitor IDs to poll; production allowlist: `803309701,803341452,803343155,803343156,803362511` |
| `UPTIMEROBOT_POLL_TTL_SECS` | UptimeRobot | Cache TTL (default 30) |
| `UPTIMEROBOT_TIMEOUT_SECS` | UptimeRobot | HTTP timeout (default 5) |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | GitHub | PAT with `repo` + `actions:read` |
| `GITHUB_WORKFLOW_MONITOR_REPO` | GitHub | `owner/repo` to watch (validated; invalid value falls back to `skippALGO/skipp-algo`) |
| `GITHUB_WORKFLOW_MONITOR_IDS` | GitHub | Workflow IDs or names to monitor |
| `GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS` | GitHub | Cache TTL |
| `GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS` | GitHub | HTTP timeout |
| `GITHUB_WORKFLOW_MONITOR_PER_PAGE` | GitHub | Pagination page size |

### Expected market traffic alert rollout

`LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` controls whether the deployment expects
`/smc_live` request traffic during US market-open windows.

- `0` default: first-zero traffic alerting is disabled.
- `1`: alert when US market is open, the daemon has been up for more than
  10 minutes, and `/smc_live` request traffic remains near zero.

Production deployments that should receive TradingView/Pine traffic must set:

```env
LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1
```

After rollout, verify:

```promql
live_overlay_expected_market_traffic{job="live_overlay"} == 1
```

If the deployment is local, dev, or warm-standby, leave the value at `0`.

#### Alloy service

| Variable | Purpose |
|----------|---------|
| `OVERLAY_SECRET_TOKEN` | `/metrics` basic-auth password |
| `OVERLAY_SERVICE_URL` | Scrape target without scheme, e.g. `liveoverlaydaemon-production.up.railway.app` or `liveoverlaydaemon.railway.internal:<PORT>` |
| `GRAFANA_CLOUD_PROM_URL` | Grafana Cloud remote-write URL |
| `GRAFANA_CLOUD_USER` | Grafana Cloud stack user |
| `GRAFANA_CLOUD_API_KEY` | Grafana Cloud API key |

### Snapshot delivery & volume persistence

The daemon serves four producer-side snapshots (news, realtime signals, daily
experiment rollup/history, and the TradingView credential-age report). Each
loader is **URL-first**: when the matching `*_SNAPSHOT_URL` is set it fetches
the freshest payload over HTTPS (GitHub Contents API raw, fine-grained PAT),
otherwise it falls back to the local `*_SNAPSHOT_PATH`. Default `*_SNAPSHOT_PATH` values for the three CI-produced snapshots (news,
experiment rollup/history, TradingView credential report) point at tracked seed
files under `artifacts/live_overlay/` so the daemon renders data out of the
box. Realtime signals remain host-only and still default to
`artifacts/open_prep/latest/latest_realtime_signals.json`. CI producers push
fresher snapshots to dedicated `bot/*` cache branches (exempt from the
`main-governance` ruleset, see ADR-0024); off-host daemons should set the
matching `*_SNAPSHOT_URL` / `*_HISTORY_URL` to consume those instead.

| Snapshot | Producer workflow | Bot branch | Bot-branch stable path | Default seed path |
|----------|-------------------|------------|------------------------|-------------------|
| News | `smc-live-newsapi-refresh.yml` | `bot/live-news-snapshot` | `artifacts/smc_microstructure_exports/smc_live_news_snapshot.json` | `artifacts/live_overlay/news_snapshot.json` |
| Experiment rollup + history | `smc-measurement-benchmark-rolling.yml` | `bot/live-experiment-snapshot` | `artifacts/ci/measurement_benchmark_rolling/latest/plan_2_8_tf_family_rollup.json` and `.../latest/plan_2_8_history.jsonl` | `artifacts/live_overlay/plan_2_8_tf_family_rollup.json` / `plan_2_8_history.jsonl` |
| TradingView credential age | `credential-health-check.yml` | `bot/live-tv-credential-snapshot` | `artifacts/credential_health/latest/credential_health.json` | `artifacts/live_overlay/credential_health.json` |
| Realtime signals | _host helper (no CI producer)_ | `bot/live-signals-snapshot` | `artifacts/open_prep/latest/latest_realtime_signals.json` | `artifacts/open_prep/latest/latest_realtime_signals.json` |

`smc-measurement-benchmark-rolling.yml` writes temporary per-timeframe
`structure_export_*.json` files only for inline notices and deletes them in the
same step so they do not leak into later jobs/artifacts.

The `*_URL` form is `https://api.github.com/repos/skippALGO/skipp-algo/contents/<stable-path>?ref=<bot-branch>` with a fine-grained PAT (`Contents: Read`, repo `skipp-algo` only) in the matching `*_URL_TOKEN`.

**Realtime signals on Railway are fetched live from `smc-signals-producer`.**
Set `SIGNALS_SERVICE_URL` to the Railway private hostname/URL and
`SIGNALS_INTERNAL_TOKEN` to the producer bearer token. The daemon calls the
producer's `/signals.json` endpoint first and only falls back to
`SIGNALS_SNAPSHOT_URL` / `SIGNALS_SNAPSHOT_PATH` when the producer is
unreachable or unconfigured.

**Realtime signals have no CI producer.** `latest_realtime_signals.json` is
written only by `open_prep/realtime_signals.py` on the live trading host. Run
[`scripts/publish_signals_snapshot.py`](../../scripts/publish_signals_snapshot.py)
on that host (cron / after each engine cycle) with `GH_TOKEN` set to a PAT that
can push to `bot/*`; it publishes to `bot/live-signals-snapshot` using
`--force-with-lease` semantics, including a race-safe first-publish guard with
an all-zeros expected SHA
(`refs/heads/<branch>:0000000000000000000000000000000000000000`) and strict branch-name
validation to avoid option-injection via `--branch`. After publish,
`SIGNALS_SNAPSHOT_URL` works exactly like the news/experiment URLs:

```bash
GH_TOKEN=<push-pat> .venv/bin/python3.12 scripts/publish_signals_snapshot.py
```

Run it as a **separate, scheduled sync job** (decoupled from
`open_prep/realtime_signals.py`) so a delivery hiccup never blocks the trading
engine. A 2-minute `cron` entry on the live host is enough:

```cron
# /etc/cron.d/skipp-signals-snapshot  (live trading host)
*/2 * * * * appuser cd /opt/skipp-algo && GH_TOKEN=<push-pat> .venv/bin/python3.12 scripts/publish_signals_snapshot.py >> /var/log/skipp/signals_snapshot.log 2>&1
```

The script is idempotent (it exits `0` without a push when the snapshot is
unchanged), so over-scheduling only wastes a no-op run.

If the initial remote fetch fails for reasons other than the expected
"remote ref not found" first-publish case, the helper emits a redacted warning
to stderr before creating/seeding the local branch.

Runtime URL fetchers in `compute.py` also scope the GitHub raw `Accept` header
to actual GitHub Contents API URLs only, avoiding GitHub-specific headers on
authenticated non-GitHub snapshot endpoints.

**Write-through persistence (Railway volume).** On every successful `*_URL`
fetch the daemon atomically writes the payload back to its `*_SNAPSHOT_PATH`
(`tempfile` + `os.replace`). Mount a Railway volume and point the `*_PATH`
vars at it so a cold start (or a momentary URL outage) reads the last-good
copy from the volume instead of the baked seed.

- Create the volume (interactive — pick service `live_overlay_daemon`, mount path `/data`):

```bash
railway volume add
```

- The volume mounts as **root**. The daemon image runs as a non-root
  `appuser`, so writes to `/data` fail unless the service runs as root.
  Set `RAILWAY_RUN_UID=0` to enable write-through (the write-through is
  best-effort: without it the daemon still serves fresh data from the URL,
  it just cannot persist across restarts).
- Volumes are **not** config-as-code; do not add them to `railway.toml`
  (only `build`/`deploy` settings are supported there).

### Common Railway CLI commands

```bash
# Login (once)
railway login

# Link to project
railway link

# Show service status
railway status

# Tail logs for the daemon
railway logs -s live_overlay_daemon -f

# Tail logs for the Alloy collector
railway logs -s metrics-collector -f

# Deploy current branch
railway up

# Run a one-off shell in the daemon container
railway run --service live_overlay_daemon bash

# Pull remote env vars to local .env
railway variable list --service live_overlay_daemon
```

---

## Grafana

### Production dashboard

**[SMC Live Overlay Daemon](https://bronzeporridge977.grafana.net/d/smc-live-overlay-v1/smc-live-overlay-daemon)**

Source JSON:
`services/live_overlay_daemon/infra/grafana/dashboard.json`

### Success Rate panel and no-traffic semantics

The **Success Rate (%)** panel shows the percentage of recent `/smc_live`
compute cycles that completed without errors.

#### Historical bug: "0.00 %" with no traffic

Before `fix(live-overlay): always emit traffic counters and guarantee tzdata
availability` (`50995c03`), the traffic counters
`live_overlay_smc_live_requests_total` and
`live_overlay_smc_live_success_total` were only created when the `/smc_live`
endpoint was actually invoked. On a fresh daemon start with no traffic, these
series were absent from `/metrics`. Grafana's `rate()` over a missing series
returns no data, which the panel rendered as `0.00 %`. This looked like a
service outage even though the daemon was healthy and simply had no requests.

The same root cause made the **Market-open Request Health** panel flip between
`MARKET_CLOSED` and `OPEN_NO_TRAFFIC` because the synthetic signal depends on
whether request traffic is present.

#### Code fix

`services/live_overlay_daemon/metrics.py` now seeds the traffic counters to
`0.0` on every metrics render, so the series always exist in Prometheus even
before the first request:

- `live_overlay_smc_live_requests_total`
- `live_overlay_smc_live_success_total`
- `live_overlay_smc_live_errors_total`
- `live_overlay_smc_live_auth.denied`
- `live_overlay_smc_live_bad_tf.total`
- `live_overlay_smc_live_cache_miss.total`
- `live_overlay_smc_live_stale_served.total`

Additionally, `services/live_overlay_daemon/Dockerfile` now installs the
`tzdata` package so `ZoneInfo("America/New_York")` resolves correctly in the
container. Without it, market-open detection fell back to UTC hours and could
report the market as closed at the wrong time.

#### Dashboard UX hardening

To prevent the panel from showing a misleading percentage when the request rate
is exactly zero, the Success Rate query uses PromQL `unless on()` to drop the
result when no traffic has occurred in the selected interval:

```promql
100 * (
  sum(rate(live_overlay_smc_live_success_total{job=~"$job"}[$__rate_interval]))
  /
  sum(rate(live_overlay_smc_live_requests_total{job=~"$job"}[$__rate_interval]))
)
unless on()
sum(rate(live_overlay_smc_live_requests_total{job=~"$job"}[$__rate_interval])) == 0
```

The panel's field config sets `noValue: "NO TRAFFIC"`, so Grafana displays
**NO TRAFFIC** instead of `0.00 %` when the query returns no data. As soon as
traffic appears, the series becomes non-zero and the panel shows the real
success rate again.

#### Market Traffic Health wiring

The **Market Traffic Health** signal is intentionally US-regular-session gated
via `live_overlay_market_us_open`. Europe/Asia session gauges are displayed for
context, but `/smc_live` traffic expectations are evaluated against the US
regular session only.

Therefore the panel expression reads:

```promql
(live_overlay_market_us_open{job=~"$job"} or vector(0))
+ ((live_overlay_market_us_open{job=~"$job"} or vector(0))
   * ((rate(live_overlay_smc_live_requests_total{job=~"$job"}[5m]) or vector(0)) > bool 0.001))
```

- `0` = `MARKET_CLOSED` — US regular session is closed.
- `1` = `OPEN_NO_TRAFFIC` — US regular session is open, but the request rate is
  effectively zero.
- `2` = `TRAFFIC_OK` — US regular session is open and `/smc_live` traffic is
  present.

#### Expected market traffic alert rollout

`LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` controls whether the deployment expects
`/smc_live` request traffic during US market-open windows.

- `0` default: first-zero traffic alerting is disabled.
- `1`: alert when US market is open, the daemon has been up for more than
  10 minutes, and `/smc_live` request traffic remains near zero.

Production deployments that should receive TradingView/Pine traffic must set:

```env
LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1
```

After rollout, verify:

```promql
live_overlay_expected_market_traffic{job="live_overlay"} == 1
```

Local, dev, and warm-standby deployments should normally leave the value at
`0`.


### Dashboard masking semantics

The dashboard intentionally masks data in a few panels so on-call does not
chase false reds:

- **Market Data Freshness** — computed only while `live_overlay_market_us_open`
  is `1`. When the selected interval contains no US market-open samples, Grafana
  shows `MARKET CLOSED` via `noValue` instead of `0.00 %`.

- **External Checks** — votes only from bridges that are enabled
  (`live_overlay_*_bridge_enabled == 1`). When neither UptimeRobot nor GitHub
  Workflow bridges are enabled, the panel shows `NO CHECKS CONFIGURED`
  (`-1`) instead of `SCRAPE ERROR` (`0`).

- **Core Metrics Present** — counts how many of the critical series are
  missing (`uptime_seconds`, `overlay_fresh`, `market_us_open`,
  `last_bar_age_known`, `smc_live_requests_total`, `smc_live_success_total`,
  `smc_live_errors_total`, `smc_live_latency_ms_count`). A partial exporter
  regression that still serves `uptime_seconds` but drops the others now
  turns red.

- **Railway Metrics Bridge** — uses the generic bridge contract:
  `live_overlay_bridge_enabled{bridge="railway_metrics"}` +
  `live_overlay_bridge_scrape_success{bridge="railway_metrics"}`. It
  distinguishes `DISABLED` (`0`), `SCRAPE ERROR` (`1`) and `OK` (`2`).


### Generic bridge troubleshooting contract

| State | Expected metrics | Operational meaning |
|-------|------------------|---------------------|
| Disabled / not configured | `live_overlay_bridge_enabled{bridge="<name>"} == 0` | Bridge is intentionally not active; this should not alert as a scrape failure. |
| Enabled and healthy | `live_overlay_bridge_enabled == 1` and `live_overlay_bridge_scrape_success == 1` | Last scrape succeeded. |
| Enabled and failed | `live_overlay_bridge_enabled == 1` and `live_overlay_bridge_scrape_success == 0` | Bridge is configured but currently failing; investigate bridge logs and last error. |
| Stale success | `live_overlay_bridge_last_success_age_seconds` exceeds threshold | Bridge may be failing or unable to refresh successful data. |
| Absent bridge metrics | no `live_overlay_bridge_*` series | Exporter or metrics path may be broken; check `Core Metrics Present` and collector targets. |


### Dashboard upsert via API

Use the following Python snippet to push the dashboard JSON from a checkout.
Requires a Grafana Cloud API key with `Editor` or `Admin` role stored in the
keychain as `skipp.grafana.api`.

```python
# scripts/grafana_dashboard_upsert.py  (run from repo root)
import json
import subprocess
import urllib.request
from pathlib import Path

DASHBOARD_UID = "smc-live-overlay-v1"
DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")
GRAFANA_URL = "https://bronzeporridge977.grafana.net"

# Read API key from macOS Keychain entry "skipp.grafana.api"
api_key = subprocess.run(
    ["security", "find-generic-password", "-s", "skipp.grafana.api", "-w"],
    capture_output=True, text=True, check=True,
).stdout.strip()

payload = {
    "dashboard": json.loads(DASHBOARD_PATH.read_text(encoding="utf-8")),
    "overwrite": True,
    "message": "Automated dashboard upsert from repo",
}
payload["dashboard"]["uid"] = DASHBOARD_UID
payload["dashboard"]["id"] = None

req = urllib.request.Request(
    f"{GRAFANA_URL}/api/dashboards/db",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(resp.status, resp.read().decode("utf-8"))
```

### Pull-back workflow (when someone edited in the UI)

```bash
# 1. Export current dashboard JSON from Grafana API
GRAFANA_URL="https://bronzeporridge977.grafana.net"
API_KEY=$(security find-generic-password -s skipp.grafana.api -w)
curl -s -H "Authorization: Bearer $API_KEY" \
  "$GRAFANA_URL/api/dashboards/uid/smc-live-overlay-v1" \
  | jq '.dashboard' \
  > services/live_overlay_daemon/infra/grafana/dashboard.json

# 2. Re-apply idempotent UX transforms
python scripts/update_overlay_dashboard.py
# Optional: substitute concrete Railway console IDs so dashboard links point to
# the live-overlay service instead of placeholder URLs:
#   RAILWAY_PROJECT_ID=<id> RAILWAY_ENVIRONMENT_ID=<id> \
#     RAILWAY_LIVE_OVERLAY_SERVICE_ID=<id> \
#     python scripts/update_overlay_dashboard.py

# 3. Review diff, commit, open PR
git diff services/live_overlay_daemon/infra/grafana/dashboard.json
```

### Alert rules deploy

File (source of truth): `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`

Deploy with the idempotent one-liner (run from the repo root):

```bash
python scripts/grafana_alert_rules_upsert.py            # validate + apply
python scripts/grafana_alert_rules_upsert.py --dry-run  # validate only, no network
```

The script parses the file and upserts each rule **group** via
`PUT /api/v1/provisioning/folder/{folderUID}/rule-groups/{group}`, which
overwrites the whole group — new rules are added, changed rules updated, and
rules deleted from the YAML are removed. Re-running it is safe and converges the
live state 1:1 to the repo. The Grafana folder is resolved by name (created if
missing); rules are pushed with `X-Disable-Provenance: true` so they stay
editable in the UI.

Auth: `GRAFANA_API_KEY` env var (CI) or the macOS Keychain entry
`skipp.grafana.api` (local). The token is never printed.

> ⚠️ Do **not** `curl --data-binary @alert-rules.yaml` to
> `POST /api/v1/provisioning/alert-rules`. That endpoint creates a _single_ rule
> and ignores the `groups:` file-provisioning envelope, so it silently fails to
> provision the rule set — this is how alerting previously drifted from the repo.
> Use the script above instead.

Validation runs automatically before any network call, and
`tests/test_grafana_alert_rules_upsert.py` enforces the same checks in CI
(unique UIDs, valid condition references, parseable intervals), so a malformed
`alert-rules.yaml` fails the build instead of failing silently at deploy time.

### Keychain auth

Store the Grafana Cloud API key in the macOS Keychain:

```bash
security add-generic-password -s "skipp.grafana.api" -a "$USER" -w "<API_KEY>"
# Retrieve
security find-generic-password -s skipp.grafana.api -w
```

### PromQL conventions

#### Market-gating

Only alert on feed health when the US session is open (the feed is US equities;
`live_overlay_market_us_open` gates feed/traffic/SLO, while `live_overlay_market_open`
is the broadened US-or-EU display gauge):

```promql
live_overlay_market_us_open{job="live_overlay"}
  * (1 - live_overlay_feed_healthy{job="live_overlay"})
```

#### Banner / top-line formula

The Overall Health ampel uses:

```promql
live_overlay_health_status_code{job=~"$job"} or vector(0)
```

Value mappings:

| Value | Label | Meaning |
|-------|-------|---------|
| 3 | HEALTHY | Feed, workers, overlay all healthy |
| 2 | IDLE | Market closed before the first bar |
| 1 | STARTING | Daemon still waiting on feed, workers or overlay freshness |
| 0 | UNKNOWN | Status metric missing or scrape not available |

#### Deploy/restart annotations

```promql
resets(live_overlay_uptime_seconds{job=~"$job"}[1m]) > 0
or
sum by (__name__) (
  increase({__name__=~"live_overlay_daemon_restart_cause_.*_total",job=~"$job"}[1m])
) > 0
```

---

## UptimeRobot Bridge

Implementation: `services/live_overlay_daemon/uptimerobot_bridge.py`

### What it does (UptimeRobot bridge)

- Polls the UptimeRobot V2 `getMonitors` endpoint.
- Caches results in-process for `UPTIMEROBOT_POLL_TTL_SECS`.
- Emits Prometheus gauges for each configured monitor.

### Exported metrics (UptimeRobot bridge)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `live_overlay_uptimerobot_bridge_enabled` | gauge | — | 1 if the bridge is configured |
| `live_overlay_uptimerobot_scrape_success` | gauge | — | 1 if last poll succeeded |
| `live_overlay_uptimerobot_snapshot_age_seconds` | gauge | — | Seconds since last successful poll |
| `live_overlay_uptimerobot_monitors_up_total` | gauge | — | Count of monitors currently UP |
| `live_overlay_uptimerobot_monitors_down_total` | gauge | — | Count of monitors currently DOWN |
| `live_overlay_uptimerobot_monitors_paused_total` | gauge | — | Count of monitors currently PAUSED |
| `live_overlay_uptimerobot_monitor_response_time_ms_avg` | gauge | — | Average response time across monitors |
| `live_overlay_uptimerobot_monitor_<id>_up` | gauge | monitor id | 1 if monitor is UP |
| `live_overlay_uptimerobot_monitor_<id>_status_code` | gauge | monitor id | Raw UptimeRobot status code |
| `live_overlay_uptimerobot_monitor_<id>_response_time_ms` | gauge | monitor id | Per-monitor response time |

### Status code mapping

| Code | Grafana label | Meaning |
|------|---------------|---------|
| 0 | PAUSED | Monitor intentionally paused |
| 1 | NOT CHECKED | Not yet checked |
| 2 | UP | Healthy |
| 8 | DOWN | Seems down |
| 9 | DOWN | Confirmed down |
| other | UNKNOWN | Unrecognized |

### Setup

1. Get a free UptimeRobot API key.
2. Add `UPTIMEROBOT_API_KEY` to the `live_overlay_daemon` Railway service.
3. Add `UPTIMEROBOT_MONITOR_IDS` as a comma-separated allowlist. Production
   currently monitors:

   ```env
   UPTIMEROBOT_MONITOR_IDS=803309701,803341452,803343155,803343156,803362511
   ```

4. Restart the daemon.

---

## GitHub Workflow Bridge

Implementation: `services/live_overlay_daemon/github_workflow_bridge.py`

### What it does

- Polls GitHub Actions workflow run status for a configured repo.
- Caches results in-process for `GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS`.
- Exposes aggregate scrape success/failure metrics.
- Uses one-page polling intentionally: GitHub returns runs newest-first and the
  bridge only needs "latest run" state per configured workflow.
- Percent-encodes owner/repo segments in API URLs defensively.

### Required env vars

| Variable | Purpose |
|----------|---------|
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | GitHub PAT (`repo` + `actions:read`) |
| `GITHUB_WORKFLOW_MONITOR_REPO` | Repository in `owner/repo` format |
| `GITHUB_WORKFLOW_MONITOR_IDS` | Workflow IDs or file names to watch |
| `GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS` | In-process cache TTL |
| `GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS` | HTTP timeout |
| `GITHUB_WORKFLOW_MONITOR_PER_PAGE` | Pagination page size |

### Exported metrics

| Metric | Type | Description |
|--------|------|-------------|
| `live_overlay_github_workflow_bridge_enabled` | gauge | 1 if bridge is configured |
| `live_overlay_github_workflow_scrape_success` | gauge | 1 if last poll succeeded |
| `live_overlay_github_workflow_snapshot_age_seconds` | gauge | Seconds since last successful poll |

---

## Platform Interaction Matrix

| Source | Destination | Protocol | Auth | Direction | Data |
|--------|-------------|----------|------|-----------|------|
| Databento | Daemon `feed.py` | Databento db.Live (TCP/TLS) | `DATABENTO_API_KEY` | Inbound | ohlcv-1m bars |
| TradingView Pine | Daemon `main.py` | HTTPS | URL path token (`OVERLAY_SECRET_TOKEN`) | Inbound | Overlay JSON |
| Daemon `/metrics` | Grafana Alloy | HTTP | Basic auth (`OVERLAY_SECRET_TOKEN`) | Outbound | Prometheus metrics |
| Alloy | Grafana Cloud Prometheus | HTTPS/TLS | `GRAFANA_CLOUD_API_KEY` | Outbound | Remote-write samples |
| Grafana Cloud | Operators | HTTPS | Grafana session/API key | Outbound | Dashboards, alerts |
| Daemon | UptimeRobot API | HTTPS | `UPTIMEROBOT_API_KEY` | Outbound | Monitor status poll |
| Daemon | GitHub API | HTTPS | `GITHUB_WORKFLOW_MONITOR_TOKEN` | Outbound | Workflow run status |
| Railway healthcheck | Daemon `/health` | HTTP | none | Inbound | 200 OK liveness |
| UptimeRobot probe | Daemon `/health` | HTTP/HTTPS | none | Inbound | HEAD/GET probe |

---

## Credentials

### Keychain entries

| Keychain service | Used by | Rotation steps |
|------------------|---------|----------------|
| `skipp.grafana.api` | Grafana dashboard/alert API ops | 1. Generate new key in Grafana Cloud.<br>2. `security add-generic-password -s skipp.grafana.api -a "$USER" -w "<new>"`.<br>3. Revoke old key. |

### Railway variables (sensitive)

| Variable | Rotation steps |
|----------|----------------|
| `DATABENTO_API_KEY` | 1. Create new key in Databento portal.<br>2. Update Railway variable.<br>3. Redeploy daemon.<br>4. Revoke old key after health OK. |
| `OVERLAY_SECRET_TOKEN` | 1. Generate new random secret.<br>2. Update in Railway for both daemon and Alloy services.<br>3. Redeploy both services.<br>4. Update TradingView Pine script URL tokens if path-token auth is used. |
| `UPTIMEROBOT_API_KEY` | 1. Regenerate in UptimeRobot dashboard.<br>2. Update Railway variable.<br>3. Redeploy. |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | 1. Create new GitHub PAT with `repo` + `actions:read`.<br>2. Update Railway variable.<br>3. Redeploy.<br>4. Delete old PAT. |
| `GRAFANA_CLOUD_API_KEY` | 1. Create new MetricsPublisher/API key in Grafana Cloud.<br>2. Update Railway Alloy service variable.<br>3. Redeploy Alloy.<br>4. Revoke old key. |

---

## Quick Reference

### Deploy from local checkout

```bash
cd services/live_overlay_daemon
railway up
```

### Restart the daemon

```bash
railway redeploy --service live_overlay_daemon
```

### Check current health

```bash
curl -s https://<your-railway-domain>/health | jq .
```

### Fetch metrics locally (if port-forwarded)

```bash
curl -s -u metrics:$OVERLAY_SECRET_TOKEN \
  http://localhost:$PORT/metrics \
  | grep live_overlay_feed_healthy
```

### Regenerate dashboard JSON after manual edits

```bash
python scripts/update_overlay_dashboard.py
```

### Push dashboard to Grafana Cloud

```bash
python scripts/grafana_dashboard_upsert.py
```

### Pull dashboard back from Grafana Cloud

```bash
./scripts/grafana_dashboard_pullback.sh
python scripts/update_overlay_dashboard.py
```

### Run overlay-specific tests

```bash
python -m pytest tests/test_update_overlay_dashboard.py -v
python -m pytest tests/test_smc_live_overlay_metrics.py -v
python -m pytest tests/test_live_overlay_infra_alloy_contracts.py -v
```

### Common incident triage

| Symptom | First check | Command / Link |
|---------|-------------|----------------|
| Feed unhealthy while market open | Railway logs | `railway logs -s live_overlay_daemon -f` |
| Workers unhealthy | Worker Liveness panel | Grafana dashboard |
| Overlay stale | Compute cycle logs | `railway logs -s live_overlay_daemon -f` |
| Bridge scrape error | API tokens / quotas | UptimeRobot / GitHub status pages |
| Grey vertical lines on time-series | Recent deploy/restart | Grafana annotations |

---

_Last updated: 2026-06-23 — aligned with workflow timeline, trading-signals, and daily-experiment observability docs._

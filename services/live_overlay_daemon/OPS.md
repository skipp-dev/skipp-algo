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
| `OVERLAY_SERVICE_URL` | Railway host:port without scheme. Production uses private networking: `liveoverlaydaemon.railway.internal:8080` | Scrape target host:port |
| `GRAFANA_CLOUD_PROM_URL` | Grafana Cloud stack settings | Remote-write URL |
| `GRAFANA_CLOUD_USER` | Grafana Cloud stack settings | Remote-write user |
| `GRAFANA_CLOUD_API_KEY` | Grafana Cloud API key | Remote-write password |

Alloy config file: `services/live_overlay_daemon/infra/alloy/config.alloy`

Alloy self-metrics are scraped as `job="alloy"`. The alert
`alloy-remote-write-failures` pages when
`increase(prometheus_remote_storage_samples_failed_total{job="alloy"}[10m]) > 0`,
so remote-write drops are visible even when the scrape targets themselves still
look healthy.

Private Railway networking is required in production. Do not set a bare
`.railway.internal` host; always include `host:port`.

Use Railway service-variable references so the dependency is visible in the
Railway canvas and does not depend on copy/pasted literals:

```bash
railway variable set -s metrics-collector -e production \
  'OVERLAY_SERVICE_URL=${{live_overlay_daemon.RAILWAY_PRIVATE_DOMAIN}}:8080'

railway variable set -s metrics-collector -e production \
  'SIGNALS_SERVICE_URL=${{smc-signals-producer.RAILWAY_PRIVATE_DOMAIN}}:8080'
```

`PORT` is runtime-injected by Railway and is not a stored variable, so
`${{service.PORT}}` references are not safe. Pin `PORT=8080` explicitly on
`live_overlay_daemon` and `smc-signals-producer`.

Confirm scraper health after any variable change:

```promql
up{job="live_overlay"} == 1
```

---

## Railway

### Service configuration

File: `services/live_overlay_daemon/railway.toml`

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "services/live_overlay_daemon/Dockerfile"

[deploy]
startCommand = "python -m services.live_overlay_daemon.main"
healthcheckPath = "/health"
healthcheckTimeout = 60
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3

[[services]]
name = "live_overlay_daemon"
```

### Deployment

The daemon deploys **only via CI**, not Railway's native GitHub trigger — its
Railway service source is intentionally `none`, so a merge to `main` never
auto-deploys on Railway's side. Instead
`.github/workflows/deploy-live-overlay-daemon.yml` runs on every `main` push
that touches `services/live_overlay_daemon/**` (or on `workflow_dispatch`) and
calls `scripts/deploy_live_overlay.sh`, which stamps the git commit + branch
into the image (`build_stamp.txt`) and runs `railway up`. A verify step then
polls Railway until the new deployment reaches `SUCCESS`, so a build/healthcheck
failure fails CI instead of silently leaving the old container running.

- Repo secret **`RAILWAY_TOKEN`** must be a Railway **project token** scoped to
  the `production` environment — an account/API token yields
  `Invalid RAILWAY_TOKEN`. Without the secret the workflow no-ops with a notice.
- **Manual deploy**: `scripts/deploy_live_overlay.sh` from a clean checkout
  (needs a local `railway login`), or re-run the workflow from the Actions UI.
- **Never** use Railway's "Redeploy" button for a code update — it re-runs the
  *existing* image (same commit); that caused two silent no-op redeploys on
  2026-07-06.
- **Verify a deploy** in Grafana via the **Deployed build (commit @ branch)**
  panel / `live_overlay_build_info{commit,branch}` — it must show the intended
  commit (`unknown` = an image without a git stamp).

### Environment variables

#### Daemon (`live_overlay_daemon`)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABENTO_API_KEY` | yes | — | Databento live feed API key |
| `OVERLAY_SECRET_TOKEN` | yes | — | HMAC + `/metrics` basic-auth secret |
| `PORT` | yes | `8080` (production pin) | HTTP listen port |
| `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` | no | `0` (production: `1` since 2026-07-23) | Arms first-zero traffic alerts for a verified external `/smc_live` consumer. Keep `0` while none exists; see [Expected market traffic alert rollout](#expected-market-traffic-alert-rollout). |
| `LIVE_OVERLAY_INGEST_QUEUE_MAX` | no | 20000 | Max queued bars before drop (clamped 1000–200000) |
| `LIVE_OVERLAY_RESTART_CAUSE` | no | — | `cause` label on `live_overlay_daemon_start_time_seconds` |
| `LOG_LEVEL` | no | `INFO` | Python log level |
| `OVERLAY_FLOW_REFRESH_SECS` | no | — | Flow refresh interval |
| `OVERLAY_MAX_FEED_FAILURES` | no | — | Circuit breaker threshold |
| `OVERLAY_MAX_STALE_SECS` | no | — | Staleness threshold |
| `OVERLAY_MAX_SYMBOLS` | no | — | Symbol limit |
| `OVERLAY_NEWS_CACHE_TTL_SECS` | no | — | News cache TTL |
| `NEWS_SNAPSHOT_URL` | no | — | Optional HTTPS URL for live news snapshot |
| `NEWS_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `NEWS_SNAPSHOT_URL` |
| `NEWS_SNAPSHOT_PATH` | no | `artifacts/live_overlay/news_snapshot.json` | Local news snapshot path; point at the volume (`/data/...`) for write-through persistence |
| `SIGNALS_SNAPSHOT_PATH` | no | `artifacts/open_prep/latest/latest_realtime_signals.json` (production override: `/app/data/latest_realtime_signals.json`) | Local realtime-signals snapshot path (write-through cache) |
| `SIGNALS_SNAPSHOT_URL` | no | — | Optional legacy HTTPS fallback for realtime-signals snapshot (disabled in production lean mode) |
| `SIGNALS_SNAPSHOT_URL_TOKEN` | no | — | Optional bearer token for `SIGNALS_SNAPSHOT_URL` (disabled in production lean mode) |
| `SIGNALS_SERVICE_URL` | no | — | Internal Railway hostname/URL of `smc-signals-producer`; takes precedence |
| `SIGNALS_INTERNAL_TOKEN` | no | — | Bearer token used when calling `SIGNALS_SERVICE_URL` |
| `OVERLAY_SIGNALS_CACHE_TTL_SECS` | no | — | Signals snapshot cache TTL |
| `OVERLAY_SIGNALS_MAX_AGE_SECS` | no | — | Signals staleness threshold |
| `EXPERIMENT_SNAPSHOT_PATH` | no | `artifacts/live_overlay/plan_2_8_tf_family_rollup.json` | Local daily experiment rollup snapshot path |
| `EXPERIMENT_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for experiment rollup snapshot; explicit empty disables remote loading |
| `EXPERIMENT_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `EXPERIMENT_SNAPSHOT_URL` |
| `EVIDENCE_FRESHNESS_SNAPSHOT_PATH` | no | `artifacts/monitoring/evidence_freshness.json` | Local evidence-freshness snapshot path (ADR-0023 chain freshness gauges) |
| `EVIDENCE_FRESHNESS_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the `bot/live-evidence-freshness` snapshot; explicit empty disables remote loading |
| `EVIDENCE_FRESHNESS_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `EVIDENCE_FRESHNESS_SNAPSHOT_URL` |
| `SWEEP_TRAP_SHADOW_SNAPSHOT_PATH` | no | `artifacts/monitoring/sweep_trap_shadow.json` | Local WS4a sweep-trap shadow snapshot path (Brier-delta + verdict gauges) |
| `SWEEP_TRAP_SHADOW_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the `bot/live-sweep-trap-shadow` snapshot; explicit empty disables remote loading |
| `SWEEP_TRAP_SHADOW_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `SWEEP_TRAP_SHADOW_SNAPSHOT_URL` |
| `PROVIDER_USAGE_SNAPSHOT_PATH` | no | `artifacts/monitoring/provider_usage.json` | Local provider-usage snapshot path |
| `PROVIDER_USAGE_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the `bot/live-open-prep-snapshot` provider snapshot; explicit empty disables remote loading |
| `PROVIDER_USAGE_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `PROVIDER_USAGE_SNAPSHOT_URL` |
| `OVERLAY_SWEEP_TRAP_SHADOW_CACHE_TTL_SECS` | no | — | Sweep-trap shadow snapshot cache TTL (default 900) |
| `OVERLAY_SWEEP_TRAP_SHADOW_MAX_AGE_SECS` | no | — | Sweep-trap shadow snapshot staleness threshold (default 96h; powers `lo-sweep-trap-shadow-stale`) |
| `PINE_LIBRARY_VERSIONS_SNAPSHOT_PATH` | no | `artifacts/monitoring/pine_library_versions.json` | Local Repo↔TradingView Pine-library snapshot path (import-pin drift and generated-library data age) |
| `PINE_LIBRARY_VERSIONS_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the `bot/live-pine-library-versions` snapshot; explicit empty disables remote loading |
| `PINE_LIBRARY_VERSIONS_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `PINE_LIBRARY_VERSIONS_SNAPSHOT_URL` |
| `TRADINGVIEW_BINDINGS_SNAPSHOT_PATH` | no | `artifacts/monitoring/tradingview_consumer_bindings.json` | Local snapshot of saved-source SHA-256 checks and measured TradingView dropdown assignments |
| `TRADINGVIEW_BINDINGS_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the `bot/live-tradingview-bindings` snapshot; explicit empty disables remote loading |
| `TRADINGVIEW_BINDINGS_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for the binding snapshot URL |
| `EXPERIMENT_HISTORY_PATH` | no | — | Local daily experiment history JSONL path |
| `EXPERIMENT_HISTORY_URL` | no | canonical bot-branch URL | HTTPS URL for experiment history JSONL; explicit empty disables remote loading |
| `EXPERIMENT_HISTORY_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `EXPERIMENT_HISTORY_URL` |
| `OVERLAY_EXPERIMENT_CACHE_TTL_SECS` | no | — | Experiment rollup/history cache TTL |
| `OVERLAY_EXPERIMENT_MAX_AGE_SECS` | no | — | Experiment snapshot staleness threshold |
| `OVERLAY_EXPERIMENT_HISTORY_MAX_DAYS` | no | — | Max history days exposed as metrics |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_PATH` | no | `artifacts/live_overlay/credential_health.json` | Local daily credential-health report (TradingView storage-state age) |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` | no | canonical bot-branch URL | HTTPS URL for the credential-health report; explicit empty disables remote loading |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL_TOKEN` | no | repo monitor token for canonical URL | Optional explicit bearer token for `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` |
| `OVERLAY_TRADINGVIEW_CREDENTIAL_CACHE_TTL_SECS` | no | — | Credential-health report cache TTL (default 3600) |
| `OVERLAY_REFRESH_SECS` | no | — | Full compute refresh interval |
| `OVERLAY_ROLLING_BARS` | no | — | Rolling bar window |

#### Bridges (optional, co-deployed in same service)

| Variable | Bridge | Purpose |
|----------|--------|---------|
| `UPTIMEROBOT_API_KEY` | UptimeRobot | Free-tier API key |
| `UPTIMEROBOT_MONITOR_IDS` | UptimeRobot | Comma-separated monitor IDs to poll; production allowlist: `803309701,803341452,803343155,803343156,803362511,803555263,803555264` |
| `UPTIMEROBOT_POLL_TTL_SECS` | UptimeRobot | Cache TTL (default 30) |
| `UPTIMEROBOT_TIMEOUT_SECS` | UptimeRobot | HTTP timeout (default 5) |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | GitHub | PAT with `repo` + `actions:read` |
| `GITHUB_WORKFLOW_MONITOR_REPO` | GitHub | `owner/repo` to watch (validated; invalid value falls back to `skipp-dev/skipp-algo`) |
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

Deployments with a verified external `/smc_live` consumer must set:

```env
LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1
```

After rollout, verify:

```promql
live_overlay_expected_market_traffic{job="live_overlay"} == 1
```

If the deployment is local, dev, or warm-standby, leave the value at `0`.

**Production is armed as of 2026-07-23.** It ran with the flag at `0` while a
real consumer was already polling: `/metrics` reported 110 `/smc_live` requests
over 1707s of uptime, a measured 3.9 req/min across a 77s window (lifetime
average 3.8), with `auth_denied=0` and `errors=0`. Because
`lo-request-rate-absent-open` is multiplied by `expected_market_traffic`, that
whole period had **no** coverage for a client outage. The flag was set to `1` on
the Railway `live_overlay` service, the gauge verified at `1` after the
redeploy, and the consumer confirmed back at 4.0 req/min; the
`lo-expected-traffic-not-armed` reminder was then unpaused, so a silent revert
to `0` now pages within 15 minutes. Set it back to `0` only together with
re-pausing that rule, and record why.

**Who the consumer is.** Repo `skipp-live-lab`,
`sidecar_server/technical_poller.py` — the shared `POLLER` owns the cadence and
calls `sidecar_server/technical.py::fetch`, which was itself the direct caller
before that module existed (2026-07-23). It runs as the `lab-worker` service in
the `skipp-live-lab` Railway project. It builds
`<origin>/<token>/smc_live?symbol=X&tf=1m` from
`SKIPP_LAB_TECHNICAL_OVERLAY_ORIGIN` / `_TOKEN`, validates the reply against the
`smc-live-overlay/1` schema, and identifies itself as
`User-Agent: skipp-sidecar/<version>`. Verified 2026-07-23 in this daemon's
Railway HTTP logs: 12 of 12 `/smc_live` requests in the 14:14–14:17Z sample
carried `clientUa="skipp-sidecar/0.3.0"` from one source IP, all HTTP 200, on a
15.4s cadence. Re-identify any future consumer with
`railway logs --http --json` grouped by `clientUa`. (`smc_tv_bridge` and
`terminal_access_proxy` are *not* callers — the first is a library in this repo;
`realtime_signals.py` and `trade_context.py` mention `/smc_live` in comments
only.)

**2026-07-23 — the panel dependency is gone; a firing alert is now an
incident.** Until that date the traffic was panel-driven: the Chrome side panel
refreshed the 1m technical feed every 15s only *while it was connected*, so a
**closed** panel during US market hours drove the rate to zero and fired
`lo-request-rate-absent-open`. The alert measured "is the panel open", not "is
the infrastructure healthy". `skipp-live-lab` PR #43 (merged 2026-07-23 15:05Z)
moved the cadence server-side:

- A poller owns the interval in **both** servers that serve this overlay — the
  local Sidecar (ASGI lifespan task) and the hosted Layer-B read API
  (`cloud_worker/main.py`, thread `technical-feed`). Both start it
  unconditionally; there is no feature flag to forget.
- Its due-symbol set is never empty. With no panel connected it keeps polling
  the **last pinned symbol**, persisted via `SKIPP_LAB_TECHNICAL_STATE` so a
  restart does not silence the feed. Only if no symbol was ever pinned does it
  fall back to `SPY`.
- Cadence is 15s per tracked symbol; a symbol leaves the active set 90s after
  the last panel request, and at most 32 symbols are polled concurrently.

**Operational consequence.** From the deploy of that revision onward, treat a
firing `lo-request-rate-absent-open` as a **real infra signal** — the consuming
service is down, or this overlay is unreachable from it — and no longer as
"nobody had the panel open". The market-open floor is one request per 15s
(~40 per 10 minutes) against the rule's ~0.6 threshold, so a sustained zero
means the poller is not running. Confirm with `railway logs --http --json`
grouped by `clientUa`: absent `skipp-sidecar/` entries now indicate a dead
consumer, not an idle operator.

**2026-07-23 drill — the firing path is proven end-to-end (both directions).**
This closes the test #3954 left open: firing under real stopped traffic, and
self-resolution when it returns. Method: both `/smc_live` consumers stopped at
once during US market open — the hosted poller by pointing
`SKIPP_LAB_TECHNICAL_OVERLAY_ORIGIN` at an invalid value, the local Sidecar via
`launchctl disable` + kill. Stopping both is required, and is itself the
finding below.

- **Fire.** Consumers stopped 17:15:24Z. The daemon ran continuously through
  the whole drill (uptime climbed monotonically 47s → 3526s across 56 samples,
  no reset), so the `uptime_seconds > 600` guard cleared cleanly and the
  request counter stayed flat once traffic stopped. `pending` observed from
  17:31:10Z; the rule went to `firing` (Alertmanager `active`, `sev=warning`,
  `since 2026-07-23T17:40:40Z`) — exactly the 10-minute `for:` after pending
  began — and stayed active continuously for ~32 min through 18:13Z. (One
  isolated `inactive` read at 17:52:20Z was a polling artifact of the
  state-dump script: the `since 17:40:40Z` timestamp was identical before and
  after, so Alertmanager treated it as one uninterrupted episode.)
- **Resolve.** Consumers restored 18:13:20Z; `/smc_live` traffic resumed
  immediately (counter 6 → 9 → 13 → 18). The rule self-resolved at 18:16:27Z,
  ~3 min after restore, once `rate[10m]` climbed back above the threshold — no
  manual intervention.
- **Total time to fire is ~30 min, not 10.** The daemon must run >600s AND the
  10-minute rate window must empty AND the 10-minute `for:` must elapse, all
  continuously. A daemon restart resets the first two clocks; budget for it
  when running this drill.
- **Caveat — the rule sums all consumers.** The drill only fired because
  **both** consumers were stopped. `rate(live_overlay_smc_live_requests_total)`
  is the aggregate across every caller, so while any one consumer polls — e.g.
  one open Chrome panel on an operator's Mac (seen as the `aapl` hotspot during
  this drill) — the rule cannot fire even if the hosted service is dead. It
  detects "no one is calling", not "the service that matters is gone". The
  daemon already exports per-symbol counters
  (`live_overlay_hotspot_symbol_<sym>_requests_total`), so a sharper rule
  targeting the hosted poller's idle symbol is possible; tracked in the
  skipp-live-lab plan as A6, not armed here.

**Second consumer relationship — `/signals` (documented, not armed).**
`skipp-live-lab` PR #45 (merged 2026-07-23 15:15Z) added
`sidecar_server/signal_subscriber.py`, which polls the
`smc-signals-producer` `/signals` endpoint (`open_prep/realtime_signals.py` in
this repo) every 5s server-side, with the same `User-Agent: skipp-sidecar/*`.
This is recorded so a future reader can attribute that traffic, **not** as a
reason to arm anything. No `/signals` traffic watchdog exists today, and none
may be armed until two conditions hold:

1. **The subscriber runs permanently.** It is opt-in — it only starts when
   `SKIPP_LAB_SIGNALS_ORIGIN` is set (`signal_subscriber.configured()`), in
   both the local Sidecar and the hosted read API. While it is unset there is
   no `/signals` consumer traffic at all, so a watchdog would page on a
   configuration state, repeating exactly the mistake the panel-driven
   `lo-request-rate-absent-open` made.
2. **The producer exposes an inbound request counter.** It does not:
   `realtime_signals.py` serves `/signals` and `/signals.json` but exports no
   counter for inbound requests (`signals_producer_*_requests_total` covers
   outbound FMP calls only), so there is currently no metric such a rule could
   evaluate.

Existing producer alerts (`up{job="signals_producer"}` scrape health, RSS, and
the `lo-trading-signals-snapshot-*` family) are unaffected — they watch the
producer and its snapshot, not consumer traffic.

#### Alloy service

| Variable | Purpose |
|----------|---------|
| `OVERLAY_SECRET_TOKEN` | `/metrics` basic-auth password |
| `OVERLAY_SERVICE_URL` | Scrape target without scheme. Production: `liveoverlaydaemon.railway.internal:8080` |
| `GRAFANA_CLOUD_PROM_URL` | Grafana Cloud remote-write URL |
| `GRAFANA_CLOUD_USER` | Grafana Cloud stack user |
| `GRAFANA_CLOUD_API_KEY` | Grafana Cloud API key |

### Snapshot delivery & volume persistence

The daemon's snapshot loaders are **URL-first**: the canonical CI-produced
GitHub Contents URL is used by default and the local `*_SNAPSHOT_PATH` is the
fetch-failure fallback. An explicitly present-but-empty URL disables that
remote source for local/offline operation. Default `*_SNAPSHOT_PATH` values for the CI-produced snapshots (news,
experiment rollup/history, TradingView credential report) point at tracked seed
files under `artifacts/live_overlay/` so the daemon renders data out of the
box. Realtime signals remain host-only and still default to
`artifacts/open_prep/latest/latest_realtime_signals.json`. CI producers push
fresher snapshots to dedicated `bot/*` cache branches (exempt from the
`main-governance` ruleset, see ADR-0024). Canonical URLs reuse
`GITHUB_WORKFLOW_MONITOR_TOKEN` when no source-specific token is configured;
custom URLs never receive that generic token.

| Snapshot | Producer workflow | Bot branch | Bot-branch stable path | Default seed path |
|----------|-------------------|------------|------------------------|-------------------|
| News | `smc-live-news-refresh.yml` | `bot/live-news-snapshot` | `artifacts/smc_microstructure_exports/smc_live_news_snapshot.json` | `artifacts/live_overlay/news_snapshot.json` |
| Experiment rollup + history | `smc-measurement-benchmark-rolling.yml` | `bot/live-experiment-snapshot` | `artifacts/ci/measurement_benchmark_rolling/latest/plan_2_8_tf_family_rollup.json` and `.../latest/plan_2_8_history.jsonl` | `artifacts/live_overlay/plan_2_8_tf_family_rollup.json` / `plan_2_8_history.jsonl` |
| TradingView credential age | `credential-health-check.yml` | `bot/live-tv-credential-snapshot` | `artifacts/credential_health/latest/credential_health.json` | `artifacts/live_overlay/credential_health.json` |
| Realtime signals | _host helper (no CI producer)_ | `bot/live-signals-snapshot` | `artifacts/open_prep/latest/latest_realtime_signals.json` | `artifacts/open_prep/latest/latest_realtime_signals.json` |
| Sweep-trap shadow (WS4a) | `sweep-trap-shadow-daily.yml` | `bot/live-sweep-trap-shadow` | `artifacts/monitoring/latest/sweep_trap_shadow.json` | `artifacts/monitoring/sweep_trap_shadow.json` |
| Pine-library versions | `pine-library-version-monitor.yml` | `bot/live-pine-library-versions` | `artifacts/monitoring/latest/pine_library_versions.json` | `artifacts/monitoring/pine_library_versions.json` |
| TradingView saved sources + bindings | `tv-save-consumer-source.yml` | `bot/live-tradingview-bindings` | `artifacts/monitoring/latest/tradingview_consumer_bindings.json` | `artifacts/monitoring/tradingview_consumer_bindings.json` |

`smc-measurement-benchmark-rolling.yml` writes temporary per-timeframe
`structure_export_*.json` files only for inline notices and deletes them in the
same step so they do not leak into later jobs/artifacts.

The `*_URL` form is `https://api.github.com/repos/skipp-dev/skipp-algo/contents/<stable-path>?ref=<bot-branch>` with a fine-grained PAT (`Contents: Read`, repo `skipp-algo` only) in the matching `*_URL_TOKEN` when the workflow-monitor token is not used.

**Realtime signals on Railway are fetched live from `smc-signals-producer`.**
Production uses lean mode:

- `SIGNALS_SERVICE_URL=${{smc-signals-producer.RAILWAY_PRIVATE_DOMAIN}}:8080`
- `SIGNALS_INTERNAL_TOKEN=<shared bearer token>`
- `SIGNALS_SNAPSHOT_URL` and `SIGNALS_SNAPSHOT_URL_TOKEN` unset
- `SIGNALS_SNAPSHOT_PATH=/app/data/latest_realtime_signals.json`

In this mode the daemon reads live producer data first and persists successful
payloads to the local path as restart-safe cache.

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

**Write-through persistence (Railway volume).** On every successful producer/
URL fetch the daemon atomically writes the payload back to its
`*_SNAPSHOT_PATH` (`tempfile` + `os.replace`). Mount a Railway volume and point
the `*_PATH` vars at it so a cold start (or a momentary outage) reads the
last-good copy from the volume instead of the baked seed.

- Create the volume (for daemon service, mount path `/app/data`):

```bash
railway volume add -s live_overlay_daemon -e production -m /app/data
```

- Keep `SIGNALS_SNAPSHOT_PATH=/app/data/latest_realtime_signals.json` so
  realtime-signal writes persist across daemon restarts.
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
HTTP requests that completed without errors (`smc_live_success_total` over
`smc_live_requests_total` — request-level, NOT compute cycles; the dashboard
contract test pins that wording on the panel itself).

#### Historical bug: "0.00 %" with no traffic

Before `fix(live-overlay): always emit traffic counters and guarantee tzdata
availability` (`50995c03`), the traffic counters
`live_overlay_smc_live_requests_total` and
`live_overlay_smc_live_success_total` were only created when the `/smc_live`
endpoint was actually invoked. On a fresh daemon start with no traffic, these
series were absent from `/metrics`. Grafana's `rate()` over a missing series
returns no data, which the panel rendered as `0.00 %`. This looked like a
service outage even though the daemon was healthy and simply had no requests.

The same root cause made older **External Consumer Traffic** revisions hard to
interpret during no-traffic startup. `live_overlay_market_us_open` was still the
correct US-session gate, but missing request counters could make the traffic
half of the expression collapse to no data. The current dashboard keeps
`live_overlay_market_us_open` for US regular-session gating and relies on seeded
request counters plus explicit `or vector(0)` fallbacks for the no-traffic
state.

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

The panel's field config sets `noValue: "NO REQUESTS"`, so Grafana displays
**NO REQUESTS** instead of `0.00 %` when the query returns no data. As soon as
traffic appears, the series becomes non-zero and the panel shows the real
success rate again. (The contract test pins that the label is NOT the
ambiguous "NO TRAFFIC" — that wording collided with the market-traffic tile.)

#### External Consumer Traffic wiring

The **External Consumer Traffic** signal is intentionally US-regular-session
gated via `live_overlay_market_us_open` and rollout-gated via
`live_overlay_expected_market_traffic`. Europe/Asia session gauges are display
context only.

Therefore the panel expression reads:

```promql
(live_overlay_market_us_open{job=~"$job"} or vector(0))
+ ((live_overlay_market_us_open{job=~"$job"} or vector(0))
   * (live_overlay_expected_market_traffic{job=~"$job"} or vector(0)))
+ ((live_overlay_market_us_open{job=~"$job"} or vector(0))
   * (live_overlay_expected_market_traffic{job=~"$job"} or vector(0))
   * ((rate(live_overlay_smc_live_requests_total{job=~"$job"}[5m]) or vector(0)) > bool 0.001))
```

- `0` = US regular session is closed.
- `1` = market open, but no external consumer is expected (current healthy state).
- `2` = a consumer is expected, but request traffic is absent.
- `3` = an expected consumer is sending `/smc_live` traffic.

In der UI sind diese Stati bewusst lesbarer benannt:

- `0` = `MARKET CLOSED`
- `1` = `NO CONSUMER EXPECTED`
- `2` = `EXPECTED · NO REQUESTS`
- `3` = `CONSUMER TRAFFIC OK`

#### Expected market traffic alert rollout

`LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` controls whether the deployment expects
`/smc_live` request traffic during US market-open windows.

- `0` default: first-zero traffic alerting is disabled.
- `1`: alert when US market is open, the daemon has been up for more than
  10 minutes, and `/smc_live` request traffic remains near zero.

Deployments with a verified external `/smc_live` consumer must set:

```env
LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1
```

After rollout, verify:

```promql
live_overlay_expected_market_traffic{job="live_overlay"} == 1
```

The dashboard tile **External Consumer Watchdog** shows the same gauge:

- `0` = `NO CONSUMER EXPECTED`
- `1` = `CONSUMER EXPECTED`

Production also has a guard alert:

```promql
live_overlay_expected_market_traffic{job="live_overlay"} == bool 0
```

This reminder stays paused only while no supported consumer exists. Set
`LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1` only after a real client has been deployed
and end-to-end requests are verified.

#### Current production mode: external consumer verified and armed

**Superseded 2026-07-23.** This section previously read "no supported external
consumer" and told on-call to keep `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=0` with
`lo-expected-traffic-not-armed` paused. That is no longer the production state:
a real consumer was identified and verified, the flag is `1`, and the reminder
is unpaused (`isPaused: false`) — see
[Expected market traffic alert rollout](#expected-market-traffic-alert-rollout).

Pine still cannot call `/smc_live` directly; the consumer is the
`skipp-live-lab` Sidecar, not TradingView. The API's own health, latency,
error, and auth-denied alerts remain active regardless of this flag. Revert to
`0` only together with re-pausing `lo-expected-traffic-not-armed`, and record
why.

### Bar cache depth — "too shallow" alert (`lo-bar-cache-depth-low`)

The rolling features (squeeze, relative volume, ATS z-score) need ~20 bars of
history per symbol. `lo-bar-cache-depth-low` fires when that floor is breached
**for the symbols a consumer actually reads**.

**Read the right metric.** The alert evaluates
`live_overlay_requested_bars_per_symbol` — mean bar depth over the intersection
of the cache and the requested-symbol set — gated on
`live_overlay_requested_bar_symbols > 0`. Do **not** diagnose from the global
`live_overlay_bars_per_symbol` (`bar_count / bar_symbols`): the feed subscribes
to `ALL_SYMBOLS` and the cache caps at `OVERLAY_MAX_SYMBOLS` (default 2000), so
demand-aware retention (#3903) deliberately pins the cache at the cap with the
unrequested majority holding a single bar. That makes the global mean sit at
~1.0 during every open session **by design** — it is not a health signal, and
alerting on it flagged a healthy system every market-open minute until
2026-07-24.

**When it fires, it is real.** Past warmup, a requested symbol only stays
shallow if it is being evicted before it can accumulate history — i.e. live
demand exceeds the cap. Confirm with
`increase(live_overlay_bar_requested_symbols_evicted_total[30m]) > 0` (the
leading-indicator alert `lo-bar-cache-protected-evictions`). Remedy: raise
`OVERLAY_MAX_SYMBOLS` so demand fits, or narrow the requested universe. A shallow
cache in the first ~15 min after a restart or a freshly pinned symbol is
expected warmup, not a defect (the 900 s uptime gate + 15 m `for` absorb it).

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

- **Bridge Metrics Present** — counts how many required generic bridge
  contract series are absent across `uptimerobot`, `github_workflow`, and
  `railway_metrics`: `live_overlay_bridge_enabled`,
  `live_overlay_bridge_configured`, `live_overlay_bridge_scrape_success`,
  `live_overlay_bridge_error_info`, and
  `live_overlay_bridge_last_success_age_seconds`, and
  `live_overlay_bridge_last_scrape_duration_seconds`. This is the first signal
  that the exporter has stopped emitting part of the `live_overlay_bridge_*`
  family even though the daemon is still scraped.


### Why `degraded` has no alert rule of its own

`health_status_code == 4` (`degraded`) is a dashboard rollup, not an
independent failure mode, and **no alert rule references
`live_overlay_health_status_code`**. That is deliberate.

`compute_daemon_health_status` returns `degraded` when — past a 900 s warmup,
during an open US session — any of `feed_healthy`, `workers_healthy` or
`overlay_fresh` is false. Each of those three already has a rule that fires
*before* the 900 s gate opens:

| input | rule | fires after |
|---|---|---|
| `feed_healthy` | `lo-feed-down-market-open` | 5 min |
| `workers_healthy` | `lo-workers-degraded` | 3 min |
| `overlay_fresh` (no symbols) | `lo-no-symbols` | 5 min |
| `overlay_fresh` (stale) | `lo-overlay-stale` | 5 min |

A dedicated `degraded` rule could therefore never page first — it would be
pure duplicate noise. The cost of that choice is that the coverage is
*implicit*: delete one component rule and the gap opens with nothing red.
`tests/test_degraded_status_alert_coverage.py` pins the invariant, including
the "fires before 900 s" property, so such an edit fails CI.

### Generic bridge troubleshooting contract

| State | Expected metrics | Operational meaning |
|-------|------------------|---------------------|
| Disabled / not configured | `live_overlay_bridge_enabled{bridge="<name>"} == 0` | Bridge is intentionally not active; this should not alert as a scrape failure. |
| Enabled and healthy | `live_overlay_bridge_enabled == 1` and `live_overlay_bridge_scrape_success == 1` | Last scrape succeeded. |
| Enabled and failed | `live_overlay_bridge_enabled == 1` and `live_overlay_bridge_scrape_success == 0` | Bridge is configured but currently failing; investigate bridge logs and last error. |
| Stale success | `live_overlay_bridge_last_success_age_seconds` exceeds threshold | Bridge may be failing or unable to refresh successful data. |
| Slow scrape | `live_overlay_bridge_last_scrape_duration_seconds` rises unexpectedly | Bridge requests are completing but taking longer than normal. |
| Absent bridge metrics | no `live_overlay_bridge_*` series | Exporter or metrics path may be broken; check `Bridge Metrics Present`, `Core Metrics Present`, and collector targets. |

The alert **`lo-bridge-contract-missing`** fires when any required generic
bridge contract family disappears for any configured bridge for more than five
minutes. Treat this as a critical exporter/metrics-path issue (not a bridge
misconfiguration), because the generic contract must always be present when the
daemon is scraped.


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

### Evidence-freshness monitoring — go-live runbook

Bringing the ADR-0023 evidence-freshness monitoring (per-workflow alerts,
evidence-chain freshness gauges, the §2/§5 per-family sample panel) live in
Grafana. The code + config ship in the repo, but deploy to Grafana Cloud is
**manual** (there is no CI upsert), so these steps are required once.

**Prerequisite:** PRs #3215 (plane/gate governance) and #3216 (per-family
sample panel) are merged to `main`; run from a fresh top-level checkout:

```bash
cd ~/Documents/skipp-algo && git checkout main && git pull --ff-only
```

1. **Push the alert rules** (validate first, then apply — needs the Grafana
   API key in the keychain, `skipp.grafana.api`):

   ```bash
   python scripts/grafana_alert_rules_upsert.py --dry-run   # validate, no network
   python scripts/grafana_alert_rules_upsert.py             # apply
   ```

   Adds the `evidence-and-workflow-freshness` group (ledger-stale,
   audit-branch-stale, snapshot-stale, wsh-stale, plus the three per-workflow
   alerts). Do **not** pass `--prune` unless you intend to delete live groups
   absent from the repo.

2. **Push the dashboard:**

   ```bash
   python scripts/grafana_dashboard_upsert.py
   ```

   Adds the "Evidence Freshness (§5 Track)" row incl. the "Samples toward
   §2/§5 (need 40 / family)" panel.

3. **Wire the data feed** (otherwise the panels are empty / go stale):

   * Run the producer once so it publishes the snapshot to
     `bot/live-evidence-freshness`:

     ```bash
     gh workflow run evidence-freshness-snapshot.yml
     ```

   * Set two env vars on the **`live_overlay_daemon`** Railway service, then
     redeploy:

     ```
     EVIDENCE_FRESHNESS_SNAPSHOT_URL=https://api.github.com/repos/<OWNER>/skipp-algo/contents/artifacts/monitoring/latest/evidence_freshness.json?ref=bot/live-evidence-freshness
     EVIDENCE_FRESHNESS_SNAPSHOT_URL_TOKEN=<fine-grained PAT, Contents:Read, skipp-algo only>
     ```

     For `<OWNER>` and the token, mirror the already-working snapshot vars
     (`SIGNALS_SNAPSHOT_URL` / `EXPERIMENT_SNAPSHOT_URL`) — same owner, reuse
     the same PAT.

4. **Verify:**

   ```bash
   curl -s https://<daemon-host>/metrics | grep live_overlay_evidence_samples
   ```

   Expect `live_overlay_evidence_samples_usable{family="BOS",classification="operational"} …`
   and `live_overlay_evidence_samples_target 40`. In Grafana the new row shows
   BOS with coloured progress toward 40, SWEEP/controls greyed, and the alerts
   listed under the `SMC Live Overlay` folder.

Without step 3's env vars the daemon serves the checked-in seed snapshot; its
`generated_at` ages and the "Evidence snapshot stale" alert fires after 24h —
at which point that alert is a true signal that step 3 is missing.

### Sweep-trap shadow monitoring — go-live runbook

Bringing the WS4a sweep-trap shadow evaluation (Brier-delta + tercile lift +
sample accrual toward the promotion decision) live in Grafana. As with
evidence-freshness, the code + config ship in the repo but the Grafana deploy is
**manual**, and the data feed only fills once the detector is armed on the
corpus producer.

The detector is **observe-only** — arming `ENABLE_SWEEP_TRAP` logs the
`sweep_trap_*` features and lets the shadow eval score them, but grants the
detector **no score-budget weight**. Promotion to a live signal is the separate
WS4b decision this monitoring exists to inform.

**Prerequisite:** #3411 (evidence engine) and this PR (Grafana surface) are
merged to `main`; run from a fresh top-level checkout:

```bash
cd ~/Documents/skipp-algo && git checkout main && git pull --ff-only
```

1. **Arm the detector on the corpus producer.** Set the repo variable so the
   rolling benchmark logs the observe-only `sweep_trap_quality_score` the eval
   later reads from the corpus (`smc-measurement-benchmark-rolling.yml` passes it
   in as `ENABLE_SWEEP_TRAP: ${{ vars.ENABLE_SWEEP_TRAP }}`; the daily eval itself
   needs no flag — it just reads the pre-logged scores):

   ```bash
   gh variable set ENABLE_SWEEP_TRAP --body 1
   ```

   Until this is set the daily eval resolves to `no_data` (green) and no
   evidence accrues — the sample-count tile stays at 0.

2. **Push the alert rule** (validate first, then apply — needs `skipp.grafana.api`):

   ```bash
   python scripts/grafana_alert_rules_upsert.py --dry-run   # validate, no network
   python scripts/grafana_alert_rules_upsert.py             # apply
   ```

   Adds `lo-sweep-trap-shadow-stale` to the `evidence-and-workflow-freshness`
   group. Do **not** pass `--prune` unless you intend to delete live groups.

3. **Push the dashboard:**

   ```bash
   python scripts/update_overlay_dashboard.py services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json
   python scripts/grafana_dashboard_upsert.py
   ```

   Adds the "Sweep-Trap Promotion Evidence" row (verdict, Brier delta, lift, samples
   toward promotion, snapshot age) to the Signals & Experiments board.

4. **Wire the data feed** (otherwise the tiles serve the no-data seed):

   * Run the eval once so it publishes the snapshot to
     `bot/live-sweep-trap-shadow` (needs a day's rolling-bench corpus with the
     score already logged — i.e. after step 1 has been live for at least one
     `smc-measurement-benchmark-rolling` run):

     ```bash
     gh workflow run sweep-trap-shadow-daily.yml
     ```

   * Set two env vars on the **`live_overlay_daemon`** Railway service, then
     redeploy (mirror the already-working `EVIDENCE_FRESHNESS_SNAPSHOT_URL`):

     ```
     SWEEP_TRAP_SHADOW_SNAPSHOT_URL=https://api.github.com/repos/<OWNER>/skipp-algo/contents/artifacts/monitoring/latest/sweep_trap_shadow.json?ref=bot/live-sweep-trap-shadow
     SWEEP_TRAP_SHADOW_SNAPSHOT_URL_TOKEN=<fine-grained PAT, Contents:Read, skipp-algo only>
     ```

5. **Verify:**

   ```bash
   curl -s https://<daemon-host>/metrics | grep live_overlay_sweep_trap_shadow
   ```

   Expect `live_overlay_sweep_trap_shadow_sample_count` climbing toward 40 and a
   `live_overlay_sweep_trap_shadow_verdict_code{verdict="…"}` series. Before
   step 1 the count stays 0 and the verdict is `INCONCLUSIVE`.

The seed snapshot carries `generated_at=0`, so the snapshot-age gauge reports
"unknown" and `lo-sweep-trap-shadow-stale` stays quiet until the first real
publish — after which a stalled feed (step 4 missing, or the cron stopped) ages
past 96h and the alert becomes a true signal. `workflow-freshness-monitor`
independently files an issue if the daily cron stops running at all.

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

### Reading the live firing state (read-only)

The reader is the missing half of the upsert flow — "is anything firing?"
without opening the UI (same auth chain, GET-only):

```bash
python -m scripts.grafana_alert_state                   # firing/pending/unhealthy + active instances
python -m scripts.grafana_alert_state --all             # include inactive rules
python -m scripts.grafana_alert_state --rule vix        # filter by rule-name substring
python -m scripts.grafana_alert_state --json            # machine-readable
python -m scripts.grafana_alert_state --fail-on-firing  # exit 1 if anything fires (scripts/CI)
```

Rules with `health=error` (unevaluable) are always surfaced in the default
view — an unevaluable rule is operationally worse than a firing one. Run in
module form (`-m`) from the repo root; the script reuses the upsert module's
keychain/HTTP helpers and adds no credentials of its own.

### macOS APFS filesystem-alert deduplication

Grafana's stock macOS integration evaluates every writable APFS system volume.
Because `Data`, `VM`, `Update`, and `Preboot` share one APFS container, a single
low-space condition otherwise produces four equivalent alerts. Apply the
idempotent per-rule patch after installing or upgrading that integration:

```bash
python -m scripts.grafana_macos_node_filesystem_alert_patch --dry-run
python -m scripts.grafana_macos_node_filesystem_alert_patch
```

The patch excludes only `/System/Volumes/VM`, `/System/Volumes/Update`, and
`/System/Volumes/Preboot`. The canonical writable Data-volume signal and any
independent external filesystem remain monitored. Grafana marks stock
integration rules with `converted_prometheus` provenance, which rejects
per-rule updates. The script therefore rewrites the six-rule group atomically,
changes only the warning and critical expressions, and verifies that the four
non-target rules remain unchanged.

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
max(live_overlay_health_status_code{job=~"$job"}) or vector(0)
```

The `max(...)` wrapper collapses the scraped, labelled series to a single
empty-label series so the `or vector(0)` fallback deduplicates instead of
adding a phantom second tile. Without it, the stat panel renders two values
(the real code plus a spurious `0`/UNKNOWN) because `vector(0)` carries an
empty label set that never matches the scraped `{job,instance}` series. The
`0`/UNKNOWN value therefore only appears when the metric is genuinely absent
(scrape down) — `compute_daemon_health_status` itself never emits `0`.

Value mappings:

| Value | Label | Meaning |
|-------|-------|---------|
| 3 | HEALTHY | Feed, workers, overlay all healthy |
| 2 | IDLE | Market closed before the first bar |
| 1 | STARTING | Daemon still waiting on feed, workers or overlay freshness |
| 0 | UNKNOWN | Status metric missing or scrape not available (fallback only — never emitted by the daemon) |

#### Deploy/restart annotations

```promql
changes(live_overlay_process_start_time_seconds{job=~"$job"}[1m]) > 0
```

Restart-cause breakdown (per-cause counts over a window):

```promql
sum by (cause) (
  changes(live_overlay_daemon_start_time_seconds{job=~"$job"}[24h])
)
```

> The `live_overlay_daemon_restart_cause_*_total` and
> `live_overlay_daemon_restarts_total` counters no longer exist. They were reset
> to `1` on every process start and stayed constant, so Prometheus saw `1,1,…`,
> detected no reset, and `increase()` was always `0` — measured 2026-07-23, the
> series read `1` against 51 real restarts in the same 24h.
> `live_overlay_daemon_start_time_seconds{cause}` carries the start epoch as its
> value, so `changes()` counts real restarts per cause.

**F-1 drill evidence (2026-07-23, one-night practice test, PR #3875/#3884/#3892):**
the `lo-restart-data-loss-closed` firing path was exercised against production —
dead-zone restart dispatched 00:52:51Z (deploy run 29970302656, success); rule
`Overlay data lost after restart (market closed)` observed `state=firing
health=ok` at 03:17:22Z; self-resolved to `state=inactive health=ok` at
08:17:10Z after the 6h-uptime window. The quiet path was live-confirmed
2026-07-22 (09:13Z restart, premarket repopulated, rule stayed silent). The
temporary drill workflow and its contract test were removed in #3892 — this
line is the surviving record.

---

## UptimeRobot Bridge

Implementation: `services/live_overlay_daemon/uptimerobot_bridge.py`

### What it does (UptimeRobot bridge)

- Polls the UptimeRobot V2 `getMonitors` endpoint.
- Caches results in-process for `UPTIMEROBOT_POLL_TTL_SECS`.
- Emits Prometheus gauges for each configured monitor.

### Exported metrics (UptimeRobot bridge)

Bridge status is exported through the generic
`live_overlay_bridge_*{bridge="uptimerobot"}` contract. The metrics below are
UptimeRobot-specific detail series.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `live_overlay_uptimerobot_monitors_total` | gauge | — | Count returned by the UptimeRobot API |
| `live_overlay_uptimerobot_monitors_expected` | gauge | — | Expected count derived from `UPTIMEROBOT_MONITOR_IDS` |
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
   UPTIMEROBOT_MONITOR_IDS=803309701,803341452,803343155,803343156,803362511,803555263,803555264
   ```

   The final two IDs monitor the public Terminal AI and MLflow `/health`
   endpoints with HEAD every five minutes.

4. Restart the daemon.

### Production guards

Production expects the UptimeRobot API result to match the configured bridge
allowlist. Grafana derives the expected count from `UPTIMEROBOT_MONITOR_IDS`
instead of duplicating a hard-coded number. The alerts gate on the generic
bridge contract while keeping the UptimeRobot-specific monitor count gauges as
the domain signal:

```promql
(live_overlay_uptimerobot_monitors_total{job="live_overlay"}
 != bool on(job)
 live_overlay_uptimerobot_monitors_expected{job="live_overlay"})
and on(job)
(live_overlay_bridge_enabled{job="live_overlay",bridge="uptimerobot"} == 1)
```

```promql
(live_overlay_uptimerobot_monitors_down_total{job="live_overlay"} > bool 0)
and on(job)
(live_overlay_bridge_enabled{job="live_overlay",bridge="uptimerobot"} == 1)
```

If the count alert fires, compare `UPTIMEROBOT_MONITOR_IDS` in Railway with the
UptimeRobot dashboard. If the down alert fires, correlate the failed public
probe with Railway `/health`, `/ready`, deploy history, and the
**External Integrations** dashboard row.

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

Bridge status is exported through the generic
`live_overlay_bridge_*{bridge="github_workflow"}` contract. The metrics below
are GitHub-workflow-specific detail series.

| Metric | Type | Description |
|--------|------|-------------|
| `live_overlay_github_workflow_runs_*_total` | gauge | Snapshot counts grouped by workflow-run state |
| `live_overlay_github_workflow_latest_run_*_seconds` | gauge | Aggregate latest run age and duration |
| `live_overlay_github_workflow_phase_code{workflow_id,workflow,event}` | gauge | Per-workflow timeline state |
| `live_overlay_github_workflow_latest_success{workflow_id,workflow,event}` | gauge | Per-workflow latest success state |
| `live_overlay_github_workflow_latest_age_seconds{workflow_id,workflow,event}` | gauge | Per-workflow latest run age |
| `live_overlay_github_workflow_latest_duration_seconds{workflow_id,workflow,event}` | gauge | Per-workflow latest run duration |

---

## Platform Interaction Matrix

| Source | Destination | Protocol | Auth | Direction | Data |
|--------|-------------|----------|------|-----------|------|
| Databento | Daemon `feed.py` | Databento db.Live (TCP/TLS) | `DATABENTO_API_KEY` | Inbound | ohlcv-1m bars |
| External API client (none deployed) | Daemon `main.py` | HTTPS | URL path token (`OVERLAY_SECRET_TOKEN`) | Inbound | Overlay JSON |
| Daemon `/metrics` | Grafana Alloy | HTTP | Basic auth (`OVERLAY_SECRET_TOKEN`) | Outbound | Prometheus metrics |
| Alloy | Grafana Cloud Prometheus | HTTPS/TLS | `GRAFANA_CLOUD_API_KEY` | Outbound | Remote-write samples |
| Grafana Cloud | Operators | HTTPS | Grafana session/API key | Outbound | Dashboards, alerts |
| Daemon | UptimeRobot API | HTTPS | `UPTIMEROBOT_API_KEY` | Outbound | Monitor status poll |
| Daemon | GitHub API | HTTPS | `GITHUB_WORKFLOW_MONITOR_TOKEN` | Outbound | Workflow run status |
| Railway healthcheck | Daemon `/health` | HTTP | none | Inbound | 200 OK liveness |
| UptimeRobot probe | Daemon `/health` | HTTP/HTTPS | none | Inbound | HEAD/GET probe |

### `/smc_live` synthetic canary plan

Do **not** place the production `OVERLAY_SECRET_TOKEN` in UptimeRobot for a
`/{token}/smc_live` synthetic probe. The token is not independently rotatable for
that third-party monitor, so a UptimeRobot leak would force the same secret used
by `/smc_live` API clients and legacy `/metrics` auth.

Current production coverage stays:

- UptimeRobot probes unauthenticated liveness/readiness-style endpoints.
- Grafana alerts detect first-zero `/smc_live` traffic during US market open
  through `live_overlay_expected_market_traffic` and request-rate metrics.
- Auth-denied spikes are monitored via `live_overlay_smc_live_auth_denied`.

Future safe options, in order of preference:

1. Add a non-secret contract endpoint such as `/ready/smc_live_contract` that
   validates cache/compute readiness without returning customer-token-protected
   overlay payloads.
2. Run an internal synthetic from `metrics-collector` over Railway private
   networking with a token that is not shared with external API clients.
3. Keep the current Grafana first-zero request-rate detector as the end-to-end
   traffic guard if neither of the above is approved.

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
| `OVERLAY_SECRET_TOKEN` | 1. Generate new random secret.<br>2. Update in Railway for both daemon and Alloy services.<br>3. Redeploy both services.<br>4. Update any authenticated server-side `/smc_live` clients. |
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

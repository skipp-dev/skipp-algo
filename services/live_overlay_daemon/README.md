# SMC Live Overlay Daemon

<!-- markdownlint-disable MD060 -->

FastAPI micro-service that subscribes to [Databento](https://databento.com) `EQUS.MINI` live feed
(schema `ohlcv-1m`, `ALL_SYMBOLS`) and exposes a per-symbol overlay JSON endpoint for
TradingView Pine scripts.

Deployed on [Railway.app](https://railway.com) — see [Deployment](#deployment).

---

## Architecture

```text
Databento Live (db.Live())
        │ ohlcv-1m bars (background thread)
        ▼
   feed.py   ──── cache.py  (thread-safe bar + overlay store)
                      │
               compute.py  (overlay field computation, 30 min / 5 min cycles)
                      │
              main.py / FastAPI
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
  GET /health                GET /{token}/smc_live
  (liveness, no auth)        (token in path, HMAC compare)
              │                           │
            GET /metrics                GET /{token}/metrics (legacy)
            (Basic auth preferred)      (backward-compatible)
        │                           │
  Railway healthcheck        Pine request.raw() consumer
  UptimeRobot HEAD probe     TradingView chart
```

---

## Endpoints

### `GET /health` / `HEAD /health`

No authentication required. **Liveness only** endpoint used by Railway healthcheck and UptimeRobot.

#### Response example (200 OK)

```json
{
  "status": "alive",
  "service": "smc-live-overlay",
  "uptime_secs": 406,
  "ts": "2026-06-20T18:17:30+00:00"
}
```

---

### `GET /ready` / `HEAD /ready`

No authentication required. **Readiness/diagnostics** endpoint with worker and dependency state.

#### Response (200 OK)

```json
{
  "status": "ok",
  "feed_healthy": true,
  "workers_healthy": true,
  "worker_liveness": {"live_feed": true, "overlay_refresh": true, "flow_refresh": true},
  "feed_metrics": {"reconnect_attempts": 0, "bento_errors": 0, "unexpected_errors": 0, "circuit_breakers": 0, "partial_restarts": 0},
  "overlay_fresh": true,
  "last_bar_age_secs": 12.3,
  "uptime_secs": 406,
  "bar_symbols": 12,
  "bar_count": 720,
  "overlay_symbols": 12,
  "overlay_age_secs": 45.2,
  "ts": "2026-06-16T13:17:30+00:00"
}
```

> `status` is market-aware and can be `"ok"`, `"starting"`, or
> `"idle_market_closed"` (outside US regular session while otherwise healthy).
> `feed_healthy` becomes `false` after `stop()` or if bars are stale beyond `max_stale_secs`.
> `workers_healthy` is `false` if any of the three background threads (feed, refresh, flow) is dead.
> `overlay_fresh` is `false` when overlay_symbols == 0 or overlay_age > max_stale_secs.
> `HEAD` requests return only headers (body stripped by Starlette automatically).

---

### `GET /metrics` (preferred)

Prometheus text-format endpoint protected via **Basic Auth**.

- Username: arbitrary (recommended: `metrics`)
- Password: `OVERLAY_SECRET_TOKEN`

Returns `401` + `WWW-Authenticate: Basic` on missing/invalid credentials.

```bash
curl -u "metrics:${OVERLAY_SECRET_TOKEN}" "http://localhost:8000/metrics"
```

---

### `GET /{token}/metrics`

Legacy token-in-path Prometheus endpoint (backward-compatible). Same token as `/smc_live`.
New deployments should prefer `GET /metrics` with Basic auth.

Returns all in-process counters (request totals, auth denials, compute errors,
feed errors) plus gauges (uptime, overlay age, bar count, worker liveness).

If `UPTIMEROBOT_API_KEY` is configured, this endpoint also exports
UptimeRobot bridge gauges (monitor totals/up/down, bridge status, snapshot age,
and per-monitor up/status/latency gauges) so Grafana can show both internal
daemon health and external synthetic check status.

If `GITHUB_WORKFLOW_MONITOR_TOKEN` is configured, this endpoint also exports
GitHub Actions workflow bridge gauges (run state totals, latest run age/duration,
bridge status/snapshot age, and per-workflow phase/success gauges).

Used by Prometheus scrape jobs. Returns `text/plain; version=0.0.4`.

```bash
curl "http://localhost:8000/mysecret/metrics"
```

---

### `GET /{token}/smc_live?symbol=NVDA&tf=5m`

Token must match `OVERLAY_SECRET_TOKEN` env var (constant-time `hmac.compare_digest` comparison).
Returns **404** on wrong token (does not leak route existence).

#### Query params

| Param    | Required | Example | Notes |
|----------|----------|---------|-------|
| `symbol` | ✅ | `NVDA` | Case-insensitive, max 10 chars |
| `tf`     | ❌ | `5m` | One of `5m`, `10m`, `15m`, `30m`, `1H`, `4H`. Returns 400 for unknown values. |

#### Response fields

| Field | Type | Range / Values | Notes |
|-------|------|----------------|-------|
| `schema` | str | `"smc-live-overlay/1"` | Version tag |
| `symbol` | str | e.g. `"NVDA"` | Uppercased |
| `tf` | str | e.g. `"5m"` | Echo of `tf` query param |
| `asof_ts` | int | Unix-Epoch seconds | Time of last compute cycle |
| `stale` | bool | | True when overlay_age > max_stale_secs |
| `news_strength` | float \| null | [0.0, 1.0] | Composite news sentiment |
| `news_bias` | str \| null | `"BULLISH"` \| `"BEARISH"` \| `"NEUTRAL"` | Uppercase |
| `flow_rel_vol` | float \| null | ≥ 0 | volume(N bars) / avg_volume(window) |
| `flow_delta_proxy_pct` | float \| null | | (close−open)/open × 100 |
| `squeeze_on` | int \| null | `0` \| `1` | 1 if Bollinger width < ATR threshold |
| `ats_state` | str \| null | `"accumulation"` \| `"distribution"` \| `"neutral"` | |
| `ats_zscore` | float \| null | | Z-score of last-bar volume vs rolling mean |
| `vix_level` | float \| null | | Latest VIX level (from VIX symbol bars) |
| `tone` | str \| null | `"BULLISH"` \| `"BEARISH"` \| `"NEUTRAL"` | Market-wide, uppercase |
| `global_heat` | float \| null | [-1.0, 1.0] | Directional news heat (positive = bullish) |
| `event_window_state` | str \| null | `"pre-event"` \| `"in-event"` \| `"post-event"` \| `"normal"` | |
| `event_risk_level` | str \| null | `"high"` \| `"medium"` \| `"low"` | |
| `next_event_name` | str \| null | | |
| `next_event_time` | ISO-8601 \| null | | UTC |
| `market_event_blocked` | bool | | |
| `symbol_event_blocked` | bool | | |
| `event_provider_status` | str | `"ok"` \| `"stale"` \| `"unavailable"` | |

#### Stale response

(symbol not yet in cache — pre-market or feed not connected)

All numeric fields are `null`, all bool fields are `false`, `stale: true`.

---

## Configuration (env vars)

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATABENTO_API_KEY` | ✅ | — | Set in Railway env vars |
| `OVERLAY_SECRET_TOKEN` | ✅ | — | Embedded in Pine URL path |
| `PORT` | ❌ | `8000` | Injected by Railway automatically |
| `LOG_LEVEL` | ❌ | `info` | Uvicorn-compatible level (`critical`,`error`,`warning`,`info`,`debug`,`trace`) |
| `OVERLAY_REFRESH_SECS` | ❌ | `1800` | Full overlay compute cycle interval (seconds) |
| `OVERLAY_FLOW_REFRESH_SECS` | ❌ | `300` | Flow-patch cycle interval (seconds) |
| `OVERLAY_ROLLING_BARS` | ❌ | `60` | Rolling window size for flow/ATS computations (range 1–500) |
| `OVERLAY_MAX_STALE_SECS` | ❌ | `3600` | Overlay age before `stale: true` (range 60–7200) |
| `OVERLAY_MAX_SYMBOLS` | ❌ | `2000` | Hard cap on tracked symbols in bar cache (range 100–50 000) |
| `OVERLAY_NEWS_CACHE_TTL_SECS` | ❌ | `600` | News snapshot cache TTL in seconds (range 60–3600) |
| `NEWS_SNAPSHOT_URL` | ❌ | *(unset)* | Optional HTTPS URL for news snapshot; takes precedence over local path |
| `NEWS_SNAPSHOT_URL_TOKEN` | ❌ | *(unset)* | Optional bearer token for `NEWS_SNAPSHOT_URL` |
| `SIGNALS_SNAPSHOT_PATH` | ❌ | *(repo root)*`/artifacts/open_prep/latest/latest_realtime_signals.json` | Local realtime-signals snapshot path |
| `SIGNALS_SNAPSHOT_URL` | ❌ | *(unset)* | Optional HTTPS URL for realtime-signals snapshot |
| `SIGNALS_SNAPSHOT_URL_TOKEN` | ❌ | *(unset)* | Optional bearer token for `SIGNALS_SNAPSHOT_URL` |
| `SIGNALS_SERVICE_URL` | ❌ | *(unset)* | Internal Railway hostname/URL of `smc-signals-producer`; takes precedence over all other signal sources |
| `SIGNALS_INTERNAL_TOKEN` | ❌ | *(unset)* | Bearer token used when calling `SIGNALS_SERVICE_URL` |
| `OVERLAY_SIGNALS_CACHE_TTL_SECS` | ❌ | `120` | Signals snapshot cache TTL in seconds (range 30–1800) |
| `OVERLAY_SIGNALS_MAX_AGE_SECS` | ❌ | `480` | Age threshold after which signals snapshot is stale (range 60–7200) |
| `EXPERIMENT_SNAPSHOT_PATH` | ❌ | *(repo root)*`/artifacts/live_overlay/plan_2_8_tf_family_rollup.json` | Local daily experiment rollup snapshot |
| `EXPERIMENT_SNAPSHOT_URL` | ❌ | *(unset)* | Optional HTTPS URL for daily experiment rollup snapshot |
| `EXPERIMENT_SNAPSHOT_URL_TOKEN` | ❌ | *(unset)* | Optional bearer token for `EXPERIMENT_SNAPSHOT_URL` |
| `EXPERIMENT_HISTORY_PATH` | ❌ | *(repo root)*`/artifacts/ci/measurement_benchmark_rolling/latest/plan_2_8_history.jsonl` | Local per-day experiment history JSONL |
| `EXPERIMENT_HISTORY_URL` | ❌ | *(unset)* | Optional HTTPS URL for per-day experiment history JSONL |
| `EXPERIMENT_HISTORY_URL_TOKEN` | ❌ | *(unset)* | Optional bearer token for `EXPERIMENT_HISTORY_URL` |
| `OVERLAY_EXPERIMENT_CACHE_TTL_SECS` | ❌ | `900` | Experiment snapshot/history cache TTL in seconds (range 60–7200) |
| `OVERLAY_EXPERIMENT_MAX_AGE_SECS` | ❌ | `129600` | Age threshold after which experiment snapshot is stale (range 3600–1209600) |
| `OVERLAY_EXPERIMENT_HISTORY_MAX_DAYS` | ❌ | `30` | Max number of history days surfaced as metrics (range 1–366) |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_PATH` | ❌ | *(repo root)*`/artifacts/live_overlay/credential_health.json` | Local daily credential-health report (TradingView storage-state age probe) |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` | ❌ | *(unset)* | Optional HTTPS URL for the credential-health report; takes precedence over local path |
| `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL_TOKEN` | ❌ | *(unset)* | Optional bearer token for `TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL` |
| `OVERLAY_TRADINGVIEW_CREDENTIAL_CACHE_TTL_SECS` | ❌ | `3600` | Credential-health report cache TTL in seconds (range 60–86400) |
| `OVERLAY_MAX_FEED_FAILURES` | ❌ | `50` | Circuit-breaker threshold for consecutive feed failures (range 1–1000) |
| `UPTIMEROBOT_API_KEY` | ❌ | *(unset)* | Enables optional UptimeRobot API bridge metrics in `/metrics` |
| `UPTIMEROBOT_MONITOR_IDS` | ❌ | *(all monitors)* | Comma-separated monitor IDs to include in bridge poll |
| `UPTIMEROBOT_TIMEOUT_SECS` | ❌ | `5` | UptimeRobot API timeout in seconds (range 1–30) |
| `UPTIMEROBOT_POLL_TTL_SECS` | ❌ | `30` | In-process cache TTL for UptimeRobot snapshot (range 5–300) |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | ❌ | *(unset)* | Enables optional GitHub Actions workflow bridge metrics in `/metrics` |
| `GITHUB_WORKFLOW_MONITOR_REPO` | ❌ | `skippALGO/skipp-algo` | Target repository in `owner/repo` format (validated; invalid values fall back to default) |
| `GITHUB_WORKFLOW_MONITOR_IDS` | ❌ | *(all workflows)* | Comma-separated workflow IDs to include |
| `GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS` | ❌ | `5` | GitHub API timeout in seconds (range 1–30) |
| `GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS` | ❌ | `30` | In-process cache TTL for workflow snapshot (range 5–300) |
| `GITHUB_WORKFLOW_MONITOR_PER_PAGE` | ❌ | `30` | Number of workflow runs fetched per API poll (range 1–100) |
| `LIVE_OVERLAY_RESTART_CAUSE` | ❌ | `unknown` | Restart cause label (`deploy`, `crash`, `manual`, …) for restart observability |
| `LIVE_OVERLAY_INGEST_QUEUE_MAX` | ❌ | `20000` | Max pending bars in feed ingest queue before drops (range 1000–200000) |
| `NEWS_SNAPSHOT_PATH` | ❌ | *(repo root)*`/artifacts/live_overlay/news_snapshot.json` | Absolute path to news JSON file (resolved relative to repo root) |

### Config validation

- **`OVERLAY_ROLLING_BARS`** is clamped to `[1, 500]`. Out-of-range values are
  clamped with a `WARNING` log line.
- **`OVERLAY_MAX_STALE_SECS`** is clamped to `[60, 7200]` (1 min – 2 h). Same
  clamping + warning behaviour.
- **`OVERLAY_REFRESH_SECS`** is clamped to `[10, 86400]` (10 s – 24 h).
- **`OVERLAY_FLOW_REFRESH_SECS`** is clamped to `[5, 3600]` (5 s – 1 h).
- **`OVERLAY_NEWS_CACHE_TTL_SECS`** is clamped to `[60, 3600]` (1 min – 1 h).
- **`OVERLAY_SIGNALS_CACHE_TTL_SECS`** is clamped to `[30, 1800]`.
- **`OVERLAY_SIGNALS_MAX_AGE_SECS`** is clamped to `[60, 7200]`.
- **`OVERLAY_EXPERIMENT_CACHE_TTL_SECS`** is clamped to `[60, 7200]`.
- **`OVERLAY_EXPERIMENT_MAX_AGE_SECS`** is clamped to `[3600, 1209600]`.
- **`OVERLAY_EXPERIMENT_HISTORY_MAX_DAYS`** is clamped to `[1, 366]`.
- **`OVERLAY_MAX_SYMBOLS`** is clamped to `[100, 50000]`.
- **`OVERLAY_MAX_FEED_FAILURES`** is clamped to `[1, 1000]`.
- Non-integer values for any `_optional_int` variable are logged at `WARNING`
  and fall back to the documented default.

### Snapshot delivery & persistence

Each snapshot loader (news, signals, experiment rollup/history, TradingView
credential report) is
**URL-first**: when the matching `*_SNAPSHOT_URL` is set it fetches the freshest
payload over HTTPS and falls back to the local `*_SNAPSHOT_PATH` otherwise.
The default `*_SNAPSHOT_PATH` values for the CI-produced snapshots (news,
experiment rollup/history, and TradingView credential report) point at tracked
seed files under `artifacts/live_overlay/` so the daemon (and local dashboard)
renders data out of the box. Realtime signals are the exception: they have no
CI producer and still default to `artifacts/open_prep/latest/latest_realtime_signals.json`.
CI producers push fresher snapshots to rolling `bot/*` branches; off-host
daemons should set the matching `*_SNAPSHOT_URL` / `*_HISTORY_URL` to consume
those instead.

- **HTTPS-only URL guard is centralized:** all runtime snapshot URL fetchers
  share one validation path and reject non-HTTPS URLs with a consistent warning
  (`<ENV_NAME> must be an https URL; ignoring ...`).

- **News**, the **experiment rollup + history**, and the **TradingView
  credential-age report** are published to rolling `bot/*` cache branches by CI
  (`smc-live-newsapi-refresh.yml` → `bot/live-news-snapshot`;
  `smc-measurement-benchmark-rolling.yml` → `bot/live-experiment-snapshot`;
  `credential-health-check.yml` → `bot/live-tv-credential-snapshot`). Point the
  matching `*_SNAPSHOT_URL` / `*_HISTORY_URL` at
  `https://api.github.com/repos/skippALGO/skipp-algo/contents/<path>?ref=<bot-branch>`
  with a fine-grained PAT (`Contents: Read`) in the `*_URL_TOKEN`.
- **Realtime signals on Railway** are fetched live from the internal
  `smc-signals-producer` service. Set `SIGNALS_SERVICE_URL` to the Railway
  private hostname (e.g. `smc-signals-producer.railway.internal`) and
  `SIGNALS_INTERNAL_TOKEN` to the bearer token the producer requires. This
  source takes precedence over all other signal sources; on failure the daemon
  falls back to `SIGNALS_SNAPSHOT_URL`, then the local `SIGNALS_SNAPSHOT_PATH`.
- **Realtime signals without a producer** — `latest_realtime_signals.json` is
  written only by `open_prep/realtime_signals.py` on the live trading host. To
  feed the hosted daemon when no producer is reachable, run
  [`scripts/publish_signals_snapshot.py`](../../scripts/publish_signals_snapshot.py)
  on that host (cron / after each engine cycle) with `GH_TOKEN` set to a PAT
  that can push to `bot/*`; it updates `bot/live-signals-snapshot` via
  `--force-with-lease` with branch-name validation (`--branch` cannot become a
  git flag) and a race-safe first-publish lease
  (`refs/heads/<branch>:0000000000000000000000000000000000000000`)
  so concurrent branch creation cannot be clobbered silently. Then set
  `SIGNALS_SNAPSHOT_URL=https://api.github.com/repos/skippALGO/skipp-algo/contents/artifacts/open_prep/latest/latest_realtime_signals.json?ref=bot/live-signals-snapshot`
  and `SIGNALS_SNAPSHOT_URL_TOKEN` to a `Contents: Read` PAT, exactly like the
  news snapshot.
  On first publish, an absent remote branch is treated as expected; unexpected
  `git fetch` failures (auth/network) are emitted as **redacted warnings** to
  stderr before seeding an empty branch.

- **GitHub Contents Accept header is now endpoint-scoped:** runtime snapshot
  fetchers set `Accept: application/vnd.github.raw+json` only for true
  GitHub Contents API URLs (`api.github.com/repos/.../contents/...`).
  Authenticated non-GitHub URLs no longer receive GitHub-specific `Accept`
  headers.
- **Write-through persistence:** on every successful `*_URL` fetch the daemon
  atomically writes the payload back to its `*_SNAPSHOT_PATH`
  (exclusive temp file + `os.replace`). Temp filenames include
  `pid.thread_id.time_ns` to avoid collisions under concurrent writers.
  On Railway, mount a volume and set the `*_PATH`
  vars to `/data/...` so a cold start reads the last-good copy instead of the
  baked seed. The volume mounts as root and the image runs as a non-root
  `appuser`, so set `RAILWAY_RUN_UID=0` to enable the write-through (it is
  best-effort and never blocks serving fresh URL data). See
  [OPS.md](OPS.md#snapshot-delivery--volume-persistence) for the exact commands.

---

## Deployment

### Railway.app (production)

- **URL:** `https://liveoverlaydaemon-production.up.railway.app`
- **Plan:** Starter (512 MB RAM)
- **Builder:** Dockerfile (`services/live_overlay_daemon/Dockerfile`)
- **Root Directory:** *(empty — repo root is build context)*
- **Branch:** `main` (switch after merging `feat/live-overlay-daemon`)
- **Health check path:** `/health`
- **Health check timeout:** 60 s
- **Restart policy:** ON_FAILURE, max 3 retries

### Key deployment notes

- `uvicorn` is used **without** `[standard]` extras to avoid the
  `uvloop` / Databento TCP conflict (`TypeError: object Future can't be used in
  'await' expression` on reconnect).
- Start command forces `--loop asyncio --http h11` for compatibility.
- The background feed thread creates its own event loop via
  `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)`.

### Local development

```bash
cd skipp-algo
DATABENTO_API_KEY=xxx OVERLAY_SECRET_TOKEN=mysecret \
  uvicorn services.live_overlay_daemon.main:app \
  --host 0.0.0.0 --port 8000 --workers 1 --loop asyncio --http h11
```

```bash
# Health check
curl http://localhost:8000/health

# Metrics (preferred, Basic auth)
curl -u "metrics:${OVERLAY_SECRET_TOKEN}" "http://localhost:8000/metrics"

# Metrics (legacy token-in-path)
curl "http://localhost:8000/mysecret/metrics"

# Overlay (replace TOKEN and symbol)
curl "http://localhost:8000/mysecret/smc_live?symbol=NVDA&tf=5m"
```

---

## Monitoring

### Telemetry architecture

```text
observability.py (structured log lines + in-process counters)
        │
        ├── /metrics  → Prometheus scrape → Grafana dashboards + alerts
        ├── /health   → Railway/Uptime liveness (binary up/down)
        ├── /ready    → readiness diagnostics (worker/feed/overlay state)
        └── stdout    → Railway Logs (human/debug) → optional log-drain
```

#### Metric names

(Prometheus-format via `/{token}/metrics`)

| Metric | Type | Source |
|--------|------|--------|
| `live_overlay_smc_live_requests_total` | counter | main.py |
| `live_overlay_smc_live_auth_denied` | counter | main.py |
| `live_overlay_smc_live_cache_miss_total` | counter | main.py |
| `live_overlay_smc_live_success_total` | counter | main.py |
| `live_overlay_health_requests_total` | counter | main.py |
| `live_overlay_full_compute_cycle_errors` | counter | feed.py |
| `live_overlay_flow_patch_cycle_errors` | counter | feed.py |
| `live_overlay_feed_reconnect_attempts` | counter | feed.py |
| `live_overlay_feed_bento_errors` | counter | feed.py |
| `live_overlay_feed_unexpected_errors` | counter | feed.py |
| `live_overlay_feed_circuit_breakers` | counter | feed.py |
| `live_overlay_feed_partial_restarts` | counter | feed.py |
| `live_overlay_uptime_seconds` | gauge | main.py |
| `live_overlay_overlay_symbols` | gauge | cache |
| `live_overlay_overlay_age_seconds` | gauge | cache |
| `live_overlay_smc_live_latency_p95_ms` | gauge | metrics.py (derived from histogram buckets) |
| `live_overlay_smc_live_latency_p99_ms` | gauge | metrics.py (derived from histogram buckets) |
| `live_overlay_last_bar_age_seconds` | gauge | feed.py |
| `live_overlay_feed_healthy` | gauge | feed.py |
| `live_overlay_workers_healthy` | gauge | feed.py |
| `live_overlay_worker_*_alive` | gauge | feed.py |
| `live_overlay_market_us_open` | gauge | market_hours.py |
| `live_overlay_market_europe_open` | gauge | market_hours.py |
| `live_overlay_market_asia_open` | gauge | market_hours.py |
| `live_overlay_daemon_restart_cause_<cause>_total` | counter | main.py/config.py |
| `live_overlay_daemon_restarts_total` | counter | main.py |
| `live_overlay_hotspot_symbols_tracked` | gauge | request_hotspots.py |
| `live_overlay_hotspot_timeframes_tracked` | gauge | request_hotspots.py |
| `live_overlay_hotspot_symbol_<symbol>_requests_total` | counter | request_hotspots.py |
| `live_overlay_hotspot_tf_<tf>_requests_total` | counter | request_hotspots.py |
| `live_overlay_feed_ingest_queue_depth` | gauge | feed.py backpressure snapshot |
| `live_overlay_feed_ingest_queue_depth_max` | gauge | feed.py backpressure snapshot |
| `live_overlay_feed_ingest_queue_dropped_total` | counter | feed.py backpressure snapshot (monotonically increasing drops) |
| `live_overlay_feed_ingest_queue_lag_ms_last` | gauge | feed.py backpressure snapshot |
| `live_overlay_feed_ingest_queue_lag_ms_max` | gauge | feed.py backpressure snapshot |
| `live_overlay_provider_news_snapshot_loaded` | gauge | metrics.py news provider snapshot probe |
| `live_overlay_provider_news_snapshot_age_seconds` | gauge | metrics.py news provider snapshot probe |
| `live_overlay_provider_news_snapshot_age_known` | gauge | metrics.py news provider snapshot probe (`1=timestamp known`) |
| `live_overlay_provider_news_providers_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_providers_ok_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_providers_degraded_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_providers_unknown_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_providers_disabled_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_providers_consumed_total` | gauge | metrics.py news provider snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_provider_news_health_ok` | gauge | metrics.py news provider snapshot probe |
| `live_overlay_provider_news_health_degraded` | gauge | metrics.py news provider snapshot probe |
| `live_overlay_provider_news_health_unknown` | gauge | metrics.py news provider snapshot probe |
| `live_overlay_provider_news_<provider>_ok` | gauge | metrics.py provider drill-down (`1=ok`) |
| `live_overlay_provider_news_<provider>_degraded` | gauge | metrics.py provider drill-down (`1=degraded`) |
| `live_overlay_provider_news_<provider>_state_code` | gauge | metrics.py provider drill-down (`0=unknown,1=degraded,2=ok,3=disabled`) |
| `live_overlay_provider_news_<provider>_consumed` | gauge | metrics.py provider drill-down (`1=consumed`, `0=excluded/disabled`) |
| `live_overlay_provider_news_info{provider,state,reason,consumed}` | gauge | metrics.py labeled provider reason/state info series |
| `live_overlay_trading_signals_loaded` | gauge | metrics.py signals snapshot probe |
| `live_overlay_trading_signals_active_total` | gauge | metrics.py signals snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_trading_signals_a0_total` | gauge | metrics.py signals snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_trading_signals_a1_total` | gauge | metrics.py signals snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_trading_signals_watched_total` | gauge | metrics.py signals snapshot probe (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_trading_signals_snapshot_age_known` | gauge | metrics.py signals snapshot probe |
| `live_overlay_trading_signals_snapshot_age_seconds` | gauge | metrics.py signals snapshot probe |
| `live_overlay_trading_signals_snapshot_max_age_seconds` | gauge | metrics.py signals snapshot probe (configured staleness threshold) |
| `live_overlay_trading_signals_snapshot_stale` | gauge | metrics.py signals snapshot probe (`1=stale`, `0=fresh/unknown`) |
| `live_overlay_trading_signal_*` | gauge | metrics.py per-signal labeled series (`score`, `freshness`, `technical_score`, `change_pct`, `info`) |
| `live_overlay_tradingview_credential_loaded` | gauge | metrics.py TradingView credential-health snapshot probe |
| `live_overlay_tradingview_credential_valid` | gauge | metrics.py TradingView credential-health snapshot probe (`0=error severity`, `1=ok/warn`) |
| `live_overlay_tradingview_credential_age_known` | gauge | metrics.py TradingView credential-health snapshot probe (`1=age_hours present`) |
| `live_overlay_tradingview_credential_age_hours` | gauge | metrics.py TradingView credential-health snapshot probe (`tv_storage_state_age.details.age_hours`) |
| `live_overlay_tradingview_credential_validated_at_seconds` | gauge | metrics.py TradingView credential-health snapshot probe (`tv_storage_state_age.details.validated_at`) |
| `live_overlay_credential_health_loaded` | gauge | metrics.py full credential-health report loaded (`1=yes`, `0=no`) |
| `live_overlay_credential_health_overall_valid` | gauge | metrics.py full credential-health report overall validity (`0=error severity`, `1=ok/warn/unknown`) |
| `live_overlay_credential_health_overall_severity_info` | gauge | metrics.py overall severity as a label (`severity=ok|warn|error|unknown`) |
| `live_overlay_credential_health_<probe>_severity_code` | gauge | metrics.py per-probe severity code (`0=error`, `1=warn`, `2=ok`) |
| `live_overlay_credential_health_<probe>_valid` | gauge | metrics.py per-probe validity (`0=error severity`, `1=ok/warn`) |
| `live_overlay_credential_health_<probe>_info` | gauge | metrics.py per-probe severity/message labels |
| `live_overlay_credential_health_<probe>_age_hours` | gauge | metrics.py `tv_storage_state_age.details.age_hours` |
| `live_overlay_credential_health_<probe>_validated_at_seconds` | gauge | metrics.py `tv_storage_state_age.details.validated_at` epoch |
| `live_overlay_credential_health_<probe>_days_left` | gauge | metrics.py `github_pat_validity.details.days_left` |
| `live_overlay_credential_health_<probe>_staleness_days` | gauge | metrics.py `databento_delivery.details.staleness_days` |
| `live_overlay_experiment_loaded` | gauge | metrics.py daily experiment snapshot probe |
| `live_overlay_experiment_snapshot_age_known` | gauge | metrics.py daily experiment snapshot probe |
| `live_overlay_experiment_snapshot_age_seconds` | gauge | metrics.py daily experiment snapshot probe |
| `live_overlay_experiment_files_scanned` | gauge | metrics.py daily experiment snapshot probe |
| `live_overlay_experiment_tf_*` | gauge | metrics.py per-timeframe experiment series (`hit_rate`, `n_events`) |
| `live_overlay_experiment_family_*` | gauge | metrics.py per-family experiment series (`hit_rate`, `n_events`) |
| `live_overlay_experiment_verdict_*` | gauge | metrics.py verdict series (`status_code`, `delta_hr`, `underpowered`, optional `p_value`) |
| `live_overlay_experiment_day_family_*` | gauge | metrics.py per-day history timeline/backfill series (`hit_rate`, `n_events`) |
| `live_overlay_uptimerobot_bridge_enabled` | gauge | uptimerobot_bridge.py |
| `live_overlay_uptimerobot_scrape_success` | gauge | uptimerobot_bridge.py |
| `live_overlay_uptimerobot_snapshot_age_seconds` | gauge | uptimerobot_bridge.py |
| `live_overlay_uptimerobot_monitors_*_total` | gauge | uptimerobot_bridge.py (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_uptimerobot_monitor_<id>_*` | gauge | uptimerobot_bridge.py |
| `live_overlay_github_workflow_bridge_enabled` | gauge | github_workflow_bridge.py |
| `live_overlay_github_workflow_scrape_success` | gauge | github_workflow_bridge.py |
| `live_overlay_github_workflow_snapshot_age_seconds` | gauge | github_workflow_bridge.py |
| `live_overlay_github_workflow_runs_*_total` | gauge | github_workflow_bridge.py (`_total` suffix reflects a count, but value is a snapshot) |
| `live_overlay_github_workflow_latest_run_*_seconds` | gauge | github_workflow_bridge.py aggregate latest run age/duration |
| `live_overlay_github_workflow_phase_code{workflow_id,workflow,event}` | gauge | metrics.py per-workflow timeline series |
| `live_overlay_github_workflow_latest_success{workflow_id,workflow,event}` | gauge | metrics.py per-workflow latest success state |
| `live_overlay_github_workflow_latest_age_seconds{workflow_id,workflow,event}` | gauge | metrics.py per-workflow latest run age |
| `live_overlay_github_workflow_latest_duration_seconds{workflow_id,workflow,event}` | gauge | metrics.py per-workflow latest run duration |
| `live_overlay_railway_metrics_enabled` | gauge | metrics.py Railway API snapshot reachable |
| `live_overlay_railway_metrics_age_seconds` | gauge | metrics.py Railway API snapshot age |
| `live_overlay_railway_metrics_error_info{error}` | gauge | metrics.py Railway API snapshot error |
| `live_overlay_railway_service_cpu_cores{service,service_id}` | gauge | metrics.py Railway per-service CPU cores |
| `live_overlay_railway_service_memory_gb{service,service_id}` | gauge | metrics.py Railway per-service memory usage |
| `live_overlay_railway_service_memory_limit_gb{service,service_id}` | gauge | metrics.py Railway per-service memory limit |
| `live_overlay_railway_service_memory_used_ratio{service,service_id}` | gauge | metrics.py Railway per-service memory pressure |
| `live_overlay_railway_service_disk_gb{service,service_id}` | gauge | metrics.py Railway per-service disk usage |
| `live_overlay_railway_service_network_rx_gb{service,service_id}` | gauge | metrics.py Railway per-service network receive |
| `live_overlay_railway_service_network_tx_gb{service,service_id}` | gauge | metrics.py Railway per-service network transmit |

> Railway service metrics are visualized in the *Railway Resources* dashboard
> row (CPU cores, memory used ratio, disk GB, network RX/TX GB, memory limit).

> Provider drill-down and trading-signal metric families intentionally use
> dynamic metric names (for example `live_overlay_provider_news_<provider>_*`
> and `live_overlay_trading_signal_*`). The Grafana dashboard queries these via
> `__name__=~...` regex matchers so adding providers/signals does not require
> panel rewrites.

### Alert rules (recommended)

| Condition | Severity | Action |
|-----------|----------|--------|
| `status != "ok"` for > 5 min | critical | Investigate feed + workers |
| `overlay_fresh == false` | high | Compute cycle hung or erroring |
| `workers_healthy == false` | critical | Thread died, check logs |
| `circuit_breakers > 0` | high | Feed outage exceeded max retries |
| `rate(bento_errors[5m]) > 0.5` | warning | Databento connectivity degraded |
| `overlay_age_seconds > max_stale_secs` | high | Compute not running |
| `overlay_symbols == 0` after 10 min | critical | No symbols computed |

### Grafana dashboard layout (v24)

The dashboard `services/live_overlay_daemon/infra/grafana/dashboard.json`
is organized into section rows to keep navigation fast during incidents:

- `External Integrations`
- `SLO & Reliability`
- `Provider Health`
- `Workflow Timeline`
- `Trading Signals`
- `Daily Experiment`
- `Railway Resources`

Operational UX additions:

- `Active Alerts (live_overlay)` alert-list panel for in-dashboard triage.
- Alert-list `no_data` state is intentionally filtered out to avoid ambiguous
  `unknown/no_data` UI noise during incidents.
- A dedicated alert rule (`lo-news-snapshot-series-missing`) captures missing
  news snapshot metric series via explicit `absent(...)` checks.
- Provider drill-down query excludes aggregate health series so per-provider
  `..._ok` / `..._degraded` timelines remain noise-free.

### UptimeRobot (free tier)

| Setting | Value |
|---------|-------|
| Monitor type | HTTP(s) |
| URL | `https://liveoverlaydaemon-production.up.railway.app/health` |
| Interval | 5 minutes |
| Alert | Email on down |

> The `/health` endpoint accepts both `GET` and `HEAD` (UptimeRobot sends HEAD).
> Use `/ready` for semantic status checks and deeper alerting.

---

## Pine Script consumer

See [`pine/smc_live_overlay_consumer.pine`](../../pine/smc_live_overlay_consumer.pine).

All 16 overlay fields are exposed as named `plot()` series so other scripts can
import them via `request.security()`. A dashboard table renders in the top-right
corner (toggle off in indicator settings).

### Usage

1. Open Pine Script Editor in TradingView
2. Paste `pine/smc_live_overlay_consumer.pine`
3. Set `OVERLAY_SECRET_TOKEN` in the `Overlay Token` input
4. Save as **private** script (do not publish publicly — token is in the URL)

> `request.raw()` requires **TradingView Premium**. On Free tier the script loads
> but all fields return `null` / stale until Premium is activated.

---

## Security

- Token is compared via `hmac.compare_digest` (constant-time, no timing oracle).
- Wrong token returns **404** (not 401/403) to avoid leaking the route structure.
- Keep the Pine script **invite-only** or private. Rotate `OVERLAY_SECRET_TOKEN`
  monthly: update Railway env var → update Pine script input → redeploy.
- `OVERLAY_SECRET_TOKEN` is never logged.

---

## Operational notes

### Symbol eviction (cache.py)

The bar cache tracks up to **2 000 symbols** (`OVERLAY_MAX_SYMBOLS`). When a new symbol
arrives and the cache is full, the **10 % least-recently-updated** symbols are
evicted in a single batch. This prevents unbounded memory growth during extended
sessions that stream `ALL_SYMBOLS`.

### Databento SDK private-attr guard (feed.py)

The feed loop reads `client._symbology_map` (a private attribute) to resolve
instrument IDs to ticker strings. If the attribute is absent (e.g. after a
databento SDK upgrade), a `WARNING` is logged and symbol resolution falls back
to an empty map. Monitor for this warning after upgrading the `databento` package.

### News snapshot error handling (compute.py)

`_load_news_snapshot()` caches the parsed JSON with a configurable TTL
(`OVERLAY_NEWS_CACHE_TTL_SECS`, default 600 s). If reading or parsing
the file fails, the error is logged at `WARNING` (with traceback) and the
compute cycle continues with an empty news dict rather than crashing the daemon.

### Circuit breaker (feed.py)

After **50 consecutive failures** (`_MAX_TOTAL_FAILURES`) without a successful
bar push, the feed thread logs `CRITICAL` and **stops**. This prevents endless
reconnect loops when the error is permanent (e.g. invalid API key, revoked
permissions). The health endpoint will continue responding but `bar_symbols`
will stay at 0.

### Startup readiness (main.py)

The readiness endpoint (`/ready`) returns market-aware daemon status and may be
`"starting"` until feed + workers + overlay freshness are healthy. Liveness
(`/health`) remains intentionally simple (`"alive"`) for probes like
Railway/UptimeRobot.

---

## Module structure

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, `/health`, `/{token}/smc_live` |
| `feed.py` | `db.Live()` consumer background thread with reconnect loop |
| `cache.py` | Thread-safe bar + overlay cache (`threading.Lock`) |
| `compute.py` | Overlay field computation (16 fields, news/flow/squeeze/ATS/events) |
| `config.py` | Env-var loader, `_require()` guards for mandatory vars |
| `Dockerfile` | Python 3.12-slim, repo-root build context |
| `railway.toml` | Railway build + deploy config |
| `requirements.txt` | `fastapi`, `uvicorn` (plain), `databento`, `psutil` |

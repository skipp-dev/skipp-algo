# SMC Live Overlay Daemon

FastAPI micro-service that subscribes to [Databento](https://databento.com) `EQUS.MINI` live feed
(schema `ohlcv-1m`, `ALL_SYMBOLS`) and exposes a per-symbol overlay JSON endpoint for
TradingView Pine scripts.

Deployed on [Railway.app](https://railway.com) — see [Deployment](#deployment).

---

## Architecture

```
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
  Railway healthcheck        Pine request.raw() consumer
  UptimeRobot HEAD probe     TradingView chart
```

---

## Endpoints

### `GET /health` / `HEAD /health`

No authentication required. **Liveness only** endpoint used by Railway healthcheck and UptimeRobot.

**Response (200 OK)**
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

**Response (200 OK)**
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

> `status` is `"starting"` until feed + workers + overlay_fresh are all healthy, then `"ok"`.
> `feed_healthy` becomes `false` after `stop()` or if bars are stale beyond `max_stale_secs`.
> `workers_healthy` is `false` if any of the three background threads (feed, refresh, flow) is dead.
> `overlay_fresh` is `false` when overlay_symbols == 0 or overlay_age > max_stale_secs.
> `HEAD` requests return only headers (body stripped by Starlette automatically).

---

### `GET /{token}/metrics`

Token-protected Prometheus text-format endpoint. Same token as `/smc_live`.
Returns all in-process counters (request totals, auth denials, compute errors,
feed errors) plus gauges (uptime, overlay age, bar count, worker liveness).

Used by Prometheus scrape jobs. Returns `text/plain; version=0.0.4`.

```bash
curl "http://localhost:8000/mysecret/metrics"
```

---

### `GET /{token}/smc_live?symbol=NVDA&tf=5m`

Token must match `OVERLAY_SECRET_TOKEN` env var (constant-time `hmac.compare_digest` comparison).
Returns **404** on wrong token (does not leak route existence).

**Query params**

| Param    | Required | Example | Notes |
|----------|----------|---------|-------|
| `symbol` | ✅ | `NVDA` | Case-insensitive, max 10 chars |
| `tf`     | ❌ | `5m` | One of `5m`, `15m`, `1H`, `4H`. Returns 400 for unknown values. |

**Response fields**

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

**Stale response** (symbol not yet in cache — pre-market or feed not connected):

All numeric fields are `null`, all bool fields are `false`, `stale: true`.

---

## Configuration (env vars)

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATABENTO_API_KEY` | ✅ | — | Set in Railway env vars |
| `OVERLAY_SECRET_TOKEN` | ✅ | — | Embedded in Pine URL path |
| `PORT` | ❌ | `8000` | Injected by Railway automatically |
| `OVERLAY_REFRESH_SECS` | ❌ | `1800` | Full overlay compute cycle interval (seconds) |
| `OVERLAY_FLOW_REFRESH_SECS` | ❌ | `300` | Flow-patch cycle interval (seconds) |
| `OVERLAY_ROLLING_BARS` | ❌ | `60` | Rolling window size for flow/ATS computations (range 1–500) |
| `OVERLAY_MAX_STALE_SECS` | ❌ | `3600` | Overlay age before `stale: true` (range 60–7200) |
| `OVERLAY_MAX_SYMBOLS` | ❌ | `2000` | Hard cap on tracked symbols in bar cache (range 100–50 000) |
| `OVERLAY_NEWS_CACHE_TTL_SECS` | ❌ | `600` | News snapshot cache TTL in seconds (range 60–3600) |
| `OVERLAY_MAX_FEED_FAILURES` | ❌ | `50` | Circuit-breaker threshold for consecutive feed failures (range 1–1000) |
| `NEWS_SNAPSHOT_PATH` | ❌ | *(repo root)*`/artifacts/smc_microstructure_exports/smc_live_news_snapshot.json` | Absolute path to news JSON file (resolved relative to repo root) |

### Config validation

- **`OVERLAY_ROLLING_BARS`** is clamped to `[1, 500]`. Out-of-range values are
  clamped with a `WARNING` log line.
- **`OVERLAY_MAX_STALE_SECS`** is clamped to `[60, 7200]` (1 min – 2 h). Same
  clamping + warning behaviour.
- **`OVERLAY_REFRESH_SECS`** is clamped to `[10, 86400]` (10 s – 24 h).
- **`OVERLAY_FLOW_REFRESH_SECS`** is clamped to `[5, 3600]` (5 s – 1 h).
- **`OVERLAY_NEWS_CACHE_TTL_SECS`** is clamped to `[60, 3600]` (1 min – 1 h).
- **`OVERLAY_MAX_SYMBOLS`** is clamped to `[100, 50000]`.
- **`OVERLAY_MAX_FEED_FAILURES`** is clamped to `[1, 1000]`.
- Non-integer values for any `_optional_int` variable are logged at `WARNING`
  and fall back to the documented default.

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

# Metrics (Prometheus text format)
curl "http://localhost:8000/mysecret/metrics"

# Overlay (replace TOKEN and symbol)
curl "http://localhost:8000/mysecret/smc_live?symbol=NVDA&tf=5m"
```

---

## Monitoring

### Telemetry architecture

```
observability.py (structured log lines + in-process counters)
        │
        ├── /metrics  → Prometheus scrape → Grafana dashboards + alerts
        ├── /health   → Railway/Uptime liveness (binary up/down)
        ├── /ready    → readiness diagnostics (worker/feed/overlay state)
        └── stdout    → Railway Logs (human/debug) → optional log-drain
```

**Metric names** (Prometheus-format via `/{token}/metrics`):

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
| `live_overlay_last_bar_age_seconds` | gauge | feed.py |
| `live_overlay_feed_healthy` | gauge | feed.py |
| `live_overlay_workers_healthy` | gauge | feed.py |
| `live_overlay_worker_*_alive` | gauge | feed.py |

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

**Usage:**
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

The health endpoint returns `"status": "starting"` until the feed thread has
pushed at least one OHLCV bar. After the first bar, it switches to `"ok"`.
This lets Railway/UptimeRobot distinguish a cold-starting daemon from one that
has successfully connected to Databento.

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

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
  (no auth)                  (token in path, HMAC compare)
        │                           │
  Railway healthcheck        Pine request.raw() consumer
  UptimeRobot HEAD probe     TradingView chart
```

---

## Endpoints

### `GET /health` / `HEAD /health`

No authentication required. Used by Railway healthcheck and UptimeRobot.

**Response (200 OK)**
```json
{
  "status": "ok",
  "uptime_secs": 406,
  "bar_symbols": 0,
  "bar_count": 0,
  "overlay_symbols": 0,
  "overlay_age_secs": null,
  "ts": "2026-06-16T13:17:30Z"
}
```

> `HEAD` requests return only headers (body stripped by Starlette automatically).

---

### `GET /{token}/smc_live?symbol=NVDA&tf=5m`

Token must match `OVERLAY_SECRET_TOKEN` env var (constant-time `hmac.compare_digest` comparison).
Returns **404** on wrong token (does not leak route existence).

**Query params**

| Param    | Required | Example | Notes |
|----------|----------|---------|-------|
| `symbol` | ✅ | `NVDA` | Case-insensitive, max 10 chars |
| `tf`     | ❌ | `5m` | One of `5m \| 15m \| 1H \| 4H \| 1D`. Returns 400 for unknown values. |

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
| `REFRESH_SECS` | ❌ | `1800` | Full overlay compute cycle interval (seconds) |
| `FLOW_REFRESH_SECS` | ❌ | `300` | Flow-patch cycle interval (seconds) |
| `ROLLING_BARS` | ❌ | `20` | Rolling window size for flow/ATS computations |
| `MAX_STALE_SECS` | ❌ | `600` | Overlay age before `stale: true` |
| `NEWS_SNAPSHOT_PATH` | ❌ | `/tmp/news_snapshot.json` | Path to news JSON file |

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

# Overlay (replace TOKEN and symbol)
curl "http://localhost:8000/mysecret/smc_live?symbol=NVDA&tf=5m"
```

---

## Monitoring

### UptimeRobot (free tier)

| Setting | Value |
|---------|-------|
| Monitor type | HTTP(s) |
| URL | `https://liveoverlaydaemon-production.up.railway.app/health` |
| Interval | 5 minutes |
| Alert | Email on down |

> The `/health` endpoint accepts both `GET` and `HEAD` (UptimeRobot sends HEAD).

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

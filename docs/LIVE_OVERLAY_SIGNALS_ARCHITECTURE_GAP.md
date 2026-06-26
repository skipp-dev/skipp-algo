# Live Overlay + Signals Producer — Architecture GAP Analysis

> Status: 2026-06-26  
> Scope: Railway deployment of `smc-live-overlay` and `smc-signals-producer`,
> plus the local manual `smc-signals-producer` that is used only on demand.

## 1. Intended architecture

```text
┌────────────────────────────────────────────────────────────────────────────────────┐
│                                 Railway (Production)                                │
│                                                                                      │
│  ┌──────────────────────────────┐        ┌─────────────────────────────────────┐    │
│  │ smc-signals-producer         │        │ smc-live-overlay                    │    │
│  │ (open_prep/realtime_signals) │        │ (live_overlay_daemon)               │    │
│  │                              │        │                                     │    │
│  │ Inputs:                      │        │ Inputs:                             │    │
│  │ • FMP_API_KEY                │        │ • Databento live feed               │    │
│  │ • latest_open_prep_run.json  │        │ • *_SNAPSHOT_URL / *_SNAPSHOT_PATH  │    │
│  │                              │        │ • smc-signals-producer /signals     │    │
│  │ Outputs:                     │        │ • UptimeRobot / GitHub / Railway    │    │
│  │ • /signals  ────────────────┼────────►│                                     │    │
│  │ • /metrics                   │        │ Outputs:                            │    │
│  │ • /healthz                   │        │ • /smc_live  → Pine Script          │    │
│  │ • /telemetry.json            │        │ • /metrics   → metrics-collector    │    │
│  └──────────┬───────────────────┘        └──────────────────┬──────────────────┘    │
│             │                                                │                       │
│             └────────────────┬───────────────────────────────┘                       │
│                              │                                                       │
│                              ▼                                                       │
│                   ┌──────────────────────┐                                           │
│                   │ metrics-collector    │                                           │
│                   │ (Grafana Alloy)      │                                           │
│                   │ scrapes /metrics     │                                           │
│                   │ from both services   │                                           │
│                   └──────────┬───────────┘                                           │
│                              │                                                       │
└──────────────────────────────┼───────────────────────────────────────────────────────┘
                               │
                               │ Prometheus remote-write
                               ▼
                    ┌──────────────────────┐
                    │ Grafana Cloud        │
                    │ (monitoring only)    │
                    └──────────────────────┘
```

**Role of each component:**

| Component | Purpose | Runs where | Monitored by Grafana? |
|-----------|---------|------------|----------------------|
| `smc-signals-producer` | Polls FMP, detects A0/A1 breakouts, serves `/signals` | Railway (always on) | Yes (process metrics) |
| `smc-live-overlay` | Aggregates all data sources, serves `/smc_live` for Pine and `/metrics` for Alloy | Railway (always on) | Yes |
| `metrics-collector` | Grafana Alloy, scrapes `/metrics` from both services | Railway (always on) | Yes (self-metrics) |
| Pine Script | End consumer of `GET /smc_live` | TradingView / client browsers | No |
| Local `smc-signals-producer` | Manual, on-demand runs for local analysis / VisiData | Developer machine | No |

**Important:** Grafana is purely a monitoring/visualization tool. It is **not**
part of the operational data path between `smc-signals-producer` and
`smc-live-overlay`.

## 2. Current state vs. intended state

| Area | Intended | Current | Gap |
|------|----------|---------|-----|
| **Signal delivery to overlay** | `smc-live-overlay` fetches `/signals` from `smc-signals-producer.railway.internal` | `smc-live-overlay` only reads `SIGNALS_SNAPSHOT_PATH` / `SIGNALS_SNAPSHOT_URL` (local file or GitHub bot branch) | No direct service-to-service call |
| **Signal freshness in overlay** | Real-time A0/A1 signals appear in `/smc_live` and `/metrics` within seconds | Overlay dashboard shows stale or empty signal data unless `SIGNALS_SNAPSHOT_URL` is manually configured to a bot branch | Live producer output is not consumed |
| **Env configuration** | `SIGNALS_SERVICE_URL` + `SIGNALS_INTERNAL_TOKEN` used by `smc-live-overlay` | `SIGNALS_SERVICE_URL` only used by Alloy; `SIGNALS_INTERNAL_TOKEN` only guards Alloy scrapes | Overlay daemon has no config for producer URL/token |
| **Code path** | `_load_signals_snapshot()` in `compute.py` tries producer first, then local/URL fallback | `_load_signals_snapshot()` only knows local path + `SIGNALS_SNAPSHOT_URL` | Missing producer client |
| **Metrics** | Overlay exposes live signal counts, A0/A1 counts, per-symbol signal state | Overlay exposes signal data only from file/URL snapshot | No live signal metrics from producer |
| **Documentation** | Architecture shows producer → overlay data flow | Architecture shows producer only as a source of process metrics for Alloy | Misleading diagrams and env-var tables |

## 3. Options to close the gap

### Option A: `smc-live-overlay` calls `smc-signals-producer /signals`

**Implementation:**
- Add `SIGNALS_SERVICE_URL` and `SIGNALS_INTERNAL_TOKEN` to `services/live_overlay_daemon/config.py`.
- Extend `compute._load_signals_snapshot()` to fetch `http://<SIGNALS_SERVICE_URL>/signals` with `Authorization: Bearer <SIGNALS_INTERNAL_TOKEN>` when the env var is set.
- Fall back to existing `SIGNALS_SNAPSHOT_PATH` / `SIGNALS_SNAPSHOT_URL` if the producer call fails or is not configured.
- Update `metrics.py` to surface live signal counts from the producer.
- Update Alloy config: already correct, no change needed.

**Pros:**
- Single live source of truth on Railway.
- No extra bot branch, no publish script, no cron.
- Leverages existing internal Railway network and existing auth token.
- Lowest operational complexity.

**Cons:**
- Adds a runtime dependency: if `smc-signals-producer` is down, overlay signals are empty unless fallback is configured.
- Slightly more code in `compute.py` (HTTP client with bearer auth).
- Requires `SIGNALS_INTERNAL_TOKEN` to become mandatory in Railway.

**Recommended?** ✅ **Yes.** This matches the intended architecture and removes the stale-snapshot problem.

---

### Option B: Keep file/URL snapshot as primary path

**Implementation:**
- Keep current behavior.
- Document that operators must run `scripts/publish_signals_snapshot.py` on a host (or in a Railway cron job) to push `latest_realtime_signals.json` to `bot/live-signals-snapshot`.
- Set `SIGNALS_SNAPSHOT_URL` in Railway to the bot-branch raw URL.

**Pros:**
- No code changes in `smc-live-overlay`.
- Works with the existing URL-first loader.
- Producer and overlay are decoupled.

**Cons:**
- Requires a separate publishing mechanism (cron, bot branch, PAT).
- Signals are only as fresh as the last publish (minutes, not seconds).
- The Railway `smc-signals-producer` service becomes mostly redundant for the overlay dashboard.
- More moving parts and credentials.

**Recommended?** ❌ No. This contradicts the intended architecture and reintroduces the staleness problem.

---

### Option C: Shared persistent volume

**Implementation:**
- Mount the same Railway volume to both `smc-signals-producer` and `smc-live-overlay`.
- `smc-signals-producer` writes `latest_realtime_signals.json` to the volume.
- `smc-live-overlay` reads it from the shared volume path.

**Pros:**
- Simple file-based coupling, no HTTP client needed.
- Works with existing `SIGNALS_SNAPSHOT_PATH` logic.

**Cons:**
- Railway volumes are paid and add deployment complexity.
- File locking / stale-read race conditions possible.
- Two services become tied to the same filesystem.
- Not portable, harder to test locally.

**Recommended?** ❌ No. Over-engineered for this use case; HTTP is cleaner on Railway.

---

### Option D: Merge the two services

**Implementation:**
- Run `open_prep/realtime_signals` as a background thread inside `smc-live-overlay`.
- Single Docker image, single Railway service.

**Pros:**
- No inter-service networking.
- Single deploy artifact.

**Cons:**
- Violates separation of concerns.
- `realtime_signals` has different scaling/resource needs (FMP polling, heavy CPU) than the overlay daemon.
- Harder to restart/update one component independently.
- Large refactor.

**Recommended?** ❌ No. The two services were intentionally separated; keep them separated.

## 4. Recommended implementation plan

1. **Config** (`services/live_overlay_daemon/config.py`):
   - Add `signals_service_url()` → reads `SIGNALS_SERVICE_URL`.
   - Add `signals_internal_token()` → reads `SIGNALS_INTERNAL_TOKEN`.

2. **Compute** (`services/live_overlay_daemon/compute.py`):
   - Extend `_load_signals_snapshot()` with a producer-first branch:
     - If `signals_service_url()` is set, `GET http://<url>/signals.json` with bearer token.
     - If producer returns valid JSON, use it.
     - Else fall back to `SIGNALS_SNAPSHOT_URL`, then `SIGNALS_SNAPSHOT_PATH`.
   - Add TTL/caching to avoid hammering the producer on every metrics scrape.

3. **Metrics** (`services/live_overlay_daemon/metrics.py`):
   - Ensure signal counts and per-symbol state reflect live producer data.

4. **Auth / Ops**:
   - Mark `SIGNALS_SERVICE_URL` and `SIGNALS_INTERNAL_TOKEN` as required for Railway.
   - Update `services/live_overlay_daemon/railway.toml` env hints if applicable.
   - Update `docs/LIVE_OVERLAY_INFRA_OPS.md` (already done in this branch).

5. **Tests**:
   - Add producer-mock test for `_load_signals_snapshot()`.
   - Add env-var tests in `tests/test_smc_live_overlay_robustness.py` or a new test file.

6. **Alloy**:
   - Verify `config.alloy` still scrapes both services; no change required.

## 5. Out of scope

- The **local manual** `smc-signals-producer` on the developer machine is not part
  of this architecture. It does not need to be monitored by Grafana and does not
  feed the Railway overlay daemon.
- Grafana dashboards for the producer are fine as-is (process metrics only); the
  change is about getting A0/A1 signal **data** into the overlay daemon.

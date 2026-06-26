# Live Overlay + Signals Producer — Architecture GAP Analysis

> Status: 2026-06-26 — Option A implemented in PR #2962 (pending merge)  
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
│  │                              │        │ • smc-signals-producer /signals.json │    │
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

> All gaps below were closed by **PR #2962** (`feat(overlay): consume live signals directly from smc-signals-producer`), currently pending merge.

| Area | Intended | Current (after PR #2962) | Status |
|------|----------|--------------------------|--------|
| **Signal delivery to overlay** | `smc-live-overlay` fetches `/signals.json` from `smc-signals-producer.railway.internal` | `smc-live-overlay` calls the producer first, then falls back to `SIGNALS_SNAPSHOT_URL` / `SIGNALS_SNAPSHOT_PATH` | ✅ Closed |
| **Signal freshness in overlay** | Real-time A0/A1 signals appear in `/smc_live` and `/metrics` within seconds | Producer signals are consumed live; fallback paths keep stale data from blocking cold starts | ✅ Closed |
| **Env configuration** | `SIGNALS_SERVICE_URL` + `SIGNALS_INTERNAL_TOKEN` used by `smc-live-overlay` | `config.signals_service_url()` and `config.signals_internal_token()` read the env vars | ✅ Closed |
| **Code path** | `_load_signals_snapshot()` in `compute.py` tries producer first, then local/URL fallback | `_fetch_signals_service()` implements the producer-first branch with TTL/caching | ✅ Closed |
| **Metrics** | Overlay exposes live signal counts, A0/A1 counts, per-symbol signal state | `metrics.py` reads through `_load_signals_snapshot()`, so gauges reflect the live producer | ✅ Closed |
| **Documentation** | Architecture shows producer → overlay data flow | `docs/LIVE_OVERLAY_INFRA_OPS.md` and daemon README/OPS updated | ✅ Closed |

## 3. Options to close the gap

### Option A: `smc-live-overlay` calls `smc-signals-producer /signals`

**Implementation:**
- Add `SIGNALS_SERVICE_URL` and `SIGNALS_INTERNAL_TOKEN` to `services/live_overlay_daemon/config.py`.
- Extend `compute._load_signals_snapshot()` to fetch `http://<SIGNALS_SERVICE_URL>/signals.json` with `Authorization: Bearer <SIGNALS_INTERNAL_TOKEN>` when the env var is set.
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

## 4. Implementation plan (completed in PR #2962)

- [x] **Config** (`services/live_overlay_daemon/config.py`):
  - Added `signals_service_url()` → reads `SIGNALS_SERVICE_URL`.
  - Added `signals_internal_token()` → reads `SIGNALS_INTERNAL_TOKEN`.

- [x] **Compute** (`services/live_overlay_daemon/compute.py`):
  - Extended `_load_signals_snapshot()` with a producer-first branch:
    - If `signals_service_url()` is set, `GET http://<url>/signals.json` with bearer token.
    - If producer returns valid JSON, use it.
    - Else fall back to `SIGNALS_SNAPSHOT_URL`, then `SIGNALS_SNAPSHOT_PATH`.
  - Added TTL/caching (`OVERLAY_SIGNALS_CACHE_TTL_SECS`) to avoid hammering the producer.

- [x] **Metrics** (`services/live_overlay_daemon/metrics.py`):
  - Signal gauges read through `_load_signals_snapshot()`, so they automatically reflect live producer data.

- [x] **Auth / Ops**:
  - `SIGNALS_SERVICE_URL` and `SIGNALS_INTERNAL_TOKEN` are documented as required Railway service variables for `smc-live-overlay`.
  - `docs/LIVE_OVERLAY_INFRA_OPS.md` and daemon README/OPS updated.

- [x] **Tests**:
  - Added producer-fetch and fallback tests in `tests/test_live_overlay_snapshot_write_through.py`.
  - Added env-var tests in `tests/test_smc_live_overlay_config_env_precedence.py`.

- [x] **Alloy**:
  - `config.alloy` already scraped both services; no change required.

## 5. Out of scope

- The **local manual** `smc-signals-producer` on the developer machine is not part
  of this architecture. It does not need to be monitored by Grafana and does not
  feed the Railway overlay daemon.
- Grafana dashboards for the producer are fine as-is (process metrics only); the
  change is about getting A0/A1 signal **data** into the overlay daemon.

## 6. Implementation status

| Milestone | PR | Status |
|-----------|-----|--------|
| Option A: Direct producer-to-overlay signal consumption | [#2962](https://github.com/skippALGO/skipp-algo/pull/2962) | ⏳ Pending merge |
| Architecture documentation corrected | [#2961](https://github.com/skippALGO/skipp-algo/pull/2961) | ✅ Merged |
| Default snapshot paths fixed | [#2958](https://github.com/skippALGO/skipp-algo/pull/2958) | ✅ Merged |

### Operational notes after implementation

- `smc-live-overlay` must have `SIGNALS_SERVICE_URL` (e.g. `smc-signals-producer.railway.internal`) and `SIGNALS_INTERNAL_TOKEN` set in Railway.
- The producer is queried at `http://<SIGNALS_SERVICE_URL>/signals.json`.
- If the producer is unreachable, the daemon falls back to `SIGNALS_SNAPSHOT_URL` and then `SIGNALS_SNAPSHOT_PATH`.
- `metrics-collector` (Grafana Alloy) remains monitoring-only and scrapes `/metrics` from both services.
- Rollback: unset `SIGNALS_SERVICE_URL` in the `smc-live-overlay` Railway environment to restore the previous file/URL-only behavior.

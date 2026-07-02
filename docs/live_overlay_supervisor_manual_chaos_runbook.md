# Live Overlay Daemon: Manual Supervisor Chaos Runbook

Status: 2026-07-02
Scope: Manual operator validation for WP1 self-heal supervisor behavior (feed worker death, stale feed, fatal config).

## Quick start (5 minutes)

Use this when you need a rapid confidence check before the full run.

1. Confirm readiness is healthy.
2. Capture baseline metrics (worker alive gauges + supervisor heal counter).
3. Inject one short transient fault.
4. Wait 60-90s (2 supervisor cycles) and confirm auto-recovery.
5. Record evidence and stop.

```bash
# 1) Baseline readiness
curl -sS -o /tmp/ready_before.json -w "HTTP %{http_code}\n" "https://<daemon-host>/ready"
cat /tmp/ready_before.json

# 2) Baseline worker/heal metrics
curl -sS -u "metrics:${OVERLAY_SECRET_TOKEN}" "https://<daemon-host>/metrics" \
  | grep -E "live_overlay_feed_supervisor_heals_total|live_overlay_worker_.*_alive|live_overlay_feed_healthy"

# 3) Inject a short transient fault in staging (example: temporary Databento path interruption)
#    Keep it brief, then restore connectivity.

# 4) Verify recovery after 60-90s
curl -sS -o /tmp/ready_after.json -w "HTTP %{http_code}\n" "https://<daemon-host>/ready"
cat /tmp/ready_after.json
curl -sS -u "metrics:${OVERLAY_SECRET_TOKEN}" "https://<daemon-host>/metrics" \
  | grep -E "live_overlay_feed_supervisor_heals_total|live_overlay_worker_live_feed_alive"
```

Quick-start pass:

- `/ready` is `HTTP 200` after recovery.
- `workers_healthy=true` and feed worker alive gauge is back to `1`.
- `live_overlay_feed_supervisor_heals_total` increased by at least `+1` after the induced fault.

## 1. Goal and pass criteria

Goal: Prove that the daemon self-heals transient worker failures and escalates only after configured limits.

Pass criteria:

- A single worker failure is healed automatically.
- `live_overlay_feed_supervisor_heals_total` increases after induced failure.
- `/ready` is green (HTTP 200) after successful heal.
- Repeated failure beyond `_SELF_HEAL_MAX_ATTEMPTS=3` escalates with process exit (`os._exit(1)`), allowing Railway restart policy `ON_FAILURE` to recover service.
- Stale feed condition (`last_bar_age_secs > _STALL_MAX_BAR_AGE_SECS=180`) triggers active client stop and restart attempt.

## 2. Preconditions

- Branch with WP1-WP5 merged into daemon runtime is deployed.
- Railway service has:
  - `restartPolicyType=ON_FAILURE`
  - healthcheck path set to `/ready`
- Required env vars are present:
  - `DATABENTO_API_KEY`
  - `OVERLAY_SECRET_TOKEN`
- Optional but recommended tuning:
  - `OVERLAY_MAX_FEED_FAILURES` (default 50)

## 3. Fast baseline check (before chaos)

Run these checks and save outputs in the incident note.

```bash
# 1) readiness should be healthy
curl -sS -o /tmp/ready.json -w "HTTP %{http_code}\n" "https://<daemon-host>/ready"
cat /tmp/ready.json

# 2) metrics should expose supervisor counter
curl -sS -u "metrics:${OVERLAY_SECRET_TOKEN}" "https://<daemon-host>/metrics" \
  | grep -E "live_overlay_feed_supervisor_heals_total|live_overlay_worker_.*_alive|live_overlay_feed_healthy"
```

Expected baseline:

- `/ready` returns `HTTP 200` and `workers_healthy=true`.
- `live_overlay_worker_live_feed_alive 1`
- `live_overlay_worker_overlay_refresh_alive 1`
- `live_overlay_worker_flow_refresh_alive 1`

## 4. Test A: Simulate single worker death (should self-heal)

### Step A1: Induce failure

Use a controlled one-shot fault method in your staging environment (for example SIGTERM to the feed worker process container, or a temporary network interruption to Databento path).

Note: prefer network-level fault injection over code patching in this manual run.

### Step A2: Observe during 2 supervisor cycles

Supervisor interval is 30s. Observe for about 60-90s.

```bash
# repeat a few times during observation window
curl -sS "https://<daemon-host>/ready" | jq '{status,workers_healthy,feed_healthy,last_bar_age_secs,worker_liveness,feed_metrics}'

curl -sS -u "metrics:${OVERLAY_SECRET_TOKEN}" "https://<daemon-host>/metrics" \
  | grep -E "live_overlay_feed_supervisor_heals_total|live_overlay_feed_reconnect_attempts_total|live_overlay_worker_live_feed_alive"
```

Expected:

- Temporary degradation may appear (`workers_healthy=false` or dead worker gauge).
- Within 1-2 cycles, worker recovers and `/ready` returns healthy again.
- `live_overlay_feed_supervisor_heals_total` increments by at least 1.

## 5. Test B: Simulate stale feed (bar-age breach)

### Step B1: Force stale condition

Pause/blackhole live bar ingress long enough to exceed 180s bar age.

### Step B2: Verify supervisor reaction

```bash
curl -sS "https://<daemon-host>/ready" | jq '{feed_healthy,last_bar_age_secs,workers_healthy,feed_metrics}'
curl -sS -u "metrics:${OVERLAY_SECRET_TOKEN}" "https://<daemon-host>/metrics" \
  | grep -E "live_overlay_feed_supervisor_heals_total|live_overlay_feed_partial_restarts_total|live_overlay_feed_unexpected_errors_total"
```

Expected:

- `last_bar_age_secs` grows beyond 180 before intervention.
- Supervisor stops active client and attempts recovery.
- Heal counter or restart-related counters increase.
- Service returns to healthy once feed resumes.

## 6. Test C: Exhaust heal budget (escalation path)

Purpose: verify hard escalation after repeated failures, then platform restart.

### Step C1: Repeat failure injection > 3 attempts

Trigger persistent failure so each heal attempt cannot stabilize.

### Step C2: Confirm process exit and platform restart

```bash
# Railway logs / deploy events (example via UI or CLI)
# check for exit and restart cycle
```

Expected:

- After max attempts are exhausted, process exits intentionally.
- Railway restarts service via `ON_FAILURE` policy.
- Post-restart `/ready` returns 200 once warm.

## 7. Negative test: Fatal config error

Purpose: verify non-retryable config errors go to escalation, not endless retries.

Method (staging only): remove or invalidate a required config (for example `DATABENTO_API_KEY`) and restart.

Expected:

- Startup path marks fatal configuration error.
- Supervisor escalates to process exit.
- Platform restart occurs, but remains unhealthy until config is fixed.

Rollback immediately after test.

## 8. Evidence checklist

Capture all of the following:

- Timestamped `/ready` snapshots before, during, after each test.
- Metric lines for:
  - `live_overlay_feed_supervisor_heals_total`
  - `live_overlay_worker_*_alive`
  - feed restart/error counters
- Railway restart/deploy log snippets for escalation test.
- Final green-state confirmation.

## 9. Abort criteria and safety

Abort the run immediately if:

- Production user traffic is impacted.
- Restart loop exceeds expected recovery window.
- Metrics endpoint/auth is unavailable during incident.

Safety rules:

- Run in staging first.
- Execute one chaos vector at a time.
- Wait for full recovery before next vector.

## 10. Operator summary template

Use this template in PR comment or ops ticket.

```text
Run date:
Environment:
Operator:

Test A (single worker death): PASS/FAIL
- heal counter delta:
- recovery time:

Test B (stale feed >180s): PASS/FAIL
- max observed last_bar_age_secs:
- recovery time:

Test C (exhaust >3 attempts): PASS/FAIL
- escalation observed:
- platform restart observed:

Fatal config test: PASS/FAIL
- expected unhealthy behavior observed:

Final readiness state:
Notes/follow-ups:
```

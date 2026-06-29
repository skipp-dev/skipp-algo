# Grafana Alloy — Metrics Collector

Scrapes `/metrics` from the live overlay daemon and remote-writes to
Grafana Cloud. Runs as a separate Railway service in the same project.

The daemon exposes `/metrics` with **Basic auth**. Alloy sends the
`OVERLAY_SECRET_TOKEN` as the Basic auth password. This keeps the token out
of Prometheus target labels, scrape logs, and remote-write metadata.

## Railway Setup

1. **Create a new service** in the Railway project:
   - Name: `metrics-collector`
   - Root directory: `services/live_overlay_daemon/infra/alloy`
   - Builder: Dockerfile
   - Healthcheck path: `/metrics`

2. **Set environment variables** (Service Variables):
   ```
   OVERLAY_SECRET_TOKEN=<same as main daemon>
   # Current production uses the public Railway host without scheme.
   # Private networking can use liveoverlaydaemon.railway.internal:<PORT>
   # after the live daemon runtime PORT is verified from inside Railway.
   OVERLAY_SERVICE_URL=liveoverlaydaemon-production.up.railway.app
   GRAFANA_CLOUD_PROM_URL=https://prometheus-prod-XX-prod-XX.grafana.net/api/prom/push
   GRAFANA_CLOUD_USER=<numeric stack ID>
   GRAFANA_CLOUD_API_KEY=<API key with MetricsPublisher role>
   ```

3. **Health check** — Alloy's HTTP server must bind to the Railway-provided
   port. The Dockerfile passes
   `--server.http.listen-addr=0.0.0.0:${PORT}` after defaulting `PORT` to
   `12345` for local runs, so Railway can reach the service healthcheck instead
   of probing Alloy's default loopback listener. The repo-local
   `railway.toml` sets the healthcheck path to `/metrics`, which Alloy exposes
   on the same HTTP server.

   The Dockerfile also defaults `ALLOY_SELF_ADDRESS` to `127.0.0.1:$PORT` so the
   `alloy_self` scrape target follows the runtime port rather than staying
   pinned to Alloy's default `12345`.

4. **Networking**: Prefer Railway Private Networking for the main-daemon scrape
   once the runtime port is known. Do not set `OVERLAY_SERVICE_URL` to a bare
   `.railway.internal` hostname; Alloy needs `host:port`. Keep the public
   Railway host until `up{job="live_overlay"} == 1` has been confirmed after
   the private-host switch.

## Grafana Cloud Free Tier

- Sign up at https://grafana.com/products/cloud/ (free forever tier)
- 10,000 active series, 14-day retention — sufficient for our ~30 metrics
- Get the Prometheus remote-write URL + user + API key from:
  Stack → Connections → Prometheus → Remote Write

## Generic bridge contract

The live overlay daemon exports a uniform family of bridge metrics so that
dashboards and alerts do not depend on per-integration metric names:

```promql
live_overlay_bridge_enabled{bridge="uptimerobot"}
live_overlay_bridge_configured{bridge="uptimerobot"}
live_overlay_bridge_scrape_success{bridge="uptimerobot"}
live_overlay_bridge_error_info{bridge="uptimerobot",error="none"}
```

`bridge` is one of `uptimerobot`, `github_workflow`, or `railway_metrics`.
`enabled` is `1` when the bridge is turned on for this deployment;
`configured` is `1` when the required credentials/environment are present;
`scrape_success` is `1` when the last poll succeeded.
`error_info` exposes the active error class (`error="none"` when healthy).

If you add a new bridge, emit these four series with a new `bridge` label
value and update both the dashboard alert `lo-bridge-contract-missing` and
the `Bridge Metrics Present` panel so the contract is tracked end-to-end.

## Validation

After deploying, verify in Grafana Cloud → Explore:
```promql
live_overlay_smc_live_requests_total
live_overlay_uptime_seconds
live_overlay_feed_healthy
up{job="live_overlay"}
increase(prometheus_remote_storage_samples_failed_total{job="alloy"}[10m])
```

## Security note

The legacy path `/{token}/metrics` is still supported for backwards
compatibility, but new deployments should use `/metrics` with Basic auth
so the secret token does not appear in observability metadata.

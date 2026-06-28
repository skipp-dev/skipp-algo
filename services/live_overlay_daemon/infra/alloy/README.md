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

2. **Set environment variables** (Service Variables):
   ```
   OVERLAY_SECRET_TOKEN=<same as main daemon>
   # Current production uses the public Railway host without scheme.
   # Private networking can use liveoverlaydaemon.railway.internal:<PORT>.
   OVERLAY_SERVICE_URL=liveoverlaydaemon-production.up.railway.app
   GRAFANA_CLOUD_PROM_URL=https://prometheus-prod-XX-prod-XX.grafana.net/api/prom/push
   GRAFANA_CLOUD_USER=<numeric stack ID>
   GRAFANA_CLOUD_API_KEY=<API key with MetricsPublisher role>
   ```

3. **No health check needed** — Alloy runs as a pure scraper without inbound traffic.

4. **Networking**: Uses Railway Private Networking to reach the main daemon
   (no public internet hop, no additional auth layer needed beyond the token).

## Grafana Cloud Free Tier

- Sign up at https://grafana.com/products/cloud/ (free forever tier)
- 10,000 active series, 14-day retention — sufficient for our ~30 metrics
- Get the Prometheus remote-write URL + user + API key from:
  Stack → Connections → Prometheus → Remote Write

## Validation

After deploying, verify in Grafana Cloud → Explore:
```promql
live_overlay_smc_live_requests_total
live_overlay_uptime_seconds
live_overlay_feed_healthy
```

## Security note

The legacy path `/{token}/metrics` is still supported for backwards
compatibility, but new deployments should use `/metrics` with Basic auth
so the secret token does not appear in observability metadata.

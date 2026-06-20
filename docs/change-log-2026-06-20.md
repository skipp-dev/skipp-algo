# Change Log — 2026-06-20

## Überblick

Dieser Eintrag dokumentiert alle heutigen Änderungen laut Git-Historie auf `main`.
Schwerpunkt war die Stabilisierung und Observability des `live_overlay_daemon` inklusive Grafana-Dashboard/Alerting sowie ein Alloy-Fix.

## Heutige Commits (chronologisch rückwärts)

1. `bbca2c03` — **feat(grafana): add market-aware health status telemetry**
   - Neue market-aware Health-Status-Metriken im Prometheus-Output:
     - `live_overlay_health_status_ok`
     - `live_overlay_health_status_starting`
     - `live_overlay_health_status_idle_market_closed`
     - `live_overlay_market_open`
   - Dashboard aktualisiert:
     - Service-Status zeigt market-aware Zustand
     - explizite Threshold-Modi an relevanten Panels
     - Auto-Refresh (`30s`)

2. `69c7817c` — **fix(grafana-alerts): use actual Prometheus datasource UID**
   - `alert-rules.yaml` auf die tatsächlich gültige Datasource-UID `grafanacloud-prom` korrigiert.

3. `f1d72e9a` — **chore(grafana): align alert rules datasource UID**
   - Datasource-UID in Alert-Regeln initial auf Stack-spezifischen Namen umgestellt (später via `69c7817c` auf reale UID korrigiert).

4. `69c00938` — **chore(grafana): improve live-overlay dashboard signal readability**
   - Dashboard-Verbesserungen:
     - explizite Job-Selector in Queries
     - `[$__rate_interval]` statt hardcoded `[5m]`
     - State Timeline für Worker-Liveness
     - bessere Stat-/Timeseries-Konfiguration (Tooltip, Legend, Farben, Schwellen)

5. `8c3bc3cd` — **feat(live-overlay): mark health as idle_market_closed outside US session**
   - `/health` erweitert um market-aware Statuslogik (`ok` / `starting` / `idle_market_closed`)
   - Session-Erkennung für US-Regular-Hours (ET)
   - relevante Tests + Ledger-Pins aktualisiert

6. `352c8266` — **fix(alloy): remove queue_config + use sys.env() (#2863)**
   - Alloy-Konfigurationsfix für stabilen Collector-Start.

7. `1679bc71` — **chore(open_prep): outcome backfill ... (#2864)**
   - Open-prep Outcome/Artifact-Backfill.

## Betroffene Dateien (Union laut Git)

- `services/live_overlay_daemon/infra/alloy/config.alloy`
- `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`
- `services/live_overlay_daemon/infra/grafana/dashboard.json`
- `services/live_overlay_daemon/main.py`
- `services/live_overlay_daemon/metrics.py`
- `tests/test_smc_live_overlay_robustness.py`
- `tests/test_smc_live_overlay_metrics_endpoint.py` (verifiziert, nicht zwingend heute geändert)
- `tests/test_hmac_auth_zero_surface.py`
- `tests/test_silent_security_and_boundary_bundle.py`
- `tests/test_global_statement_budget.py`
- plus Open-Prep/Artifacts-Dateien aus den entsprechenden Commits

## Validierung heute

- Health-/Robustheits-Tests erfolgreich (u. a. `idle_market_closed`-Verhalten).
- Security/Ledger-relevante Tests auf Stand gebracht (Line-Pins).
- `tests/test_smc_live_overlay_metrics_endpoint.py`: **7 passed**.
- Grafana API Sync erfolgreich:
  - Dashboard upsert: `smc-live-overlay-v1`
  - Alert-Rules upsert: `live-overlay-critical` + `live-overlay-warning` (Konfliktfrei via Update bei bestehenden UIDs)

## Operative Hinweise

- Grafana API-Key ist lokal via macOS Keychain hinterlegt (`service: skipp.grafana.api`).
- Für automatischen lokalen Push nach Grafana kann der Key per
  `security find-generic-password -s skipp.grafana.api -a "$USER" -w`
  in die Umgebung geladen werden (ohne Secret im Repo zu speichern).

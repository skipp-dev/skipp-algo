# Change Log — 2026-06-21

## Überblick

Diese Notiz fasst die Änderungen vom **21.06.2026** zusammen (inkl. gemergter PRs auf `main` und branch-seitiger Nacharbeiten für PR #2875).

## Änderungen (konsolidiert)

### 1) Live-Overlay Runtime / API

- Feed-Lifecycle serialisiert (`_lifecycle_lock`) zur Vermeidung von Start/Stop-Races.
- `smc_live` kann für nicht-`5m`-Timeframes on-demand aus 1m-Bars aggregieren.
- Unerwartete `smc_live`-Fehler werden als 500 zurückgegeben und mit
  `live_overlay.smc_live_errors.total` observiert.

### 2) Security & Metrics Auth

- Bevorzugter Scrape-Pfad: `GET /metrics` via **Basic Auth**
  (Passwort = `OVERLAY_SECRET_TOKEN`).
- Legacy-Pfad `/{token}/metrics` bleibt kompatibel.
- HMAC/Line-Pin Guard-Tests wurden auf aktuelle Callsite-Positionen synchronisiert.

### 3) Observability / SLO

- Monitoring-/SLO-Erweiterungen in `observability.py`, `metrics.py`, Grafana Dashboard:
  - Dynamic stale-budget denominator (`live_overlay_max_stale_seconds`)
  - Histogram-Bucket-Härtung (`metric_histogram_ms`)
  - Zusätzliche Latenz-/Stale-/Health-Signale
- Review-Follow-ups umgesetzt (inkl. Regressionstests).

### 4) Cache / Robustness / Config

- Overlay-Payloads werden auf Read deep-copied (Mutation-Schutz).
- `LOG_LEVEL` validiert, mit fallback auf `info` bei ungültigen Werten.
- Robustness-/Boundary-Tests entlang neuer Runtime-Semantik aktualisiert.

### 5) Dependencies

- `databento` auf `0.79.0` gepinnt + Contract-Test abgesichert.

## Relevante PRs / Commits (Auszug)

- `#2866` fix(live-overlay): lifecycle locking
- `#2867` fix(alloy/metrics auth): Basic Auth für `/metrics`
- `#2869` feat(compute): timeframe aggregation for overlay payloads
- `#2870` fix(cache): deep-copy overlay payloads on read
- `#2872` feat(observability): monitoring panels
- `#2873` fix(config): LOG_LEVEL validation + reconnect tests
- `#2874` fix(main): catch unexpected `smc_live` failures
- `#2875` feat/fix(monitoring): SLO follow-ups, histogram/stale-budget review fixes

## Validierung

- Targeted Lint/Test-Läufe für die betroffenen Dateien/Suiten wurden grün ausgeführt
  (u. a. `test_smc_live_overlay_metrics.py`, `test_smc_live_overlay_observability.py`,
  `test_hmac_auth_zero_surface.py`).

---

## Nachtrag — 2026-06-23 (PR #2909 Audit-Follow-ups)

### Architektur / Runtime-Härtung

- Snapshot-URL-Validierung in `compute.py` zentralisiert
  (`_validate_https_url`): alle runtime `*_URL`-Fetcher sind konsistent
  HTTPS-only.
- Write-through-Persistenz weiter gehärtet: temporäre Snapshot-Dateien enthalten
  jetzt `pid + thread_id + time_ns` zur besseren Kollisionsvermeidung.
- `GITHUB_WORKFLOW_MONITOR_REPO` wird strenger validiert; ungültige Werte fallen
  auf `skippALGO/skipp-algo` zurück.

### Integrations-/Bridge-Details

- GitHub Workflow Bridge dokumentiert als bewusstes "first-page is enough"
  Polling für Latest-Run-Status; URL-Segmente werden defensiv percent-encoded.
- `publish_signals_snapshot.py` gibt bei unerwartetem initialen Fetch-Fehler
  (außer "remote ref not found" beim First-Publish) eine redacted Warnung aus,
  statt stillschweigend fortzufahren.

### Observability-Dokumentation

- Dynamic metric names bei Provider-/Signal-Serien sind als beabsichtigtes
  Design festgehalten (Grafana arbeitet mit `__name__=~`-Regex-Matchern).

### CI/Workflow-Hygiene

- `smc-measurement-benchmark-rolling.yml` räumt temporäre
  `structure_export_*.json` innerhalb des Steps auf.

# Live Overlay Telemetrie — Umsetzungsplan

Status: Vorschlag · Datum: 2026-06-19 · Branch-Kontext: `fix/live-overlay-post-merge-bugs` (PR #2860)

## 1. Ausgangslage

Die Telemetrie wird heute **erzeugt, aber nicht operativ konsumiert**.

Erzeugt:

- `services/live_overlay_daemon/observability.py` — `metric_counter`, `metric_gauge`,
  `metric_timing_ms`, `trace_event`, `trace_span`, `audit_event`. Transport = strukturierte
  Log-Zeilen (`metric kind=... name=live_overlay.* ...`). Counter halten zusätzlich einen
  In-Process-Stand (`_counters` + `_counter_lock`).
- `main.py` — Lifespan-Span, `/health` Counter/Audit, `/smc_live` Counter/Audit
  (auth denied, bad tf, cache miss, success). `_VALID_TFS = {5m, 15m, 1H, 4H}`.
- `compute.py` — `run_full_compute_cycle` / `run_flow_patch_cycle` mit Trace-Span,
  Gauges (`overlay_symbols`, `flow_patch_symbols`), Countern, Audit.
- `feed.py` — `metrics_snapshot()` mit `reconnect_attempts`, `bento_errors`,
  `unexpected_errors`, `circuit_breakers`, `partial_restarts`. Diese landen im `/health` JSON
  unter `feed_metrics`.

Konsumiert:

- `/health` → Railway Healthcheck + UptimeRobot (nur binär up/down).
- Strukturierte Logs → Railway Logs + Mensch + Tests (`caplog`).
- Pine → nur `/{token}/smc_live`, keine Telemetrie.

Fehlt vollständig: Prometheus, Grafana, Datadog, OpenTelemetry, App Insights, Log-Drain,
Alert-Regeln, semantischer `/health`-Monitor.

Deploy-Fakten: Railway, Dockerfile-Build, **ein** uvicorn-Worker (`--workers 1`),
`healthcheckPath = /health`, Restart `ON_FAILURE` (max 3). Der Single-Worker ist wichtig:
In-Process-Counter sind damit konsistent und können direkt über eine `/metrics`-Route
exponiert werden — kein Multiprocess-Prometheus-Setup nötig.

## 2. Zielbild

Telemetrie wird auf Railway **maschinell konsumiert**:

1. `/metrics` (Prometheus-Format) als kanonischer Pull-Endpoint für Zahlen.
2. Strukturierte Logs bleiben für Trace/Audit/Debug — optional via Railway Log-Drain.
3. Ein **semantischer Health-Watcher** alarmiert auf Basis von `/health` + `/metrics`.
4. Visualisierung über Grafana (Railway-gehostet oder Grafana Cloud Free).

Leitprinzip: **Railway bleibt die externe Lösung.** Alle Bausteine laufen als Railway-Services
oder werden von Railway gescraped/gedrained.

## 3. Architektur (Railway-nativ)

```mermaid
flowchart LR
  subgraph Railway Project
    APP[smc-live-overlay\n/health + /metrics] -->|scrape /metrics| PROM[Prometheus service]
    APP -->|structured logs| LOGS[(Railway Logs)]
    PROM --> GRAF[Grafana service]
    PROM --> ALERT[Alertmanager\noder Grafana Alerting]
    WATCH[health-watcher\n(Railway cron/worker)] -->|GET /health| APP
    WATCH -->|alert| NOTIFY[(Slack/Email/Telegram)]
    ALERT --> NOTIFY
  end
  LOGS -. optional log drain .-> EXT[(extern: Better Stack/Datadog)]
```

Begründung der Optionswahl:

- **Prometheus `/metrics` Pull** ist die geringste Reibung bei Single-Worker und passt zu den
  bereits vorhandenen In-Process-Countern.
- **Health-Watcher** deckt semantische Zustände ab, die reine Zahlen nicht sauber abbilden
  (`overlay_fresh`, `workers_healthy`, `worker_liveness`).
- **Grafana** liefert Dashboards ohne Eigenbau.
- **Log-Drain** ist optional und erst in einer späteren Phase nötig.

## 4. Phasenplan

### Phase 0 — Hygiene & Doku (Vorbereitung)

Ziel: Saubere Basis, keine Funktionsänderung am Verhalten.

- `feed.py`: Metrics-Implementierung vereinheitlicht; `metrics_snapshot()` liest jetzt aus der
  einen thread-sicheren Counter-Quelle.
- README/Ops-Doku korrigieren: `/health`-Payload vollständig dokumentieren, `tf`-Contract auf
  `5m,15m,1H,4H` (kein `1D`), strukturierte Telemetrie erklären.
- Akzeptanz: bestehende Tests grün, `metrics_snapshot()` unverändert im Verhalten, README
  spiegelt echten Payload + TF-Contract.

Aufwand: klein. Risiko: niedrig.

### Phase 1 — `/metrics` Endpoint (Prometheus-Format)

Ziel: Zahlen pull-bar machen, ohne neue schwere Dependency.

- Neue token-geschützte Route `GET /{token}/metrics` in `main.py`, die ausgibt:
  - Counter aus `observability._counters` (bereits vorhanden) im Prometheus-Textformat.
  - Feed-Counter aus `feed.metrics_snapshot()`.
  - Health-abgeleitete Gauges: `overlay_fresh`, `workers_healthy`, `last_bar_age_secs`,
    `overlay_age_secs`, `uptime_secs`, `overlay_symbols`, `bar_count`.
- Umsetzungsvariante:
  - **A (empfohlen):** kleiner eigener Renderer (kein `prometheus_client`), da Single-Worker
    und die Counter bereits in-process vorliegen — minimale Dependency-Fläche.
  - **B:** `prometheus_client` + `generate_latest()`; mehr Komfort, aber neue Dependency und
    Registry-Verdrahtung mit den vorhandenen Countern.
- Name-Mapping: `live_overlay.smc_live_requests.total` → `live_overlay_smc_live_requests_total`
  (Punkte → Unterstriche, Prometheus-Konvention). Mapping zentral kapseln.
- Auth: `/{token}/metrics` nutzt denselben URL-Token wie `/smc_live`; Alloy soll den Endpoint nur
  über Railway Private Networking scrapen.
- Tests: Endpoint liefert gültiges Prometheus-Textformat; Counter-Werte spiegeln Aktionen
  (z. B. nach einem `/smc_live`-Hit steigt `..._requests_total`).
- Akzeptanz: `curl /metrics` liefert parsebares Format; ausgewählte Kern-Counter vorhanden.

Aufwand: mittel. Risiko: niedrig–mittel (Auth/Exposure sauber lösen).

### Phase 2 — Counter-Lücken schließen (Producer-Härtung)

Ziel: Die Daten, die ein Alert braucht, müssen auch entstehen.

- Feed-Counter zusätzlich als strukturierte Metrics emittieren, damit sie auch im Log/Drain
  sichtbar sind: `live_overlay.feed.reconnect_attempts`, `...bento_errors`,
  `...unexpected_errors`, `...circuit_breakers`, `...partial_restarts`.
- Error-Counter in den Refresh-Loops ergänzen (`run_full_compute_cycle` /
  `run_flow_patch_cycle` Loop-Ebene): `live_overlay.full_compute_cycle.errors`,
  `live_overlay.flow_patch_cycle.errors` (heute wird Exception nur per `logger.error` geloggt).
- Akzeptanz: Tests pinnen, dass Fehlerpfade die Error-Counter erhöhen.

Aufwand: klein–mittel. Risiko: niedrig.

### Phase 3 — Prometheus + Grafana als Railway-Services

Ziel: Scrapen, speichern, visualisieren — innerhalb Railway.

- Prometheus als eigener Railway-Service (Docker-Image `prom/prometheus`), `scrape_config`
  zeigt über Railway Private Networking auf `smc-live-overlay:$PORT/metrics`,
  `scrape_interval: 30s`.
- Persistenz: Railway Volume für Prometheus TSDB (Retention z. B. 15 Tage).
- Grafana als Railway-Service (`grafana/grafana`) mit Prometheus-Datasource.
  Alternative: Grafana Cloud Free (dann Remote-Write/Scrape von Railway aus).
- Start-Dashboard:
  - Request-Rate `/smc_live`, Fehlerquote (auth denied, bad tf, cache miss).
  - Compute-/Flow-Zyklus-Dauer (`*.duration_ms`).
  - `overlay_symbols`, `flow_patch_symbols`, `overlay_age_secs`, `last_bar_age_secs`.
  - Feed-Counter Trends (`bento_errors`, `reconnect_attempts`, `circuit_breakers`).
- Akzeptanz: Dashboard zeigt Live-Daten aus Produktion.

Aufwand: mittel. Risiko: mittel (Networking, Volumes, Service-Discovery in Railway).

### Phase 4 — Alerting

Ziel: Vom Dashboard zum Pager.

- Variante A: **Grafana Alerting** (kein separater Alertmanager).
- Variante B: Prometheus + Alertmanager (mehr Kontrolle).
- Kern-Alerts:
  - `status != ok` länger als 5 min.
  - `overlay_fresh == 0` (false).
  - `workers_healthy == 0` (false) oder einzelner Worker in `worker_liveness` tot.
  - `feed_metrics.circuit_breakers > 0`.
  - `rate(bento_errors)` / `rate(unexpected_errors)` über Schwellwert.
  - Compute-Zyklus-Dauer p95 über Schwellwert.
  - `overlay_symbols == 0` nach Warmup.
- Notification-Channel: Slack/Telegram/Email (Secrets in Railway).
- Akzeptanz: künstlich ausgelöster Fehlerzustand erzeugt nachweislich einen Alert.

Aufwand: mittel. Risiko: mittel (Alert-Tuning gegen Flapping).

### Phase 5 — Semantischer Health-Watcher (ergänzend)

Ziel: Zustände abdecken, die als Gauges unscharf sind, plus Sofort-Alarm unabhängig von
Prometheus-Verfügbarkeit.

- Kleiner Railway-Cron/Worker, der periodisch `GET /health` auswertet und bei Verletzung der
  obigen semantischen Regeln direkt benachrichtigt.
- Bewusst redundant zu Phase 4 als „dead man's switch“, falls Prometheus/Grafana selbst ausfällt.
- Akzeptanz: Watcher meldet, wenn `/health` degraded ist, auch wenn Prometheus down ist.

Aufwand: klein–mittel. Risiko: niedrig.

### Phase 6 — Optionaler Log-Drain

Ziel: Trace/Audit-Logs extern durchsuchbar/aufbewahrbar.

- Railway Log-Drain → Better Stack / Datadog / Loki.
- Erst sinnvoll, wenn strukturierte Trace/Audit-Auswertung über reine Metrics hinaus gebraucht
  wird (z. B. Incident-Forensik, Audit-Retention).
- Akzeptanz: Audit-/Trace-Events sind extern abfragbar.

Aufwand: klein (Config) + ggf. externe Kosten. Risiko: niedrig.

## 5. Empfohlene Reihenfolge & Schnitt in PRs

1. PR A — Phase 0 (Hygiene + README/TF-Contract). Klein, schnell mergebar.
2. PR B — Phase 1 + Phase 2 (`/metrics` + Counter-Lücken). Liefert sofort pull-bare Daten.
3. PR C — Phase 3 (Prometheus + Grafana Railway-Services + Dashboard-as-Code).
4. PR D — Phase 4 (Alerts) und Phase 5 (Health-Watcher).
5. PR E — Phase 6 (Log-Drain), nur bei Bedarf.

## 6. Risiken & Entscheidungen

- **`/metrics` Exposure:** nicht öffentlich; Railway Private Networking oder Token-Schutz.
- **Single-Worker-Annahme:** Wenn Worker später > 1 werden, brauchen In-Process-Counter
  Multiprocess-Prometheus oder Pushgateway. Heute (`--workers 1`) nicht nötig — als Annahme
  dokumentieren.
- **Dependency-Fläche:** Variante „eigener Prometheus-Renderer“ minimiert neue Libs; falls
  `prometheus_client` gewünscht, bewusst entscheiden.
- **Alert-Flapping:** sinnvolle `for:`-Dauern und Hysterese pro Alert.
- **Kosten:** zusätzliche Railway-Services (Prometheus/Grafana) + Volumes verursachen Kosten;
  Grafana Cloud Free als Alternative prüfen.

## 7. Definition of Done (Gesamt)

- `/metrics` liefert valide Prometheus-Daten (intern erreichbar, geschützt).
- Feed- und Compute-Fehler erzeugen dedizierte Counter.
- Prometheus scrapt Produktion; Grafana-Dashboard zeigt Kernmetriken.
- Alerts feuern bei degradiertem Zustand; Health-Watcher als Backup aktiv.
- README/Ops-Doku aktuell (Payload, TF-Contract, Telemetrie, Runbook-Verweise).
- Tests decken Endpoint, Name-Mapping und Fehler-Counter ab.

# Live Overlay — Infrastruktur-Betriebshandbuch

> **Scope:** Grafana, Railway, UptimeRobot und GitHub-Workflow-Monitoring für den
> `live_overlay_daemon`-Service. Beschreibt Authentication, Publish-Workflows und
> wie die drei Plattformen miteinander und mit dem Repository interagieren.

---

## Inhaltsverzeichnis

1. [Architekturüberblick](#1-architekturüberblick)
2. [Railway — Deployment & Betrieb](#2-railway--deployment--betrieb)
3. [Grafana — Dashboard & Alerts editieren und publishen](#3-grafana--dashboard--alerts-editieren-und-publishen)
4. [UptimeRobot — Monitoring-Bridge](#4-uptimerobot--monitoring-bridge)
5. [GitHub-Workflow-Bridge](#5-github-workflow-bridge)
6. [Plattform-Interaktionsmatrix](#6-plattform-interaktionsmatrix)
7. [Credentials-Übersicht](#7-credentials-übersicht)
8. [Schnellreferenz: häufige Operationen](#8-schnellreferenz-häufige-operationen)

---

## 1. Architekturüberblick

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Railway (Production)                                            │
│                                                                                              │
│  ┌───────────────────────────────┐        ┌─────────────────────────────────────────────┐   │
│  │   smc-signals-producer        │        │   smc-live-overlay                          │   │
│  │   (open_prep/realtime_signals)│        │   (live_overlay_daemon)                     │   │
│  │                               │        │                                             │   │
│  │  Input: FMP_API_KEY           │        │  Inputs:                                    │   │
│  │  Input: latest_open_prep_run  │        │  • Databento live feed                      │   │
│  │                               │        │  • *_SNAPSHOT_URL / *_SNAPSHOT_PATH        │   │
│  │  Endpoints:                   │        │  • smc-signals-producer /signals (planned)  │   │
│  │  • /signals   ────────────────┼────────┼─► (A0/A1 signal JSON)                       │   │
│  │  • /metrics                   │        │  • UptimeRobot API                          │   │
│  │  • /healthz                   │        │  • GitHub API                               │   │
│  │  • /telemetry.json            │        │  • Railway API                              │   │
│  └──────────┬────────────────────┘        │                                             │   │
│             │                             │  Endpoints:                                 │   │
│             │                             │  • /health  → Railway healthcheck           │   │
│             │                             │  • /metrics → metrics-collector (Alloy)     │   │
│             │                             │  • /smc_live → Pine Script consumer         │   │
│             │                             └─────────────────────┬───────────────────────┘   │
│             │                                                   │                         │
│             │                    ┌──────────────────────────────┘                         │
│             │                    │                                                        │
│             │                    ▼                                                        │
│             │         ┌─────────────────────┐                                             │
│             └────────►│  metrics-collector  │                                             │
│                       │  (Grafana Alloy)    │                                             │
│                       │                     │                                             │
│                       │  scrape /metrics    │                                             │
│                       │  every 30 s         │                                             │
│                       └──────────┬──────────┘                                             │
│                                  │                                                        │
└──────────────────────────────────┼────────────────────────────────────────────────────────┘
                                   │
                                   │  Prometheus remote-write
                                   ▼
                        ┌───────────────────────┐
                        │   Grafana Cloud        │
                        │   (Monitoring only)    │
                        │                        │
                        │  ► Prometheus TSDB     │
                        │  ► Dashboards/Alerts   │
                        └───────────────────────┘
```

**Datenfluss:**
1. `smc-signals-producer` pollt FMP und berechnet A0/A1-Breakout-Signale. Er soll diese
   über `/signals` direkt an `smc-live-overlay` liefern (heute noch nicht implementiert —
   siehe `docs/LIVE_OVERLAY_SIGNALS_ARCHITECTURE_GAP.md`).
2. `smc-live-overlay` konsumiert Databento-Livedaten, Snapshot-Dateien (News/Experiment/
   TradingView), UptimeRobot, GitHub-API, Railway-API und (geplant) die Signale vom
   Producer. Er exponiert alles als Prometheus-Metriken unter `/metrics`.
3. Grafana Alloy (Railway-Service `metrics-collector`) scraped `/metrics` beider Services
   alle 30 s und schreibt die Zeitreihen nach Grafana Cloud.
4. Grafana Cloud dient ausschließlich dem Monitoring — nicht der Datenweiterleitung an
   den Overlay-Daemon oder Pine.
5. Pine Script ist der Endkonsument von `/smc_live`.

---

## 2. Railway — Deployment & Betrieb

### Service-Konfiguration

| Datei | Zweck |
|-------|-------|
| `services/live_overlay_daemon/railway.toml` | Build- und Deploy-Config |
| `services/live_overlay_daemon/Dockerfile` | Container-Image |
| `services/live_overlay_daemon/infra/alloy/config.alloy` | Alloy-Config des `metrics-collector` |

**`railway.toml` (`live_overlay_daemon`):**
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "services/live_overlay_daemon/Dockerfile"

[deploy]
startCommand = "uvicorn services.live_overlay_daemon.main:app \
  --host 0.0.0.0 --port $PORT --workers 1 --http h11 --loop asyncio"
healthcheckPath = "/health"
healthcheckTimeout = 60
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

Railway deployed automatisch, sobald ein Commit auf dem verknüpften Branch landet.

### Manuell deployen / testen

```bash
# Status und Logs
railway status -s live_overlay_daemon
railway logs -s live_overlay_daemon

# Einmalig deployen (ohne Push)
railway up -s live_overlay_daemon

# Kommando im Kontext des Services ausführen (mit dessen Env-Vars)
railway run -s live_overlay_daemon python -c "import os; print(os.environ.get('PORT'))"

# /health prüfen
curl https://liveoverlaydaemon-production.up.railway.app/health

# /ready prüfen (detaillierter Status)
curl https://liveoverlaydaemon-production.up.railway.app/ready
```

### Umgebungsvariablen (Railway-Dashboard setzen)

| Variable | Service | Pflicht | Beschreibung |
|----------|---------|---------|--------------|
| `DATABENTO_API_KEY` | live_overlay_daemon | ✅ | Databento API key (Unlimited) |
| `OVERLAY_SECRET_TOKEN` | live_overlay_daemon | ✅ | Shared Secret für `/metrics` Basic Auth und `/smc_live` URL |
| `PORT` | live_overlay_daemon | ✅ | von Railway injiziert |
| `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` | live_overlay_daemon | optional | `1` in Production, wenn TradingView/Pine-Traffic während US Market Open erwartet wird; default `0` lässt den First-Zero-Traffic-Alert deaktiviert |
| `UPTIMEROBOT_API_KEY` | live_overlay_daemon | optional | API-Key für UptimeRobot-Bridge |
| `UPTIMEROBOT_MONITOR_IDS` | live_overlay_daemon | optional | Kommagetrennte Monitor-IDs; Production-Allowlist: `803309701,803341452,803343155,803343156,803362511` |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | live_overlay_daemon | optional | GitHub PAT für Workflow-Bridge |
| `GITHUB_WORKFLOW_MONITOR_REPO` | live_overlay_daemon | optional | `owner/repo`, default `skippALGO/skipp-algo` |
| `NEWS_SNAPSHOT_PATH` | live_overlay_daemon | optional | Pfad zum News-Snapshot-JSON |
| `OVERLAY_SERVICE_URL` | metrics-collector | ✅ | Scrape target ohne Scheme, aktuell `liveoverlaydaemon-production.up.railway.app`; bei Private Networking `liveoverlaydaemon.railway.internal:<PORT>` nach Runtime-Port-Verifikation |
| `SIGNALS_SERVICE_URL` | live_overlay_daemon, metrics-collector | ✅ | `smc-signals-producer.railway.internal:PORT` — internal host:port of the signals producer; Alloy scrapes `/metrics`, live_overlay_daemon fetches `/signals` |
| `GRAFANA_CLOUD_PROM_URL` | metrics-collector | ✅ | Grafana Cloud Remote-Write-URL |
| `GRAFANA_CLOUD_USER` | metrics-collector | ✅ | Grafana Cloud Stack-ID (numerisch) |
| `GRAFANA_CLOUD_API_KEY` | metrics-collector | ✅ | Grafana Cloud API-Key (MetricsPublisher) |
| `OVERLAY_SECRET_TOKEN` | metrics-collector | ✅ | gleicher Token wie in live_overlay_daemon |
| `SIGNALS_INTERNAL_TOKEN` | live_overlay_daemon, metrics-collector, smc-signals-producer | ✅ | Shared-Secret für `/signals`- und `/metrics`-Endpoint (Bearer-Token); live_overlay_daemon und Alloy senden diesen Token beim Aufruf |

### Alloy-Konfiguration aktualisieren

Die Datei `services/live_overlay_daemon/infra/alloy/config.alloy` ist **Quell der Wahrheit**.
Änderungen wirken nach dem nächsten Deploy des `metrics-collector`-Services:

```bash
# Lokal validieren (Alloy CLI muss installiert sein)
alloy fmt services/live_overlay_daemon/infra/alloy/config.alloy

# Pushen → Railway deployed metrics-collector automatisch
git push origin <branch>
```

---

## 3. Grafana — Dashboard & Alerts editieren und publishen

### Übersicht

| Ressource | Datei im Repo | Live-Referenz |
|-----------|---------------|---------------|
| Dashboard | `services/live_overlay_daemon/infra/grafana/dashboard.json` | UID `smc-live-overlay-v1` |
| Alert-Rules | `services/live_overlay_daemon/infra/grafana/alert-rules.yaml` | Ordner `SMC Live Overlay` |

**Regel:** Das Repository ist die Quelle der Wahrheit. Änderungen werden immer
zuerst in den Repo-Dateien gemacht und dann via API auf Grafana Cloud gepusht —
nicht umgekehrt.

### Authentication

Zwei Keychain-Einträge auf dem Entwickler-Mac:

| Keychain-Service | Kontext | Befehl |
|------------------|---------|--------|
| `skipp.grafana.api` | Dashboard upsert, Alert-Rules, allgemeine API | `security find-generic-password -s skipp.grafana.api -a "$USER" -w` |
| `skipp.grafana.dashboard` | (Legacy / alternativ) | `security find-generic-password -s skipp.grafana.dashboard -a "$USER" -w` |

Der Token wird als `Bearer`-Header gesetzt: `Authorization: Bearer <token>`.

Der Grafana-API-Token benötigt mindestens:
- Role `Editor` (Dashboard upsert, Alert-Rule-Import)
- Scope `MetricsPublisher` wird **nicht** benötigt (nur Alloy braucht das)

### Dashboard editieren und publishen

**Workflow:**

```
1. dashboard.json lokal bearbeiten
2. JSON-Validierung + Dry-Run des Publishers
3. Via scripts/publish_overlay_dashboard.py auf Cloud pushen (upsert)
4. Live-Verifikation
5. git add / commit / push
```

**Schritt-für-Schritt:**

```bash
# Dry-run (kompakte Zusammenfassung, ohne Netzwerkaufruf)
python3 scripts/publish_overlay_dashboard.py --dry-run

# Optional: Dry-run mit vollständigem Payload-JSON
python3 scripts/publish_overlay_dashboard.py --dry-run --dry-run-full

# Publish (primär: POST /api/v1/dashboards, Fallback: /api/dashboards/db bei 404)
python3 scripts/publish_overlay_dashboard.py --message "chore: sync from repo"
```

**Token-Auflösung (publish_overlay_dashboard.py):**

1. `--token`
2. `$<--token-env>` (Default: `GRAFANA_API_TOKEN`)
3. `$GRAFANA_API_TOKEN` (nur wenn `--token-env` auf eine andere Variable zeigt)
4. `$GRAFANA_TOKEN`
5. macOS Keychain (`skipp.grafana.api`), außer bei `--no-keychain`

**Endpoint-Verhalten:**

- Primär: `POST /api/v1/dashboards`
- Wenn Grafana Cloud dafür `404 Not found` liefert: automatischer Fallback auf
  `POST /api/dashboards/db` mit Legacy-Wrapper (`dashboard`, `overwrite`, `message`)

Beispiele:

```bash
# CI/Agent-Sandbox ohne Keychain
GRAFANA_API_TOKEN=... python3 scripts/publish_overlay_dashboard.py --no-keychain --message "ci sync"

# Custom env var first
CUSTOM_GRAFANA_TOKEN=... python3 scripts/publish_overlay_dashboard.py --token-env CUSTOM_GRAFANA_TOKEN --message "custom token env"
```

**Live-Version verifizieren:**

```python
python3 - <<'PY'
import json, os, urllib.request
HOST = "bronzeporridge977.grafana.net"
TOKEN = os.popen('security find-generic-password -s skipp.grafana.api -a "$USER" -w').read().strip()
req = urllib.request.Request(
    f"https://{HOST}/api/dashboards/uid/smc-live-overlay-v1",
    headers={"Authorization": f"Bearer {TOKEN}"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    live = json.loads(r.read())["dashboard"]
print("live version=", live.get("version"), "panels=", len(live.get("panels", [])))
PY
```

**Live-Version in Repo zurück-synchronisieren** (wenn Grafana-UI genutzt wurde):

```python
python3 - <<'PY'
import json, os, urllib.request
from pathlib import Path
HOST = "bronzeporridge977.grafana.net"
TOKEN = os.popen('security find-generic-password -s skipp.grafana.api -a "$USER" -w').read().strip()
req = urllib.request.Request(
    f"https://{HOST}/api/dashboards/uid/smc-live-overlay-v1",
    headers={"Authorization": f"Bearer {TOKEN}"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    dash = json.loads(r.read())["dashboard"]
# Server-verwaltete Felder entfernen, damit der nächste Publish sauber ist.
meta = dash.setdefault("metadata", {})
for key in ("resourceVersion", "generation", "creationTimestamp", "uid"):
    meta.pop(key, None)
Path("services/live_overlay_daemon/infra/grafana/dashboard.json").write_text(
    json.dumps(dash, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print("saved panels=", len(dash.get("spec", {}).get("elements", {})))
PY
```

> ⚠️ **Nach einem UI-Edit immer pull-back + commit** — sonst driftet das Repo
> hinter die Live-Version und der nächste Repo-Push überschreibt UI-Änderungen.

### Alert-Rules verwalten

Alert-Rules sind in `infra/grafana/alert-rules.yaml` im Grafana-Provisioning-Format
(Version `v1`) hinterlegt. Sie werden **nicht** automatisch provisioniert — es gibt
keinen Alloy- oder File-Provisioner für Alert-Rules im aktuellen Setup.

**Manuell importieren:**

1. Grafana Cloud UI öffnen: `https://bronzeporridge977.grafana.net`
2. Navigation: `Alerting → Alert rules → New alert rule` (oder `Import`)
3. YAML-Inhalt aus `alert-rules.yaml` einfügen

**Oder via API (programmatisch):**

```bash
TOKEN=$(security find-generic-password -s skipp.grafana.api -a "$USER" -w)
HOST="bronzeporridge977.grafana.net"

# Einzelne Gruppe importieren
curl -sS -X POST "https://$HOST/api/ruler/grafana/api/v1/rules/SMC%20Live%20Overlay" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @services/live_overlay_daemon/infra/grafana/alert-rules.yaml
```

**Bestehende Gruppen auflisten:**

```bash
TOKEN=$(security find-generic-password -s skipp.grafana.api -a "$USER" -w)
curl -sS "https://bronzeporridge977.grafana.net/api/ruler/grafana/api/v1/rules" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -40
```

### Dashboard-JSON Konventionen

- `uid` ist `smc-live-overlay-v1` — nie ändern.
- Das `id`-Feld wird beim Upsert ignoriert (Grafana vergibt interne IDs selbst).
- `version` im JSON wird beim Upsert ebenfalls ignoriert — Grafana inkrementiert
  intern.
- Panels, die nur bei offenem Markt sinnvoll sind, werden mit
  `and on(job) (live_overlay_market_open{job="live_overlay"} == 1)` gegated und
  tragen `noValue: "MARKET CLOSED"`.
- Der Market-Session-Banner (Panel `Market Session Banner`) nutzt den Ausdruck:
  ```
  ((2 * (max(live_overlay_market_open) or vector(0)))
   + (clamp_max(count(live_overlay_uptime_seconds), 1) or vector(0)))
  ```
  mit 4-State-Mapping: `0=SERVICE DOWN`, `1=MARKET CLOSED`, `2=OPEN/TELEMETRY MISSING`, `3=MARKET OPEN`.

---

## 4. UptimeRobot — Monitoring-Bridge

### Konzept

UptimeRobot überwacht externe Endpunkte (URLs, Ping) unabhängig von der eigenen
Infrastruktur. Die Bridge importiert den Status in den `live_overlay_daemon`, der
ihn als Prometheus-Gauge exportiert — so landen UptimeRobot-Daten im gleichen
Grafana-Dashboard wie alle anderen Metriken.

### Implementierung

| Datei | Funktion |
|-------|----------|
| `services/live_overlay_daemon/uptimerobot_bridge.py` | API-Polling, in-process Cache |
| `services/live_overlay_daemon/config.py` | Env-Var-Accessors |
| `services/live_overlay_daemon/metrics.py` | Gauge-Export im `/metrics`-Handler |

**Ablauf:**
```
Prometheus-Scrape (/metrics)
  → metrics.render_metrics()
    → uptimerobot_bridge.snapshot()      # TTL-gecacht (default 30 s)
      → UptimeRobot API v2 /getMonitors  # nur wenn Cache abgelaufen
```

### Authentication

- API-Key in Railway-Variable `UPTIMEROBOT_API_KEY` (Read-Only-Key ausreichend).
- Production setzt `UPTIMEROBOT_MONITOR_IDS` auf
  `803309701,803341452,803343155,803343156,803362511`, damit neue
  UptimeRobot-Monitore nicht automatisch die Bridge-Aggregate verändern.
- Kein Outbound-Request wenn `UPTIMEROBOT_API_KEY` fehlt → Bridge-Metriken zeigen
  `enabled=0`, kein Fehler.

### UptimeRobot-API-Aufruf (intern)

```
POST https://api.uptimerobot.com/v2/getMonitors
Content-Type: application/x-www-form-urlencoded

api_key=<UPTIMEROBOT_API_KEY>
format=json
logs=0
response_times=1
response_times_limit=1
monitors=<optional kommagetrennte IDs>
```

### Exportierte Prometheus-Metriken

```
live_overlay_uptimerobot_bridge_enabled       # 1 = API-Key gesetzt, 0 = deaktiviert
live_overlay_uptimerobot_bridge_ok            # 1 = letzter Fetch erfolgreich
live_overlay_uptimerobot_bridge_fetched_at    # Unix-Timestamp letzter Fetch
live_overlay_uptimerobot_monitors_total
live_overlay_uptimerobot_monitors_up
live_overlay_uptimerobot_monitors_down
live_overlay_uptimerobot_monitors_paused
live_overlay_uptimerobot_monitors_unknown
live_overlay_uptimerobot_avg_response_time_ms
live_overlay_uptimerobot_monitor_<id>_up       # 1 pro Monitor
live_overlay_uptimerobot_monitor_<id>_response_time_ms
```

### UptimeRobot-Konfiguration (Dashboard selbst)

UptimeRobot wird direkt über `https://uptimerobot.com` verwaltet. Dort werden
Monitore erstellt, Pausen gesetzt und Alertkontakte konfiguriert.
Das Repository hat **keinen** schreibenden Einfluss auf UptimeRobot-Monitore —
der Datenfluss ist immer: UptimeRobot → Bridge → Grafana (nur lesend).

Production erwartet exakt diese fünf Monitor-IDs in `UPTIMEROBOT_MONITOR_IDS`:

```env
UPTIMEROBOT_MONITOR_IDS=803309701,803341452,803343155,803343156,803362511
```

Grafana schützt die Konfiguration mit zwei Alerts:

```promql
(live_overlay_uptimerobot_bridge_enabled{job="live_overlay"} == 1)
* on(job)
(live_overlay_uptimerobot_monitors_total{job="live_overlay"} != bool 5)
```

```promql
(live_overlay_uptimerobot_bridge_enabled{job="live_overlay"} == 1)
* on(job)
(live_overlay_uptimerobot_monitors_down_total{job="live_overlay"} > bool 0)
```

---

## 5. GitHub-Workflow-Bridge

Analog zur UptimeRobot-Bridge lädt die GitHub-Workflow-Bridge den Status der
CI-Workflows und exportiert ihn als Prometheus-Gauges.

### Env-Vars

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | — | GitHub PAT mit `actions:read` |
| `GITHUB_WORKFLOW_MONITOR_REPO` | `skippALGO/skipp-algo` | `owner/repo` |
| `GITHUB_WORKFLOW_MONITOR_IDS` | — | Kommagetrennte Workflow-IDs |
| `GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS` | 5 | HTTP-Timeout |
| `GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS` | 30 | Cache-TTL in Sekunden |

---

## 6. Plattform-Interaktionsmatrix

| Von → Nach | Protokoll | Auth | Richtung | Trigger |
|------------|-----------|------|----------|---------|
| Grafana Alloy → `smc-live-overlay /metrics` | HTTP Basic | `metrics` / `OVERLAY_SECRET_TOKEN` | Pull | alle 30 s |
| Grafana Alloy → `smc-signals-producer /metrics` | HTTP Bearer | `SIGNALS_INTERNAL_TOKEN` (same token shared with metrics-collector) | Pull | alle 30 s |
| Grafana Alloy → Alloy self `127.0.0.1:12345/metrics` | HTTP | keine (loopback) | Pull | alle 30 s |
| Grafana Alloy → Grafana Cloud Prometheus | HTTPS Basic | `GRAFANA_CLOUD_USER` / `GRAFANA_CLOUD_API_KEY` | Push (remote-write) | kontinuierlich |
| `smc-live-overlay` → UptimeRobot API | HTTPS POST | `UPTIMEROBOT_API_KEY` in Request-Body | Pull | bei Scrape (TTL 30 s) |
| `smc-live-overlay` → GitHub API | HTTPS | `GITHUB_WORKFLOW_MONITOR_TOKEN` Bearer | Pull | bei Scrape (TTL 30 s) |
| Entwickler-Mac → Grafana API | HTTPS Bearer | Keychain `skipp.grafana.api` | Push | manuell / bei Dashboard-Update |
| Railway → GitHub | HTTPS | Railway OAuth App | Pull (Webhook) | bei git push |
| Pine Script → `smc-live-overlay /smc_live` | HTTPS | `OVERLAY_SECRET_TOKEN` im URL-Pfad | Pull | bei Chart-Request |

### Private Networking fuer `live_overlay` Metrics

Alloy kann den Daemon privat scrapen, sobald der Runtime-Port der Railway
Deployment-Instanz bekannt ist:

```env
OVERLAY_SERVICE_URL=liveoverlaydaemon.railway.internal:<PORT>
```

Nicht setzen:

```env
OVERLAY_SERVICE_URL=liveoverlaydaemon.railway.internal
```

Ohne Port kann Alloy den privaten Host nicht sicher scrapen. Nach der Umstellung
sofort in Grafana pruefen:

```promql
up{job="live_overlay"} == 1
increase(prometheus_remote_storage_samples_failed_total{job="alloy"}[10m]) == 0
```

Bis der Port sicher verifiziert ist, bleibt der public Railway Host die sichere
Production-Konfiguration.

### `/smc_live` Synthetic-Canary-Entscheidung

Keinen Production-`OVERLAY_SECRET_TOKEN` in UptimeRobot hinterlegen. Der Token
ist nicht separat fuer UptimeRobot rotierbar und wird auch von Pine-Consumern
sowie `/metrics` Basic Auth verwendet.

Der aktuelle Schutz bleibt:

- UptimeRobot prueft unauthentifizierte Liveness-/Readiness-Endpunkte.
- Grafana erkennt fehlenden `/smc_live`-Traffic ueber
  `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1` und Request-Rate-Alerts.
- Auth-Probleme laufen ueber `live_overlay_smc_live_auth_denied`.

Plan fuer spaeter:

1. Bevorzugt einen nicht geheimen Contract-Endpoint wie
   `/ready/smc_live_contract` ergaenzen.
2. Alternativ einen internen Synthetic-Check aus `metrics-collector` ueber
   Railway Private Networking bauen, aber mit eigenem, nicht mit Pine geteiltem
   Token.
3. Ohne sicheren Auth-Split bleibt der Grafana First-Zero-Traffic-Alert die
   End-to-End-Absicherung.

---

## 7. Credentials-Übersicht

### macOS Keychain (lokale Entwicklung)

| Keychain-Service | Account | Verwendung |
|------------------|---------|------------|
| `skipp.grafana.api` | `$USER` | Grafana API-Token (Dashboard upsert, Alerts) |
| `skipp.grafana.dashboard` | `$USER` | Alternativer/Legacy-Dashboard-Token |

```bash
# Token lesen (für Skripte)
TOKEN=$(security find-generic-password -s skipp.grafana.api -a "$USER" -w)
```

### Railway-Secrets (in Railway-UI gesetzt, nie in Git)

Werden als Environment-Variablen in den jeweiligen Railway-Services hinterlegt.
Niemals in `.env`-Dateien committen.

### Credential-Rotation

| Credential | Rotation | Schritte |
|------------|----------|----------|
| `OVERLAY_SECRET_TOKEN` | nach Bedarf | 1. Neues Token generieren. 2. In Railway bei `smc-live-overlay` **und** `metrics-collector` setzen. 3. Railway redeploy (automatisch nach Env-Var-Änderung). |
| `GRAFANA_CLOUD_API_KEY` | nach Bedarf | 1. Grafana Cloud UI: `Administration → API keys`. 2. Neuen Key erstellen (MetricsPublisher). 3. In Railway `metrics-collector` aktualisieren. 4. Lokal: `security add-generic-password -U -s skipp.grafana.api -a "$USER" -w "<neuer-token>"`. |
| `UPTIMEROBOT_API_KEY` | nach Bedarf | In Railway `smc-live-overlay` aktualisieren. |
| `GITHUB_WORKFLOW_MONITOR_TOKEN` | bei PAT-Ablauf | Neues PAT mit `actions:read` in Railway hinterlegen. |

---

## 8. Schnellreferenz: häufige Operationen

### Dashboard-Änderung publishen

```bash
cd /path/to/skipp-algo

# 1. JSON validieren (aktuell v1 Dashboard-Shape: top-level panels)
python3 -c "import json; d=json.load(open('services/live_overlay_daemon/infra/grafana/dashboard.json')); n=len(d.get('panels') or d.get('spec',{}).get('elements',{})); print('OK schemaVersion='+str(d.get('schemaVersion','?'))+' panels='+str(n))"

# 2. Dry-run Payload prüfen
python3 scripts/publish_overlay_dashboard.py --dry-run

# 2b. Optional: vollständiges Payload für Diff/Review speichern
python3 scripts/publish_overlay_dashboard.py --dry-run --dry-run-full > /tmp/dashboard-payload.json

# 3. Publish (Skript erkennt v1/v2 automatisch)
python3 scripts/publish_overlay_dashboard.py --message "update"

# 4. Committen
git add services/live_overlay_daemon/infra/grafana/dashboard.json
git commit -m "feat(monitoring): <beschreibung>"
git push
```

### Service-Status prüfen

```bash
# Daemon-Health
curl -s https://liveoverlaydaemon-production.up.railway.app/ready | python3 -m json.tool

# Prometheus-Metriken (Basic Auth)
TOKEN=$(security find-generic-password -s skipp.grafana.api -a "$USER" -w)  # Achtung: Overlay-Token verwenden!
# Besser via railway run:
railway run -s metrics-collector curl -s -u "metrics:$OVERLAY_SECRET_TOKEN" \
  "https://$OVERLAY_SERVICE_URL/metrics" | head -30

# Logs
railway logs -s live_overlay_daemon --tail 100
railway logs -s metrics-collector --tail 50
```

### Metriken direkt aus Grafana Cloud Prometheus abfragen

```bash
railway run -s metrics-collector python3 - <<'PY'
import os, json, urllib.parse, urllib.request, base64, ssl

base = os.getenv("GRAFANA_CLOUD_PROM_URL", "").replace("/api/prom/push", "")
user = os.getenv("GRAFANA_CLOUD_USER", "")
key  = os.getenv("GRAFANA_CLOUD_API_KEY", "")

query = 'live_overlay_market_open{job="live_overlay"}'
url = f"{base}/api/prom/api/v1/query?" + urllib.parse.urlencode({"query": query})
req = urllib.request.Request(url)
req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode())
with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
    result = json.loads(r.read())["data"]["result"]
print(result)
PY
```

### Alloy-Konfig ändern

```bash
# 1. Datei bearbeiten
vi services/live_overlay_daemon/infra/alloy/config.alloy

# 2. Commit + Push → Railway deployed metrics-collector automatisch
git add services/live_overlay_daemon/infra/alloy/config.alloy
git commit -m "fix(alloy): <beschreibung>"
git push
```

### UptimeRobot-Bridge debuggen

```bash
railway run -s live_overlay_daemon python3 - <<'PY'
from services.live_overlay_daemon import uptimerobot_bridge
import json
snap = uptimerobot_bridge.snapshot()
print(json.dumps(snap, indent=2))
PY
```

---

## 9. Änderungen (Backfill 2026-06-21 / 2026-06-22)

### 2026-06-21

- `scripts/publish_overlay_dashboard.py`: Umstellung auf v2-Dashboard-Form als
  Publish-Payload (`apiVersion: dashboard.grafana.app/v2`, `kind: Dashboard`,
  `metadata`, `spec`) inkl. `grafana.app/message` Annotation.
- Playbook: Dashboard-Publish über Skript als Standardpfad dokumentiert.

### 2026-06-22

- Token-Auflösung präzisiert und in Doku/Code synchronisiert:
  - `--token-env` ist primär.
  - `$GRAFANA_API_TOKEN` wird nur als zusätzlicher Fallback geprüft, wenn
    `--token-env` auf eine andere Variable zeigt.
  - danach `$GRAFANA_TOKEN`, dann Keychain.
- Dry-run-Ausgabe gehärtet:
  - `--dry-run` zeigt standardmäßig nur eine kompakte Zusammenfassung
    (Primary/Fallback-Endpoint, Dashboard-Name, apiVersion, Elements, Message).
  - `--dry-run-full` gibt zusätzlich das komplette Payload aus.
- Publish-Robustheit erhöht:
  - automatischer Fallback auf Legacy-Endpoint bei `404` auf dem v1-Endpoint,
    damit Dashboard-Syncs auf Cloud-Stacks zuverlässig ankommen.
- Tests ergänzt für Token-Fallback-Kette und Dry-run-Verhalten.

---

*Zuletzt aktualisiert: 2026-06-28 — Monitoring-Follow-up fuer UptimeRobot, Railway, Alloy und Synthetic-Canary-Plan*

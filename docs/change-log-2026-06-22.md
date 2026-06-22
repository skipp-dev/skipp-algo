# Change Log — 2026-06-22

## Überblick

Diese Notiz fasst die Änderungen vom **22.06.2026** im Live-Overlay-Monitoring zusammen,
inklusive Root-Cause-Analyse der widersprüchlichen Dashboard-Einträge und der Guard-Härtung
für den Grafana-Publisher.

## Änderungen (konsolidiert)

### 1) Dashboard-Duplikate „DEAD + ALIVE“ behoben

- Problem: In den State-Timeline-Panels wurden für dieselbe Komponente doppelte,
  widersprüchliche Zeilen angezeigt (z. B. `flow_refresh DEAD` und `flow_refresh ALIVE`).
- Root Cause: `or vector(0)` in Timeline-Queries erzeugte bei Scrape-Lücken eine zweite,
  label-lose Fallback-Serie mit Wert `0`, die zusammen mit der echten Serie gerendert wurde.
- Fix: `or vector(0)` aus den drei betroffenen Timeline-Queries entfernt:
  - `live_overlay_worker_overlay_refresh_alive{job="live_overlay"}`
  - `live_overlay_worker_flow_refresh_alive{job="live_overlay"}`
  - `live_overlay_overlay_fresh{job="live_overlay"}`
- Ergebnis: Keine Phantom-„DEAD“-Zeilen mehr in Worker/Readiness-Timelines.

### 2) Dashboard-Query-Selektoren gehärtet

- PromQL-Selektoren wurden von `job=~"$job"` auf `job="$job"` umgestellt,
  um unbeabsichtigte Regex-Matches gegen ähnlich benannte Jobs zu vermeiden.

### 3) Guard/Defense-Gap für Dashboard-Publisher geschlossen (F1)

- `scripts/publish_overlay_dashboard.py` wird jetzt explizit von den relevanten
  Ledger-Guards erfasst (ohne globale Aufhebung des `scripts/`-Excludes):
  - `test_subprocess_spawn_sites_ledger.py` (pin für `subprocess.run`)
  - `test_http_post_egress_ledger.py` (pin für `Request(..., method="POST")`)
  - `test_http_client_discipline.py` (pin für `urlopen(..., timeout=...)`)
- Targeted Validation: **34 passed**.

## Relevante PRs / Commits

- PR #2890: Dashboard-Fix (Duplikate + Query-Selector-Härtung)
- PR #2891: Guard-Härtung für `publish_overlay_dashboard.py`

## Operator-Hinweise

- Nach Dashboard-Änderungen immer Publish durchführen:
  - `python scripts/publish_overlay_dashboard.py --message "..."`
- Bei Timeline-Panels `or vector(0)` nur mit Vorsicht einsetzen; für Status-/Timeline-Ansichten
  kann dies zu Phantom-Serien führen.
- In Stat/Timeseries-Panels bleibt `or vector(0)` weiterhin sinnvoll, um „No data“ kontrolliert
  als `0` abzubilden.

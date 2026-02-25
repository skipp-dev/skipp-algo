# Open Prep Suite — Incident Runbook Matrix

Stand: 25.02.2026  
Scope: `open_prep` + `newsstack_fmp` in 24/7 Betrieb

---

## Zweck

Dieses Dokument ist die **schnelle Incident-Matrix** für On-Call:

- **Symptom**
- **wahrscheinliche Ursache**
- **Sofortmaßnahme**
- **Verifikation**
- **typische ETA**

Für Architekturdetails siehe:

- `docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md`
- `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`
- `docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md`
- `docs/OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE_PRINT.html`

---

## Severity-Definition (operativ)

- **SEV-1 (rot):** Kein nutzbarer Kernoutput über mehrere Zyklen oder `fatal_stage` gesetzt.
- **SEV-2 (gelb):** Degraded Output (Teilausfälle), aber Kernpipeline liefert verwertbare Daten.
- **SEV-3 (blau):** Nicht-kritische Nebenfunktion betroffen (z. B. einzelnes Enrichment, kosmetische UI-Warnung).

---

## Incident-Matrix (Symptom → Aktion)

### 1) `run_status.fatal_stage` gesetzt

- **Severity:** SEV-1
- **Wahrscheinliche Ursache:** Hard-Failure in Kernstage
- **Sofortmaßnahme:** Sofort neuen Lauf starten, Logs für Stage prüfen, optionalen Layer isolieren
- **Verifikation:** `fatal_stage` leer, neuer Output mit aktuellem `run_datetime_utc`
- **Typische ETA:** 5–15 min

### 2) `ranked_v2` über mehrere Läufe leer

- **Severity:** SEV-1/2
- **Wahrscheinliche Ursache:** Quote/ATR/Premarket Input unvollständig oder Gates zu restriktiv
- **Sofortmaßnahme:** Data-Layer prüfen (`atr_fetch_errors`, `premarket_fetch_error`), testweise v1/v2 vergleichen
- **Verifikation:** `ranked_candidates` und `ranked_v2` wieder gefüllt
- **Typische ETA:** 10–30 min

### 3) `news_fetch_error` dauerhaft gesetzt

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** FMP-News Endpoint/Rate-Limit/Netzwerk
- **Sofortmaßnahme:** Fail-open akzeptieren, News-Layer isoliert testen, später wieder zuschalten
- **Verifikation:** `news_fetch_error` wieder leer und News-Scores > 0 bei aktiven Tickers
- **Typische ETA:** 10–25 min

### 4) `atr_fetch_errors` hoch (breit über Universe)

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** Historische Preisabfrage langsam/limitiert
- **Sofortmaßnahme:** `atr_parallel_workers`/Timeouts prüfen, Universe temporär verkleinern
- **Verifikation:** Fehlerquote sinkt, `atr14_by_symbol` für Kernsymbole vorhanden
- **Typische ETA:** 15–40 min

### 5) `premarket_fetch_error` dauerhaft gesetzt

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** Premarket/PMH-PML Endpunkt limitiert/timeout
- **Sofortmaßnahme:** PMH/PML als optional behandeln, Kernlauf weiterlaufen lassen, Timeout konservativ erhöhen
- **Verifikation:** `premarket_context` wieder konsistent, Fehlermeldung reduziert
- **Typische ETA:** 10–30 min

### 6) Keine oder veraltete `latest_open_prep_run.json`

- **Severity:** SEV-1
- **Wahrscheinliche Ursache:** Lauf hängt/crasht vor Persistenz
- **Sofortmaßnahme:** Prozess neustarten, Dateirechte/Pfad prüfen, einmaligen CLI-Lauf triggern
- **Verifikation:** Datei-Timestamp aktuell, JSON vollständig parsebar
- **Typische ETA:** 5–20 min

### 7) Realtime-Signale bleiben aus trotz Bewegung

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** Marktzeit-Gate, dünnes Volumen-Regime, zu strikte A0/A1-Kriterien
- **Sofortmaßnahme:** Marktzeit prüfen, `latest_realtime_signals.json` prüfen, Watchlist/Top-N validieren
- **Verifikation:** neue A1/A0 Signale erscheinen bei erfüllten Bedingungen
- **Typische ETA:** 10–20 min

### 8) Realtime-JSONL wird nicht aktualisiert

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** Realtime-Engine läuft nicht / I/O Problem
- **Sofortmaßnahme:** Realtime-Prozess separat starten, Schreibpfad prüfen
- **Verifikation:** `latest_vd_signals.jsonl` aktualisiert im Poll-Intervall
- **Typische ETA:** 5–15 min

### 9) Streamlit zeigt alte Daten trotz Refresh

- **Severity:** SEV-2/3
- **Wahrscheinliche Ursache:** Cache/Refresh-Intervall/Cooldown aktiv
- **Sofortmaßnahme:** Force refresh auslösen, `last_live_fetch_utc` vs `run_datetime_utc` vergleichen
- **Verifikation:** sichtbarer Timestamp-Sprung im UI
- **Typische ETA:** 3–10 min

### 10) Hohe Rate-Limit-Warnungen (429)

- **Severity:** SEV-2
- **Wahrscheinliche Ursache:** API-Budget überschritten
- **Sofortmaßnahme:** Refresh-Intervall erhöhen, optionale Quellen reduzieren, Retry-Backoff wirken lassen
- **Verifikation:** Warnungen gehen zurück, Laufzeit stabilisiert sich
- **Typische ETA:** 10–30 min

### 11) Newsstack liefert keine Kandidaten

- **Severity:** SEV-2/3
- **Wahrscheinliche Ursache:** Quellen disabled / Cursor-/Store-Problem
- **Sofortmaßnahme:** `ENABLE_*` prüfen, `state.db` Health prüfen, isolierten Poll testen
- **Verifikation:** `news_result.json` enthält aktuelle Kandidaten
- **Typische ETA:** 10–25 min

### 12) Alerts werden nicht gesendet

- **Severity:** SEV-2/3
- **Wahrscheinliche Ursache:** `enabled=false`, Webhook-Ziel defekt, Throttling aktiv
- **Sofortmaßnahme:** Alert-Config prüfen, Ziel-URL/Headers validieren, Throttle-Zeit berücksichtigen
- **Verifikation:** `alert_results` enthält erfolgreiche Sends
- **Typische ETA:** 10–20 min

### 13) Diff meldet keine Änderungen trotz offensichtlicher Marktbewegung

- **Severity:** SEV-3
- **Wahrscheinliche Ursache:** Snapshot nicht persistiert/geladen
- **Sofortmaßnahme:** `save_result_snapshot`/Pfad prüfen, Snapshot-Datei aktualisieren
- **Verifikation:** `diff_summary` wieder plausibel
- **Typische ETA:** 10–20 min

### 14) Watchlist wächst unerwartet stark

- **Severity:** SEV-3
- **Wahrscheinliche Ursache:** `auto_add_high_conviction` addiert viele Symbole
- **Sofortmaßnahme:** Auto-Add Kriterien/Threshold prüfen, manuell bereinigen
- **Verifikation:** Watchlist-Wachstum normalisiert
- **Typische ETA:** 10–30 min

### 15) Outcome-Dateien wachsen unkontrolliert

- **Severity:** SEV-3
- **Wahrscheinliche Ursache:** Retention falsch gesetzt
- **Sofortmaßnahme:** `OPEN_PREP_OUTCOME_RETENTION_DAYS` prüfen/korrigieren
- **Verifikation:** alte Files werden rotiert
- **Typische ETA:** 15–45 min

---

## Fast-Path Runbooks (Top 5)

### A) SEV-1: `fatal_stage` oder leerer Kernoutput

1. Sofort neuen Lauf triggern.
2. Prüfen: `run_status`, `fatal_stage`, letzte Logs.
3. Optional-Layer (Newsstack/PMH-PML) temporär isolieren.
4. Nach Recovery: aktuelle `run_datetime_utc`, gefüllte `ranked_v2`, keine fatal stage.

### B) SEV-2: Dauerhafte API-Rate-Limits

1. Refresh-Intervall hochsetzen.
2. Optionale Datenquellen temporär reduzieren.
3. Backoff/Circuit-Breaker wirken lassen.
4. Warnungsrate beobachten, dann schrittweise normalisieren.

### C) SEV-2: Realtime ohne neue Signale

1. Prüfen, ob Realtime-Prozess läuft und Dateien aktualisiert.
2. Marktzeit-Gate und Watchlist prüfen.
3. Inputquotes/Premarket-Freshness prüfen.
4. A1/A0 nur bei echten Kriterien — kein künstliches Erzwingen.

### D) SEV-2: Newsstack leer

1. `ENABLE_FMP`, `ENABLE_BENZINGA_*` prüfen.
2. isolierten `poll_once` testen.
3. Store/Cursor State validieren.
4. Export-Datei auf frischen Timestamp prüfen.

### E) SEV-2/3: Streamlit stale

1. Force Live Refresh.
2. `run_datetime_utc` gegen UI-Anzeige prüfen.
3. Cooldown/Auto-Refresh-Intervall evaluieren.
4. Bei Bedarf UI-Prozess neu starten.

---

## Post-Incident Checklist

Nach jedem Incident:

1. **Root Cause notieren** (kurz, technisch präzise).
2. **Blast Radius** festhalten (welche Outputs/Symbole betroffen).
3. **Guardrail verbessern** (Warnflag, Timeout, Fallback, Throttle).
4. **Doku aktualisieren** (diese Matrix + Ops Quick Reference).
5. **Verifikation** über mindestens zwei erfolgreiche Folgezyklen.

---

## SLA-/ETA-Heuristik (praktisch)

- Transiente Netz-/Rate-Limit-Probleme: **5–20 min**
- Data-Endpoint Degradation: **15–45 min**
- Persistenz-/Pfad-Probleme: **10–30 min**
- mehrschichtige Incidents (Pipeline + Newsstack + UI): **30–90 min**

---

## Kurzfassung für On-Call

Wenn unter Zeitdruck:

1. `latest_open_prep_run.json` + `run_status` zuerst.
2. Danach Realtime und Newsstack getrennt prüfen.
3. Fail-open nutzen: Kernpipeline stabil halten, optionale Layer später nachziehen.
4. Recovery erst als erfolgreich werten, wenn Timestamps, Kandidaten und Warnungen wieder plausibel sind.

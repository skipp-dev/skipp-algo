# Open Prep Suite — Ops Quick Reference (24/7)

Stand: 01.03.2026  
Scope: `open_prep` + `newsstack_fmp` + Terminal-Suite Betrieb

---

## 1) Ziel dieses Dokuments

Dieses Dokument ist die **kurze Betriebsanleitung** für den täglichen Einsatz der Open-Prep-Suite:

- Starten/Überwachen
- häufige Health-Checks
- schnelle Fehlerdiagnose
- sichere Recovery-Schritte

Für volle Architektur/Implementation:  
`docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md`

Incident-Matrix (Symptom → Ursache → Maßnahme → ETA):

- `docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md`

---

## 2) Kernprozesse

### A) Open-Prep Pipeline (Hauptlauf)

- Entry: `open_prep.run_open_prep.generate_open_prep_result(...)`
- Artefakt:
  - `artifacts/open_prep/latest/latest_open_prep_run.json`

### B) Realtime Signale

- Entry: `open_prep.realtime_signals.RealtimeEngine`
- Artefakte:
  - `artifacts/open_prep/latest/latest_realtime_signals.json`
  - `artifacts/open_prep/latest/latest_vd_signals.jsonl`

### C) Newsstack (optional live News-Layer)

- Entry: `newsstack_fmp.pipeline.poll_once(...)`
- Export:
  - `artifacts/open_prep/latest/news_result.json` (abhängig von `EXPORT_PATH`)

### D) Monitoring UI

- Entry: `open_prep/streamlit_monitor.py`
- Nutzt `generate_open_prep_result(...)` + Realtime/Newsstack Integration.

### E) Benzinga Delayed-Quote Overlay

- Aktiv in: `streamlit_terminal.py`, `streamlit_monitor.py`, VisiData Snapshots
- In Pre-Market/After-Hours werden `bz_price`/`bz_chg_pct` Spalten eingeblendet
- Session-Erkennung: `terminal_spike_scanner.market_session()` (US-Handelszeiten, pytz)
- Caching: `@st.cache_data(ttl=60)` — Quotes werden max. alle 60s neu abgeholt
- Preis-Priorität: RT (Realtime) > BZ (Benzinga delayed) > FMP (Schlusskurs)

---

## 3) Kritische Output-Dateien (SOLL)

Nach einem gesunden Lauf sollten folgende Dateien aktuell sein:

- `artifacts/open_prep/latest/latest_open_prep_run.json`
- `artifacts/open_prep/latest/latest_realtime_signals.json`
- `artifacts/open_prep/latest/latest_vd_signals.jsonl`
- `artifacts/open_prep/outcomes/outcomes_YYYY-MM-DD.json`

---

## 4) Schnell-Healthcheck (2 Minuten)

1. **Run-Zeitstempel prüfen**
   - Feld: `run_datetime_utc` in `latest_open_prep_run.json`
2. **Runtime-Status prüfen**
   - Feld: `run_status`
   - Kritisch: `fatal_stage`, viele `warnings`
3. **Kandidaten vorhanden?**
   - `ranked_v2`, `ranked_candidates`, `ranked_gap_go`
4. **Regime plausibel?**
   - `regime.regime`, `regime.reasons`, `macro_bias`
5. **Premarket/ATR-Qualität**
   - `premarket_fetch_error`, `atr_fetch_errors`

6. **Benzinga Quote Freshness (Pre-/After-Market)**
   - Prüfen: `bz_price` Spalte vorhanden in Spike Scanner / Rankings?
   - Wenn nicht: `BENZINGA_API_KEY` gesetzt? `market_session()` korrekt?

---

### Open Prep

- `FMP_API_KEY` (Pflicht)
- `OPEN_PREP_LOG_LEVEL` (z. B. `INFO`, `DEBUG`)
- `OPEN_PREP_BEA_AUDIT` (`1/0`)
- `OPEN_PREP_PMH_FETCH_TIMEOUT_SECONDS`
- `OPEN_PREP_OUTCOME_RETENTION_DAYS`

### Newsstack

- `ENABLE_FMP` (default `1`)
- `ENABLE_BENZINGA_REST` (default `0`)
- `ENABLE_BENZINGA_WS` (default `0`)
- `BENZINGA_API_KEY` (wenn REST/WS aktiviert)
- `POLL_INTERVAL_S`, `TOP_N_EXPORT`, `SCORE_ENRICH_THRESHOLD`

### Terminal

- `BENZINGA_API_KEY` (for delayed quotes + calendar/movers)
- `FMP_API_KEY` (for spike scanner, sector performance)
- `TERMINAL_POLL_INTERVAL_S` (default `5.0`)
- `TERMINAL_SQLITE_PATH`
- `TERMINAL_JSONL_PATH`
- `TERMINAL_MAX_ITEMS` (default `500`)

---

## 5) Realtime Engine — Start / Verify / Restart

Die Realtime-Engine läuft **separat** vom Streamlit-Monitor.
Wenn im Monitor stale/keine RT-Signale angezeigt werden, zuerst diese Schritte nutzen.

### Start (Foreground)

```bash
source .venv/bin/activate
PYTHONPATH="$PWD" python -m open_prep.realtime_signals --ultra
```

Alternative mit geringerer Last:

```bash
source .venv/bin/activate
PYTHONPATH="$PWD" python -m open_prep.realtime_signals --interval 15
```

### Verify (läuft + schreibt frische Artefakte)

```bash
pgrep -fal "open_prep.realtime_signals"
```

```bash
PYTHONPATH="$PWD" python - <<'PY'
from open_prep.realtime_signals import RealtimeEngine
d = RealtimeEngine.load_signals_from_disk()
signals = d.get("signals") or []
print("updated_at:", d.get("updated_at"))
print("stale:", bool(d.get("stale")), "stale_age_s:", int(d.get("stale_age_s") or 0))
print("signals:", len(signals), "A0:", sum(1 for s in signals if s.get("level") == "A0"), "A1:", sum(1 for s in signals if s.get("level") == "A1"))
PY
```

### Restart (wenn stale oder Prozess hängt)

```bash
pkill -f "open_prep.realtime_signals"
source .venv/bin/activate
PYTHONPATH="$PWD" python -m open_prep.realtime_signals --ultra
```

---

## 6) Alarmzeichen im Betrieb

Wenn eines der folgenden Symptome auftritt, ist der Lauf degraded:

- `run_status.fatal_stage` gesetzt
- hohe Fehlerquote in `atr_fetch_errors`
- `premarket_fetch_error` dauerhaft nicht leer
- `news_fetch_error` dauerhaft nicht leer
- `ranked_v2` dauerhaft leer trotz breiter Universe
- stark steigende Runtime-Warnungen im Streamlit Monitor

---

## 7) Standard-Recovery Playbook

### Schritt 1 — Soft-Recovery

- Refresh/Neulauf auslösen (Streamlit „Sofort aktualisieren“ oder CLI-Run)
- Prüfen, ob Warnungen transient waren (Rate Limit/Timeout)

### Schritt 2 — Data-Layer isolieren

- Nur Open-Prep Lauf ohne optionale Newsstack/Benzinga
- Prüfen, ob Kernpipeline (Macro + Quotes + Ranking) stabil läuft

### Schritt 3 — Realtime isolieren

- `realtime_signals` separat starten
- prüfen, ob `latest_realtime_signals.json` und JSONL aktualisiert werden

### Schritt 4 — Newsstack isolieren

- `newsstack_fmp.pipeline.poll_once(...)` separat validieren
- Cursor-/Store-Fehler prüfen (`state.db` / dedup)

### Schritt 5 — Hard-Recovery

- Prozess sauber neu starten
- nach Restart auf frische Timestamps + gefüllte Outputs prüfen

---

## 8) Guardrails, die bewusst fail-open sind

Die Suite degradiert in mehreren Bereichen kontrolliert statt komplett abzubrechen:

- News-Fetch Fehler → Ranking läuft ohne News-Boost weiter
- Macro Calendar Fehler → Bias fällt auf neutral/leer
- einzelne ATR/Premarket-Ausfälle → Teilergebnisse bleiben nutzbar
- Capability-Limits (Plan/Endpoint) → Warnung + Fallbacks

Wichtig: Fail-open bedeutet **nicht** „alles gut“, sondern „laufend, aber mit reduzierter Signalqualität“.

---

## 9) On-Call Decision Matrix

### Grün (Normalbetrieb)

- aktuelle Timestamps
- keine fatalen Stages
- Kandidaten + Realtime Signale plausibel

### Gelb (Degraded)

- partielle Fetch-Fehler, aber Output vorhanden
- erhöhte Warnungen
- Handlung: beobachten + Soft-Recovery

### Rot (Incident)

- leere Kernoutputs über mehrere Zyklen
- fatal_stage gesetzt
- anhaltende API-/Storage-Fehler
- Handlung: isolieren, schrittweise wieder zuschalten

---

## 10) Daily / Weekly Ops Checkliste

### Daily

- letzte Run-/Signal-Timestamps aktuell?
- Runtime-Warnungen unter Kontrolle?
- Diff/Regime plausibel zur Marktlage?
- keine auffällige Drift in Hit-Rate Buckets?

### Weekly

- Feature-Importance Report prüfen
- Weight-Drift (`_regime_adjusted`) plausibilisieren
- Outcome-Retention/Artefaktgröße kontrollieren
- Alert-Throttling und Ziel-Webhook Health prüfen

---

## 11) Safe Change Rules (Ops)

Bei Änderungen an produktionskritischen Modulen:

- `run_open_prep.py`, `scorer.py`, `macro.py`, `realtime_signals.py`, `pipeline.py`
- `terminal_spike_scanner.py`, `terminal_poller.py`, `streamlit_terminal.py`
- `newsstack_fmp/ingest_benzinga_calendar.py`

immer:

1. `py_compile` auf betroffene Dateien
2. mindestens ein kompletter E2E-Lauf
3. Output-Contract-Felder auf Rückwärtskompatibilität prüfen
4. erst danach in 24/7-Betrieb übernehmen

---

## 12) TL;DR

Wenn’s brennt:

1. `latest_open_prep_run.json` + `run_status` prüfen
2. Realtime und Newsstack getrennt testen
3. bei Bedarf degraded weiterlaufen lassen (fail-open) statt blind stoppen
4. nach Recovery auf Timestamps + Kandidaten + Warnungen verifizieren
5. Bei stale Preisen in Pre-/After-Market: `BENZINGA_API_KEY` + `market_session()` prüfen

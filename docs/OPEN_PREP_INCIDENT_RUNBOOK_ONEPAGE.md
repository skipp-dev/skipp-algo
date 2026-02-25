# Open Prep — Incident One-Page (On-Call)

Stand: 25.02.2026  
Scope: `open_prep` + `newsstack_fmp`

## 1) Priorität

- **SEV-1:** Kein nutzbarer Kernoutput / `fatal_stage` gesetzt
- **SEV-2:** Degraded Output (Teilausfälle), Kern läuft
- **SEV-3:** Nebenfunktion betroffen

## 2) 60-Sekunden-Triage

1. `artifacts/open_prep/latest/latest_open_prep_run.json` aktuell?
2. `run_status.fatal_stage` oder viele `warnings`?
3. `ranked_v2`/`ranked_candidates` gefüllt?
4. `premarket_fetch_error` / `atr_fetch_errors` auffällig?
5. Realtime-Dateien aktualisiert?

## 3) Symptom → Aktion

### A) `fatal_stage` gesetzt (SEV-1)

- **Aktion:** Sofort neuen Lauf triggern, Stage-Logs prüfen, optionale Layer isolieren
- **Done wenn:** `fatal_stage` leer + frischer `run_datetime_utc`
- **ETA:** 5–15 min

### B) `ranked_v2` bleibt leer (SEV-1/2)

- **Aktion:** ATR/Premarket-Fehler prüfen, v1/v2 vergleichen, Inputqualität validieren
- **Done wenn:** `ranked_v2` und `ranked_candidates` wieder gefüllt
- **ETA:** 10–30 min

### C) Dauerhafte 429/Rate-Limits (SEV-2)

- **Aktion:** Refresh-Intervall erhöhen, optionale Quellen reduzieren, Backoff wirken lassen
- **Done wenn:** Warnungsrate sinkt, Laufzeiten stabilisieren
- **ETA:** 10–30 min

### D) Realtime liefert nichts (SEV-2)

- **Aktion:** Realtime-Prozess + Marktzeit-Gate + Watchlist/Top-N prüfen
- **Done wenn:** `latest_realtime_signals.json`/JSONL wieder live aktualisiert
- **ETA:** 5–20 min

### E) Newsstack leer (SEV-2/3)

- **Aktion:** `ENABLE_*` prüfen, isolierten Poll testen, Cursor/Store prüfen
- **Done wenn:** News-Export wieder aktuelle Kandidaten enthält
- **ETA:** 10–25 min

## 4) Recovery-Reihenfolge

1. **Kernpipeline stabilisieren** (`open_prep` Output)
2. **Realtime wiederherstellen**
3. **Newsstack zuschalten**
4. **UI/Alerts verifizieren**

> Prinzip: Erst Kernfunktion (entscheidungsfähig), dann Komfort-/Enrichment-Layer.

## 5) Verifikation nach Recovery

- Zwei aufeinanderfolgende erfolgreiche Zyklen
- Frische Timestamps in allen Kernartefakten
- Plausible Kandidatenzahl + Regime + Warnungsniveau

## 6) Safe-Change Rule

Bei Änderungen an `run_open_prep.py`, `scorer.py`, `macro.py`, `realtime_signals.py`, `newsstack_fmp/pipeline.py`:

1. `py_compile` der betroffenen Dateien
2. mindestens ein E2E-Lauf
3. Output-Contract prüfen
4. erst dann in 24/7 übernehmen

## 7) Referenzen

- Vollmatrix: `docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md`
- Ops Quick Ref: `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`
- Volltechnik: `docs/OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md`

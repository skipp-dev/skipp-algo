# E2E-Smoke-Test — Runbook und Ergebnis

Stand: 2026-04-17 (WP-C)

## Testdefinition

### Zweck

Nachweis, dass der kritische Produktpfad des SMC-Systems end-to-end funktioniert:
Daten → Strukturartefakte → Measurement-Benchmark → Scoring → Release-Gates.

### Minimalpfad

Der Test deckt den kleinsten sinnvollen End-to-End-Pfad ab: ein einzelnes Symbol/Timeframe-Paar durchläuft alle drei Pipeline-Stufen.

| Schritt | Script | Beschreibung |
|---------|--------|--------------|
| 1 | `run_smc_pre_release_artifact_refresh.py` | Erzeugt Strukturartefakte aus dem Workbook |
| 2 | `run_smc_measurement_benchmark.py` | Führt Measurement-Benchmark mit Scoring durch |
| 3 | `run_smc_release_gates.py` | Prüft Provider-Health, Reference-Bundle, Measurement-Lane |

### Startzustand

- Repository auf `main`, HEAD sauber
- Produktions-Workbook vorhanden unter `artifacts/smc_microstructure_exports/`
- Python-Umgebung mit allen Dependencies

### Pass-Kriterien

| Schritt | Kriterium |
|---------|-----------|
| Pre-Release Refresh | `artifacts_written > 0` und Status `ok` oder `warn` |
| Measurement Benchmark | Exit-Code 0, n_events ≥ 0 |
| Release Gates | Alle erwarteten Gates (`provider_health`, `reference_bundle`, `measurement_lane`) im Report vorhanden |

### Fail-Kriterien

- Uncaught Exception in einem der drei Schritte
- Exit-Code ≠ 0 bei Benchmark
- Fehlende Gate-Namen im Release-Gates-Report
- Refresh erzeugt 0 Artefakte

### Wiederholbarkeit

```bash
python scripts/run_smc_e2e_smoke_test.py \
  --symbol AAPL --timeframe 15m \
  --output artifacts/ci/smoke_test/smoke_report.json
```

Kann auch in CI laufen. Ohne Produktionsdaten sind 0 Events erwartbar und akzeptabel — die Pipeline selbst muss trotzdem fehlerfrei durchlaufen.

---

## Ergebnis — Erstdurchlauf 2026-04-17

| Eigenschaft | Wert |
|-------------|------|
| Symbol | AAPL |
| Timeframe | 15m |
| Gesamtergebnis | **PASS** (3/3 Schritte bestanden) |
| Dauer | 62.42 s |
| Zeitpunkt | 2026-04-17T10:43:29 UTC |

### Einzelschritte

| Schritt | Pass | Exit-Code | Detail |
|---------|------|-----------|--------|
| Pre-Release Refresh | ✅ | 0 | 1 Artefakt geschrieben, Status ok |
| Measurement Benchmark | ✅ | 0 | 213 Events, Brier-Score 0.2537 |
| Release Gates | ✅ | 0 | Alle 3 Gates vorhanden, Status ok |

### Evidenz

- Report: `artifacts/ci/smoke_test/smoke_report.json`
- Benchmark-Summary: `artifacts/ci/smoke_test/smoke_measurement/AAPL/15m/measurement_summary_AAPL_15m.json`
- Refresh-Report: `artifacts/ci/smoke_test/smoke_pre_release_refresh.json`
- Gates-Report: `artifacts/ci/smoke_test/smoke_release_gates.json`

## Bewertung

Die Exit-Lücke "kein definierter E2E-Smoke-Test" ist geschlossen. Der Test ist:
- **konkret**: exakt drei benannte Schritte mit klaren Pass/Fail-Kriterien
- **wiederholbar**: ein Befehl, deterministisches Ergebnis
- **beurteilbar**: strukturierter JSON-Report mit Einzelschritt-Bewertung
- **bestanden**: alle Schritte grün beim Erstdurchlauf

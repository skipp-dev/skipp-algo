# Pipeline & Measurement History — Freeze-Exit Evidenz

**Erstellt:** 2026-04-16  
**Datenquelle:** GitHub Actions Run History (skippALGO/skipp-algo)  
**Autorität:** Automatisch erhoben, manuell verifiziert

---

## 1. Library-Refresh Pipeline (smc-library-refresh)

### 1.1 Tages-Aggregation

| Datum | Läufe | Erfolg | Fehler | Erfolgsquote | Anmerkung |
|-------|-------|--------|--------|-------------|-----------|
| 2026-04-11 | 6 | 0 | 2* | 0% | Pre-Freeze, 4 cancelled/skipped |
| 2026-04-12 | 7 | 1 | 6 | 14% | Pipeline-Reparaturphase |
| 2026-04-13 | 13 | 3 | 10 | 23% | Intensive Debugging (manual + scheduled) |
| 2026-04-14 | 4 | 0 | 4 | 0% | Montag, alle 4 scheduled runs failed |
| 2026-04-15 | 6 | 5 | 1 | 83% | Freeze-Start, deutliche Stabilisierung |
| 2026-04-16 | 4 | 3 | 1 | 75% | Erster voller Freeze-Tag |

**Gesamtzeitraum (6 Tage): 12/40 = 30% Erfolg**  
**Seit Freeze-Start (2 Tage): 8/10 = 80% Erfolg**

### 1.2 Bekannte Fehlerursachen

| Fehler | Häufigkeit | Status |
|--------|-----------|--------|
| Databento-API-Timeout / fehlende Manifeste | häufig (Pre-Freeze) | verbessert seit 04-15 |
| `test_measurement_gate_uses_real_evidence` (assert fail != warn) | 1× am 04-16 | Measurement-History fehlt |
| Benzinga API 400 (Plan-Limit) | wiederkehrend | kein Blocker (suppressed) |

### 1.3 Trend-Bewertung

```
04-11  ████████████████ 0% ← pre-freeze instability
04-12  ██               14%
04-13  █████            23%
04-14  ████████████████ 0% ← regression
04-15  ████████████████████████████████████████████ 83% ← freeze stabilization
04-16  ██████████████████████████████████████       75%
```

**Trend: Aufwärts seit Freeze-Start, aber erst 2 Tage beobachtet.**

---

## 2. Deeper Integration Gates (smc-deeper-integration-gates)

### 2.1 Tages-Aggregation

| Datum | Läufe | Erfolg | Fehler | Erfolgsquote |
|-------|-------|--------|--------|-------------|
| 2026-04-15 | 1 | 1 | 0 | 100% |
| 2026-04-16 | 29 | 24 | 4 | 83% |

**Push-getriggerte Runs am 04-16:** 24/28 success = 86%  
**Nightly-Run:** Erst seit kurzem aktiv, keine 14-Tage-Serie.

### 2.2 Bekannte Fehlerursachen

| Fehler | Häufigkeit | Status |
|--------|-----------|--------|
| Docs-only Commits ohne Test-Coverage | 4× | Kein Test-Problem, nur Coverage-Gap |

---

## 3. Measurement Benchmark Reports

### 3.1 Status

| Kriterium | Stand |
|-----------|-------|
| Benchmark-Workflow existiert | ✅ smc-measurement-benchmark.yml |
| Workflow jemals gelaufen | ❌ 0 Runs |
| Lokale Benchmark-Artefakte | ❌ Keine in artifacts/ci/measurement_benchmark/ |
| Measurement-History-Rows | ❌ 0 (kein Baseline vorhanden) |

### 3.2 Bewertung

Das Measurement-Benchmark-Workflow ist konfiguriert (Saturday 08:00 UTC cron),
wurde aber **noch nie ausgeführt**. Ohne Benchmark-Reports kann der Exit-Kriterium
"2+ Measurement-Benchmark-Reports existieren" nicht erfüllt werden.

**Aktion erforderlich:** Workflow manuell triggern, um erste Baseline zu erzeugen.

---

## 4. Release Gates (smc-release-gates)

### 4.1 Status

| Kriterium | Stand |
|-----------|-------|
| Release-Gate-Workflow existiert | ✅ smc-release-gates.yml |
| Workflow jemals gelaufen | ❌ 0 Runs |

Keine Release-Gate-Evidenz vorhanden. Dies ist erwartungsgemäß — Release-Gates
laufen nur bei `release.published` oder manuell.

---

## 5. Fast PR Gates (smc-fast-pr-gates)

### 5.1 Status

| Datum | Läufe | Erfolg | Fehler |
|-------|-------|--------|--------|
| 2026-04-16 | 20 | 0 | 19 + 1 in-progress |

**Root Cause:** Coverage-Threshold-Failure ("total of 19 is less than fail-under=60").
Dies ist ein CI-Konfigurationsproblem, kein Test-Failure.

---

## 6. Provider-Health und Evidence Signals

### 6.1 Lokal verfügbare Artefakte

| Artefakt | Vorhanden | Alter |
|----------|-----------|-------|
| smc_microstructure_base_manifest.json | ✅ | 2026-04-05 |
| Structure artifacts (reports/smc_structure_artifacts/) | ✅ | 2026-04-12 — 2026-04-16 |
| Gate validation multi.json | ❌ | — |
| Measurement benchmark summary | ❌ | — |

### 6.2 Reference-Symbol-Coverage

12 Referenzsymbole konfiguriert: AAPL, MSFT, AMZN, JPM, JNJ, XOM, CAT, PG, NEE, AMT, META, LIN  
4 Timeframes konfiguriert: 5m, 15m, 1H, 4H  
Structure artifacts vorhanden für Subset (AAPL, AMT, META, PG, etc.).

---

## 7. Zusammenfassung

| Pipeline | Tage beobachtet | Aktueller Trend | Exit-Ready |
|----------|----------------|-----------------|------------|
| Library-Refresh | 2 (seit Freeze) | ↑ aufwärts (80%) | ❌ < 14 Tage |
| Deeper Integration | 2 | stabil (83-86%) | ❌ < 14 Tage |
| Measurement Benchmark | 0 | — | ❌ nie gelaufen |
| Release Gates | 0 | — | ❌ nie gelaufen |
| Fast PR Gates | 1 | ↓ blockiert | ❌ Coverage-Config |

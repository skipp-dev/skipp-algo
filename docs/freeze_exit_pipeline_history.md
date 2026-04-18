# Pipeline & Measurement History — Freeze-Exit Evidenz

**Erstellt:** 2026-04-16  
**Letzte Aktualisierung:** 2026-04-18  
**Datenquelle:** GitHub Actions Run History (skippALGO/skipp-algo)  
**Autorität:** Automatisch erhoben, manuell verifiziert

---

## 1. Library-Refresh Pipeline (smc-library-refresh)

### 1.1 Tages-Aggregation

| Datum | Läufe | Erfolg | Fehler | Erfolgsquote | Anmerkung |
|-------|-------|--------|--------|-------------|-----------|
| 2026-04-03 | 4 | 0 | 4 | 0% | Pre-Freeze, Pipeline instabil |
| 2026-04-06 | 4 | 0 | 4 | 0% | Pre-Freeze |
| 2026-04-07 | 4 | 0 | 4 | 0% | Pre-Freeze |
| 2026-04-08 | 4 | 0 | 4 | 0% | Pre-Freeze |
| 2026-04-09 | 14 | 0 | 3 | 0% | 11 cancelled/skipped |
| 2026-04-10 | 12 | 0 | 4 | 0% | 8 cancelled/skipped |
| 2026-04-11 | 20 | 0 | 15 | 0% | 5 cancelled/skipped |
| 2026-04-12 | 7 | 1 | 6 | 14% | Pipeline-Reparaturphase |
| 2026-04-13 | 13 | 3 | 10 | 23% | Intensive Debugging (manual + scheduled) |
| 2026-04-14 | 4 | 0 | 4 | 0% | Montag, alle 4 scheduled runs failed |
| 2026-04-15 | 6 | 5 | 1 | 83% | Freeze-Start, deutliche Stabilisierung |
| 2026-04-16 | 4 | 3 | 1 | 75% | Erster voller Freeze-Tag |
| 2026-04-17 | 4 | 4 | 0 | 100% | Volle Stabilität |

**Gesamtzeitraum (04-03 bis 04-17): 16/100 = 16% Erfolg** (viele cancelled/skipped in Pre-Freeze)  
**Seit Freeze-Start (3 Tage, 04-15 bis 04-17): 12/14 = 86% Erfolg**  
**Letzter Tag (04-17): 4/4 = 100% Erfolg**

### 1.2 Bekannte Fehlerursachen

| Fehler | Häufigkeit | Status |
|--------|-----------|--------|
| Databento-API-Timeout / fehlende Manifeste | häufig (Pre-Freeze) | verbessert seit 04-15 |
| `test_measurement_gate_uses_real_evidence` (assert fail != warn) | 1× am 04-16 | Measurement-History fehlt |
| Benzinga API 400 (Plan-Limit) | wiederkehrend | kein Blocker (suppressed) |

### 1.3 Trend-Bewertung

```
04-03  ████████████████ 0% ← pre-freeze
04-06  ████████████████ 0%
04-07  ████████████████ 0%
04-08  ████████████████ 0%
04-09  ████████████████ 0%
04-10  ████████████████ 0%
04-11  ████████████████ 0%
04-12  ██               14%
04-13  █████            23%
04-14  ████████████████ 0% ← regression
04-15  ████████████████████████████████████████████ 83% ← freeze stabilization
04-16  ██████████████████████████████████████       75%
04-17  ██████████████████████████████████████████████████ 100% ← stable
```

**Trend: Stabil seit Freeze-Start, 3 Tage beobachtet. Letzter Tag 100%.**

---

## 2. Deeper Integration Gates (smc-deeper-integration-gates)

### 2.1 Tages-Aggregation

| Datum | Läufe | Erfolg | Fehler | Erfolgsquote |
|-------|-------|--------|--------|-------------|
| 2026-04-15 | 4 | 4 | 0 | 100% |
| 2026-04-16 | 33 | 29 | 4 | 87% |
| 2026-04-17 | 11 | 9 | 0 | 81% |
| 2026-04-18 | 2 | 1 | 0 | 50% |

**Seit Freeze-Start (4 Tage): 43/50 success = 86%**

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
| Workflow jemals gelaufen | ✅ 3 Runs (alle success) |
| Erster Lauf | 2026-04-17 08:55 UTC |
| Letzter Lauf | 2026-04-18 08:33 UTC |

### 3.2 Bewertung

Das Measurement-Benchmark-Workflow wurde **3× erfolgreich ausgeführt** (2026-04-17 bis 2026-04-18).
Das Exit-Kriterium "2+ Measurement-Benchmark-Reports existieren" ist damit **erfüllt**.

---

## 4. Release Gates (smc-release-gates)

### 4.1 Status

| Kriterium | Stand |
|-----------|-------|
| Release-Gate-Workflow existiert | ✅ smc-release-gates.yml |
| Workflow jemals gelaufen | ✅ 3 Runs |
| Erste 2 Runs (04-17) | ❌ failure (fehlende --ci-mode vor Commit 9cc2ee73) |
| Run #3 (04-18) | ⏳ in_progress (nach Fix: _DATA_ABSENT_CODES erweitert) |

Die ersten beiden Runs scheiterten, weil der Workflow das Gate-Script noch ohne
`--ci-mode` ausführte. Seit Commit `9cc2ee73` ist `--ci-mode` im Workflow aktiv.
Commit `92a34362` erweitert zusätzlich die `_DATA_ABSENT_CODES`, damit alle
CI-typischen Provider-Health-Codes (MISSING_ARTIFACT, EMPTY_CONTEXT_BARS,
DOMAIN_DROPPED_NEWS etc.) korrekt als data-absent erkannt werden.

---

## 5. Fast PR Gates (smc-fast-pr-gates)

### 5.1 Status

| Datum | Läufe | Erfolg | Fehler | Erfolgsquote |
|-------|-------|--------|--------|-------------|
| 2026-04-16 | 9 | 1 | 8 | 11% |
| 2026-04-17 | 10 | 7 | 1 | 70% |
| 2026-04-18 | 1 | 0 | 0 | 0% |

**Root Cause der 04-16-Fehler:** Coverage-Threshold-Failure ("fail-under=60", tatsächlich 19%).
Am 04-17 deutliche Verbesserung auf 70% durch Workflow-/Config-Fixes.
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
| Library-Refresh | 3 (seit Freeze) | ↑ stabil (86%, letzter Tag 100%) | ❌ < 14 Tage |
| Deeper Integration | 4 | stabil (86%) | ❌ < 14 Tage |
| Measurement Benchmark | 2 (3 Runs) | ✅ alle success | ✅ ≥ 2 Reports |
| Release Gates | 1 (in_progress) | ⏳ CI-Fix deployed | ⏳ Ergebnis ausstehend |
| Fast PR Gates | 3 | ↑ aufwärts (70% am 04-17) | ❌ Coverage-Config |

# Freeze-Exit Stability Program — Mehrlauf-Operationalisierung

**Erstellt:** 2026-04-16  
**Ziel:** Systematische Evidenz-Sammlung über 14+ Tage für Freeze-Exit  
**Autorität:** Owner Review v3

---

## 1. Cadence & Automatisierung

### 1.1 Bestehende Automatisierung (aktiv)

| Workflow | Trigger | Cadence | Seit |
|----------|---------|---------|------|
| smc-library-refresh | schedule | 4×/Tag Mo–Fr (12:30, 14:30, 16:30, 18:30 UTC) | aktiv |
| smc-deeper-integration-gates | push + schedule | Nightly 03:15 UTC + jeder Push auf main | aktiv |
| smc-live-newsapi-refresh | schedule | regelmäßig | aktiv |
| smc-measurement-benchmark | schedule | Samstag 08:00 UTC | **konfiguriert, nie gelaufen** |

### 1.2 Erforderliche Aktionen

| Aktion | Priorität | Verantwortung | Deadline |
|--------|-----------|---------------|----------|
| Measurement-Benchmark einmal manuell triggern | **P0** | Owner | sofort |
| Ergebnis prüfen, ggf. Fixes | P0 | Owner | innerhalb 24h |
| 2. Benchmark-Lauf (nächster Samstag oder manuell) | P0 | Owner | vor 2026-04-23 |
| Fast-PR-Gates Coverage-Config fixen | P1 | Owner | vor 2026-04-20 |

### 1.3 Minimales Monitoring-Programm

**Wöchentlich (jeden Montag):**

1. `gh run list --repo skippALGO/skipp-algo --workflow smc-library-refresh --limit 28` prüfen
2. Tages-Aggregation erstellen (Erfolg/Fehler/Quote)
3. Neue Fehler klassifizieren:
   - **Infrastruktur** (API-Timeout, Runner-Problem) → dokumentieren, kein Gate-Problem
   - **Test-Failure** (echter Fehler im Code) → diagnostizieren und fixen
   - **Config** (Coverage-Threshold, fehlende Secrets) → CI-Fix
4. Ergebnis in `docs/freeze_exit_pipeline_history.md` nachtragen

**Bei jedem Measurement-Benchmark-Lauf:**

1. Prüfen: Brier ≤ 0.60, ECE ≤ 0.30
2. Vergleich mit vorherigem Lauf: Regression ≤ 0.08
3. Event-Count pro Family notieren
4. Ergebnis in Pipeline-History dokumentieren

---

## 2. Artefakt-Inventar

### 2.1 Automatisch erzeugte Artefakte

| Artefakt | Erzeugt von | Speicherort | Retention |
|----------|-------------|-------------|-----------|
| Refresh pytest log | smc-library-refresh | artifacts/ci/smc_refresh_gate_pytest.log | Run-Level |
| Gate evidence summary | smc-library-refresh | artifacts/ci/smc_refresh_evidence_summary.json | Run-Level |
| Deeper health report | smc-deeper-integration-gates | artifacts/ci/smc_deeper_health_report.json | Run-Level |
| Deeper measurement report | smc-deeper-integration-gates | artifacts/ci/smc_deeper_measurement_report.json | Run-Level |
| Benchmark KPIs CSV | smc-measurement-benchmark | artifacts/ci/measurement_benchmark/*/benchmark_*_kpis.csv | 180 Tage |
| Scoring artifact | smc-measurement-benchmark | artifacts/ci/measurement_benchmark/*/scoring_*.json | 180 Tage |
| Reliability plot | smc-measurement-benchmark | artifacts/ci/measurement_benchmark/*/reliability_*.html | 180 Tage |

### 2.2 Manuell gepflegte Artefakte

| Artefakt | Verantwortung | Pfad |
|----------|---------------|------|
| Stabilitätskriterien | Owner | docs/freeze_exit_stability_criteria.md |
| Pipeline-History | Owner | docs/freeze_exit_pipeline_history.md |
| Freeze-Exit-Memo | Owner | docs/freeze_exit_memo.md |

---

## 3. Fail-Handling

### 3.1 Grundregel

**Kein Fehler wird versteckt.** Jeder gescheiterte Lauf bleibt in der
GitHub Actions History sichtbar und wird in der Pipeline-History
dokumentiert.

### 3.2 Eskalationsstufen

| Situation | Aktion |
|-----------|--------|
| Einzelner Fehler, Rest des Tages grün | Dokumentieren, weiter beobachten |
| Ganzer Tag ohne Erfolg | Root-Cause-Analyse, Diagnose in Pipeline-History |
| 2+ konsekutive Fehltage | Freeze-Exit blockiert bis Serie durchbrochen |
| Neuer Fehlertyp | Klassifizieren (Infra/Test/Config), ggf. Fix priorisieren |
| Messwert-Regression > Schwelle | Freeze-Exit blockiert bis Wert sich erholt |

### 3.3 Was kein Fix erfordert

- Benzinga API 400 (Plan-Limit) → bekannt, suppressed, kein Blocker
- Infrastruktur-Timeouts (< 5% der Läufe) → dokumentieren, kein Gate-Problem
- Coverage-Warnungen bei Docs-only-Commits → CI-Config-Issue, nicht Produkt

---

## 4. Timeline bis Freeze-Exit

```
2026-04-16  [JETZT] Stabilitätsprogramm gestartet
2026-04-17  1. Measurement-Benchmark manuell triggern
2026-04-19  2. Measurement-Benchmark (Samstag-Cron oder manuell)
2026-04-20  Fast-PR-Gates Coverage-Fix
2026-04-21  1. Wochen-Review: Pipeline-History aktualisieren
2026-04-28  2. Wochen-Review
2026-04-29  Frühester theoretischer 14-Tage-Punkt (ab 04-15)
...
2026-05-05  3. Wochen-Review
2026-05-12  4. Wochen-Review, Freeze-Exit-Entscheidung vorbereiten
2026-05-15  Freeze-Ende — Exit oder Verlängerung
```

---

## 5. Freeze-Exit-Entscheidungsprozess

Am oder vor 2026-05-12 wird das Freeze-Exit-Memo aktualisiert mit:

1. **Tabellarische 14-Tage-Übersicht** aller Pipeline-Läufe
2. **Measurement-Benchmark-Vergleich** (≥ 2 Reports)
3. **Offene Bugs** (Liste, Schwere)
4. **Pine-Titel-Status** (korrekt ja/nein)
5. **Explizite Entscheidung:** EXIT / VERLÄNGERN / TEILWEISE

Der Owner trifft die Entscheidung. Kein automatischer Exit.

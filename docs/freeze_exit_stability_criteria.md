# Freeze-Exit Stability Criteria

**Status:** AKTIV — Beobachtungsphase  
**Erstellt:** 2026-04-16  
**Autorität:** Owner Review v3  
**Freeze-Zeitraum:** 2026-04-15 — 2026-05-15

---

## 1. Zweck

Dieses Dokument definiert die messbaren Stabilitätskriterien,
die erfüllt sein müssen, bevor der Feature Freeze beendet werden darf.
Ein Freeze-Exit erfordert **belastbare Evidenz über Zeit**, nicht
punktuelle Einzelergebnisse.

---

## 2. Geltende Stabilitätskriterien

### 2.1 Library-Pipeline (smc-library-refresh)

| Kriterium | Schwelle | Quelle |
|-----------|----------|--------|
| Erfolgreiche Refreshs | ≥ 56 in 14 Tagen | FEATURE_FREEZE.md Exit-Kriterium |
| Tages-Erfolgsquote | ≥ 75% (3/4 Läufe pro Tag) | 4 Scheduled Runs/Tag (Mo–Fr) |
| Konsekutive Fehltage | 0 (kein ganzer Tag ohne Erfolg) | Workflow-History |
| Scheduled-Run-Stabilität | kein Trend zu steigenden Fehlern | Tages-Aggregation |

**Definition "erfolgreicher Refresh":** Workflow-Run mit `conclusion: success`.
Runs mit `conclusion: failure` zählen als Fehler und werden **nicht versteckt**.

**Cadence:** 4× täglich Mo–Fr (12:30, 14:30, 16:30, 18:30 UTC).
14 Tage × 4 Läufe/Tag = 56 Läufe bei 100% Erfolg (20 Arbeitstage × 4 = 80 potenzielle Läufe).

### 2.2 Deeper Integration Gates (smc-deeper-integration-gates)

| Kriterium | Schwelle | Quelle |
|-----------|----------|--------|
| Nightly-Erfolgsquote | ≥ 80% über 14 Tage | Nightly cron 03:15 UTC |
| Push-Gate-Stabilität | ≥ 90% success auf main-Pushes | Push-trigger |
| Measurement-Lane-Status | warn oder ok (kein fail) | Gate-Evidence-Report |

### 2.3 Measurement Benchmark Reports

| Kriterium | Schwelle | Quelle |
|-----------|----------|--------|
| Existierende Benchmark-Reports | ≥ 2 | FEATURE_FREEZE.md Exit-Kriterium |
| Metriken-Konsistenz | Brier ≤ 0.60, ECE ≤ 0.30 | release_policy.py Thresholds |
| History-Runs pro Symbol/TF | ≥ 2 | MeasurementShadowThresholds.min_history_runs |
| Keine Regression | Brier-Regression ≤ 0.08 | max_calibrated_brier_regression_abs |

### 2.4 End-to-End Smoke-Test

| Kriterium | Schwelle | Quelle |
|-----------|----------|--------|
| Bewertung | ≥ 7/10 | FEATURE_FREEZE.md Exit-Kriterium |
| Scope | 12 Referenzsymbole × 4 Timeframes | release_policy.py |
| Provider-Health | ok oder warn (kein fail) | run_smc_ci_health_checks.py |

### 2.5 Weitere Exit-Kriterien

| Kriterium | Status | Quelle |
|-----------|--------|--------|
| 21 fehlende Library-Felder | ✅ erledigt (WP-6, 2026-04-16) | FEATURE_FREEZE.md |
| Pine-Titel korrekt | ✅ verifiziert (WP-F, 2026-04-17) | FEATURE_FREEZE.md |
| Kein kritischer Bug offen | ⏳ laufend zu beobachten | FEATURE_FREEZE.md |

---

## 3. Was "stabil" bedeutet — und was nicht

### Stabil heißt:

- Schwellen werden über **≥ 14 Kalendertage** konsistent eingehalten
- Fehler werden **dokumentiert und diagnostiziert**, nicht versteckt
- Keine nachträgliche Absenkung von Schwellen, um ein Ergebnis zu erzwingen
- Trend ist **neutral oder fallend** (Fehlerquote sinkt oder bleibt niedrig)

### Stabil heißt NICHT:

- Ein einzelner grüner Lauf nach einer Serie von Fehlern
- Schwellen weich machen, damit ein schlechter Lauf durchgeht
- Tage ohne Läufe (Wochenende ausgenommen) als "stabil" werten
- Advisory-Warnungen ignorieren, wenn sie sich häufen

---

## 4. Beobachtete Metriken

Folgende Metriken werden pro Lauf und im Zeitverlauf erfasst:

| Metrik | Granularität | Quelle |
|--------|-------------|--------|
| Gate-Status (ok/warn/fail) | pro Run | Workflow conclusion |
| Brier Score | pro Symbol/TF/Run | Measurement evidence |
| Calibrated Brier Score | pro Symbol/TF/Run | Scoring artifact |
| ECE (raw + calibrated) | pro Symbol/TF/Run | Scoring artifact |
| Event Count | pro Family/Run | Benchmark artifact |
| Provider-Health | pro Run | Health-check report |
| Domain Visibility Score | pro Run | Evidence summary |
| Stratification Coverage | pro Run | Benchmark manifest |

---

## 5. Entscheidungsmatrix Freeze-Exit

| Zustand | Entscheidung |
|---------|-------------|
| Alle Kriterien §2 erfüllt + 14 Tage stabil | **EXIT erlaubt** |
| Kriterien erfüllt, aber < 14 Tage beobachtet | **Warten** — weiter beobachten |
| ≥ 1 Kriterium nicht erfüllt | **BLOCKIERT** — Ursache diagnostizieren |
| Schwellen nur durch Absenkung erreichbar | **Schwelle bleibt** — Fix finden oder akzeptieren |
| Einmaliger Lauf grün, Rest unklar | **Kein Exit** — kein Glücks-Run als Nachweis |

---

## 6. Final-Review-Checkliste für den letzten Freeze-Exit-Tag (WP-I)

Dieser Abschnitt definiert einen einmaligen Prüfpfad, der am letzten Tag
des Beobachtungsfensters (frühestens 2026-04-29) in einem Durchgang
ausgeführt wird. Er **bestätigt nur** — er öffnet keine neuen Arbeitspakete.

### 6.1 Prüfschritte (8 Nachweise, ~15 Minuten)

| # | Prüfung | Kommando / Quelle | Erwartet |
|---|---------|-------------------|----------|
| 1 | Library-Refresh ≥ 56 Successes | `gh run list --workflow smc-library-refresh --limit 80 --json conclusion \| jq '[.[] \| select(.conclusion=="success")] \| length'` | ≥ 56 |
| 2 | Library-Refresh keine Fehltage | Tages-Aggregation (§6.4 in stability_program.md) | 0 Fehltage |
| 3 | Deeper-Integration ≥ 80% | `gh run list --workflow smc-deeper-integration-gates --limit 40 --json conclusion` | ≥ 80% success |
| 4 | Measurement-Benchmarks ≥ 2 | `gh run list --workflow smc-measurement-benchmark --json conclusion` | ≥ 2 success |
| 5 | CI auf HEAD grün | `gh run list --workflow CI --limit 1 --json conclusion` | success |
| 6 | Test-Suite lokal grün | `python -m pytest tests/ -k smc --tb=short -q` | 0 failures |
| 7 | Kein kritischer Bug | `gh issue list --label critical --state open` | 0 issues |
| 8 | Branch-Protection-Status | `gh api repos/skippALGO/skipp-algo/rules/branches/main` | Regeln dokumentiert |

### 6.2 Copilot-Prompt für den finalen Check

```
Führe den Freeze-Exit Final-Review durch:

1. Prüfe die Pipeline-Stabilität seit 2026-04-15:
   - Library-Refresh: mindestens 56 Successes, keine vollständigen Fehltage
   - Deeper-Integration: mindestens 80% Success-Quote
   - Measurement-Benchmark: mindestens 2 erfolgreiche Reports

2. Prüfe den aktuellen CI-Status auf HEAD.

3. Führe die lokale Test-Suite aus (pytest tests/ -k smc).

4. Prüfe offene kritische Issues.

5. Prüfe den Branch-Protection-Status.

6. Erstelle den "Final Exit Assessment"-Abschnitt im freeze_exit_memo.md
   nach dem Template in freeze_exit_stability_program.md §6.3.

7. Gib eine klare Empfehlung: EXIT / VERLÄNGERN / TEILWEISE mit Begründung.

Öffne keine neuen Arbeitspakete. Bestätige nur.
```

### 6.3 Abnahmekriterien für den Final-Review

- Alle 8 Prüfschritte sind durchgeführt und dokumentiert.
- Das "Final Exit Assessment" ist im `freeze_exit_memo.md` eingetragen.
- Die Entscheidung (EXIT/VERLÄNGERN/TEILWEISE) ist begründet.
- Es wurden keine neuen WPs oder Arbeitspakete aufgespannt.

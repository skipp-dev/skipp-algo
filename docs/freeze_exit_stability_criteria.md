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

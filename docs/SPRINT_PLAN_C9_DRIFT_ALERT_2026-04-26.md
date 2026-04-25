# Sprint-Plan C9 — Drift-Alert + Anomalie-Monitoring

Datum: 2026-04-26 · Sprint-Reihe: Track-Record-Machbarkeitsplan · Aktueller Sprint: C9 von C1–C9

Evidenz-Marker: ✅ im Code belegt · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Ziel-Framework

C9 ist der letzte Sprint der Reihe. Liefert keine der neun Mindestkennzahlen direkt, sondern den **Watchdog**, der nach Track-Record-Gate-Passage erkennt, wann sich Live-Performance vom Backtest entfernt — bevor Live-Sharpe unter den 0.3-CI-Floor crasht.

C9 schließt damit die Feedback-Schleife auf: ✅ C1 (Outcomes) → ✅ C2 (WFE) → ✅ C3 (Bootstrap-CI) → ✅ C4 (Permutation) → ✅ C5 (Regime) → ✅ C6 (PSR) → ✅ C7 (Dashboard) → ✅ C8 (Live) → **C9 (Drift)**.

## Sprint-Übersicht

- **Sprint-Dauer:** 4–6 Werktage (Speed-Stack), 6–8 ohne
- **Sprint-Typ:** Greenfield-Modul (`scripts/drift_alert.py`) plus Cron-Wiring; konsumiert nur bestehende Outcome-Storage und C2-Performance-Metrics
- **Trigger:** C8 Phase-A in main, mindestens 30 Tage Live-Outcome-Daten in `artifacts/open_prep/outcomes/`
- **Definition of Done:** Wöchentlicher Cron `drift-watchdog.yml` läuft, emittiert `artifacts/drift/drift_report_<date>.json` mit `aggregate_severity ∈ {green, yellow, red}`, GitHub-Issue wird automatisch geöffnet bei `red`

## Inventur — was bereits existiert

| Komponente | Status | Pfad |
|---|---|---|
| Outcome-Storage als JSON pro Tag | ✅ | `open_prep/outcomes.py` (`OUTCOMES_DIR`) |
| Per-Trade PnL + Win-Rate | ✅ aus C1 | `open_prep/outcomes.py` |
| Per-Setup Sharpe / MaxDD / WFE | ✅ aus C2 | `scripts/performance_metrics.py` |
| KS-Test / PSI-Helpers | ❌ fehlt | — |
| Drift-Cron-Workflow | ❌ fehlt | — |
| GitHub-Issue-Auto-Open auf `red` | ❌ fehlt | — |
| `scipy.stats.ks_2samp` | ⚠ würde scipy als Hard-Dep erfordern (vermeiden) | — |

Konsequenz: C9 ist Greenfield für die Statistik (KS / PSI), aber Reuse für die Daten-Layer (C1-Outcomes, C2-Metrics).

## Tasks

### T1 — Inventur und Daten-Contract (0.5 Werktag)

- ✅ Bestätigt: `OUTCOMES_DIR` liefert `pnl_30m_pct` + `profitable_30m`
- ✅ Bestätigt: C2 `performance_metrics.compute_fold_metrics(returns)` liefert Sharpe / MaxDD / hit-rate / PF
- 📝 Festlegen: Baseline = letzte N Backtest-Folds (aus C2-WFE-Output); Live = letzte 30 Tage Outcomes
- 📝 Festlegen: Vergleichs-Metriken — `pnl`, `sharpe`, `win_rate`, `max_drawdown`, `profit_factor`

### T2 — KS + PSI Statistik-Helpers (1–2 Werktage) — **diese PR**

**Ziel:** `scripts/drift_alert.py` mit pure-stdlib + numpy.

**Akzeptanzkriterien:**

- ✅ `ks_two_sample(baseline, live) → (statistic, p_value)` — eigene KS-Implementation, kein scipy. Asymptotische p-Wert-Berechnung via Kolmogorov-Verteilungs-Reihe.
- ✅ `population_stability_index(baseline, live, *, n_buckets=10) → float | None` — Quantil-basierte Buckets, ε-Schutz gegen log(0).
- ✅ `psi_severity(psi) → "green"|"yellow"|"red"` — Standard-Bands [<0.10, 0.10-0.25, >0.25] (Siddiqi 2006).
- ✅ `rolling_drift_score(live_series, *, baseline_mean, baseline_std, window) → list[float]` — sliding |z|-Score.
- ✅ `compute_drift_report(metrics, *, p_value_yellow=0.05, p_value_red=0.01) → dict` — top-level Report mit `aggregate_severity`.

**Unabhängig von allen anderen Modulen — ship-bar bevor C8 in main.**

### T3 — Live-vs-Backtest-Watchdog-Skript (1–2 Werktage)

**Ziel:** `scripts/run_drift_watchdog.py` als CLI/Cron-Entry-Point.

- Liest `artifacts/open_prep/outcomes/outcomes_*.json` der letzten 30 Tage als Live-Sample
- Liest die in C8 verlinkte Backtest-WFE-Output-JSON als Baseline-Sample
- Ruft `compute_drift_report(...)` über alle Setup×Metric-Kombinationen
- Schreibt `artifacts/drift/drift_report_<date>.json` (atomic write)
- Stop-Kriterium: weniger als 30 Live-Trades pro Setup → `aggregate_severity = "yellow"` mit `reason = "insufficient_n"`

### T4 — GitHub-Issue-Auto-Open auf `red` (0.5 Werktag)

- `red`-Severity → `gh issue create --label drift,critical --title "Drift Alert: <metric>" --body @drift_report_<date>.json`
- Idempotenz: Title-Suffix `<date>` verhindert Duplikate pro Tag
- Closed-State-Check: gh wirft ja eh nur ein Issue pro Tag-Title

### T5 — Cron-Workflow (0.5 Werktag)

- `.github/workflows/drift-watchdog.yml`
- Cron `0 7 * * 1` (montags 07:00 UTC, 1h nach C2-WFE-Cron der dienstags läuft, zur deterministischen Inputs)
- Job-Steps: checkout → setup-python → install deps → `python scripts/run_drift_watchdog.py` → upload artifact → on red: open issue
- `continue-on-error: false` für den Watchdog selbst — wenn das Skript crasht, soll CI rot werden

### T6 — Dashboard-Integration (1 Werktag)

- C7 Dashboard liest `artifacts/drift/drift_report_*.json`
- Track-Record-Ampel-Tab zeigt Drift-Severity neben Sharpe-CI / WFE / PSR
- Im roten Zustand: Banner "Drift detected — review live vs. backtest distribution before scaling exposure"

### T7 — Test-Suite (1 Werktag)

- Unit-Tests T2-Helper (in dieser PR): KS gegen Hand-Calc, PSI grows with shift, severity-Bands
- E2E-Test T3: synthetische Outcome-JSONs simulieren Drift, prüfen `aggregate_severity == "red"`
- Determinismus: gleicher Input → identischer Report-JSON

## Stop-Kriterien

- **Stop nach T2:** Wenn KS / PSI bei Hand-validierten Beispielen falsche Werte liefern → eigene Implementation aufgeben, optional `scipy.stats` als Optional-Dependency aufnehmen
- **Stop nach T3:** Wenn Live-Outcomes-Verzeichnis weniger als 30 Tage abdeckt → C9 wartet auf C8 Phase-A
- **2-Iterations-Limit pro Task** wie in C1-C8

## Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| KS-p-Value fehlt scipy-Präzision | mittel | niedrig | für n>50 ist die asymptotische Form genau genug; Stop-Kriterium T2 deckt Edge-Cases |
| Falsch-positive Drift bei Regime-Wechsel | hoch | mittel | C5-Regime-Stratifikation pro-Regime-Vergleich nutzen, sobald in main |
| Issue-Spam bei dauerhaft rot | mittel | niedrig | Idempotenz via Title-Datum, plus manueller Mute-Switch via repo-secret |
| Cron läuft, aber kein Reviewer reagiert | hoch | hoch | Slack-/Discord-Webhook-Stretch in T4, plus Phase-Gate-Doc in C8 verlinkt |

## Speed-Erwartung

| Setup | Realistische Dauer |
|---|---|
| Ohne Speed-Stack | 6–8 Werktage |
| Mit KI-Repo-Tool und pytest-xdist | 4–6 Werktage |
| Plus Reuse von ✅ `compute_fold_metrics` aus C2 | unverändert (war bereits eingeplant) |

## Definition of Done — Sprint C9

- ✅ `scripts/drift_alert.py` und `scripts/run_drift_watchdog.py` existieren
- ✅ Wöchentlicher Cron `drift-watchdog.yml` läuft 1× erfolgreich durch
- ⚙️ Mindestens 1 `artifacts/drift/drift_report_*.json` ist commit-fest archiviert
- 🧪 Test-Suite läuft mit `pytest -n auto`, alle T7-Tests grün
- ⚙️ PR ist gemerged
- ⚙️ C7 Dashboard zeigt Drift-Severity (T6 — Stretch falls C7 noch nicht in main)

## Übergabe an Folge-Sprints

C9 ist der letzte Sprint der C-Reihe. Folge-Sprints (D-Reihe) wären: D1 Multi-Strategie-Portfolio, D2 Risk-Budgeting, D3 Live-Re-Calibration. Diese sind nicht Teil des Track-Record-Machbarkeitsplans.

## Quellen

- Kolmogorov-Smirnov-Test: <https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test>
- Siddiqi (2006), *Credit Risk Scorecards* — PSI-Bands [<0.10, 0.10-0.25, >0.25]
- Lopez de Prado (2018), *Advances in Financial Machine Learning*, ch. 17 (Microstructural Drift)

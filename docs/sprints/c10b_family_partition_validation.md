# C10b — Family-Partition-Validation

**Datum:** 2026-05-13
**Branch (geplant):** `sprint/c10b-family-partition-validation`
**Status:** Antrag + Status-Anker (Analyse, keine Code-Änderung an `ml/`, `rl/`, oder Promotion-Gate)
**Sprache:** Deutsch
**Vorgänger im Kontext:** C10 (`docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`), C8 (`docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md`), C12 (`docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md`)
**Dieser Sprint ist Voraussetzung für:** jede weitere Code-Arbeit in `ml/`, `rl/`, oder am Promotions-Gate — die hier zu beantwortende Frage entscheidet, ob die heutige Per-Familie-Architektur korrekt ist.

---

## Hauptziel (verbatim, nicht zu paraphrasieren)

> **"Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt — dann habe ich nichts zu verkaufen."**
>
> Genau das ist der Vertrag, den die Methodik mit dem Geschäft schließt. Kein "vielleicht", kein "das wird schon", sondern: **Beweise oder kein Verkauf.**

Jede Antwort, jeder Plan, jeder Sprint dient diesem Ziel. Wenn ein Vorschlag sich entfernt, ist er falsch.

---

## Die offene Frage, die diesen Sprint auslöst

**C10 hat festgelegt** (`SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md` Methoden-Foundation Phase A): _"Vier separate Klassifikatoren, einer pro Familie. Bewusst keine gemeinsame Multi-Task-Architektur — Familien sind unterschiedliche statistische Populationen."_

**Code-Konsequenzen** (heute im Repo):
- `ml/training/xgb_family_trainer.py` + `ml/training/lgbm_family_trainer.py` — vier separate Modelle
- `scripts/run_smc_live_incubation.py:125-149` `PHASE_B_CRITERIA` — `min_phase_days=90`, `min_trades_closed=30` **pro Familie**
- `scripts/check_c12_trigger.py:15` _"requires per family all of"_ (90 days, 30 trades, 0 kill-switch, drift pass)
- `docs/calibration/calibration_report_public.json` mit `family_weights` als zentraler Datenstruktur

**Aktueller Track-Record-Status** (2026-05-13, gemessen):
```
$ python scripts/check_c12_trigger.py
{
  "status": "BLOCKED",
  "families_evaluated": 0,
  "families_live_qualified": 0,
  "reasons": ["no family satisfied all gate criteria", "families inspected: 0"]
}
```

`docs/calibration/calibration_report_public_history.jsonl` (8 Einträge): durchgehend `n_events: null`, `weighted_hit_rate: null`, `family_weights: {}`.

**Die Hypothese "vier disjunkte Populationen" wurde nie empirisch validiert.** Sie steht als Designentscheidung im Plan und ist als Constraint hart in den Code geschrieben. Wenn diese Hypothese falsch ist — wenn BOS, OB, FVG, SWEEP also verschiedene Beobachtungs-Linsen auf dasselbe Marktphänomen sind statt vier disjunkter Populationen — dann produziert die heutige Architektur **künstlich** 4× Wartezeit (jede Familie muss 90 Tage × 30 Trades einzeln erreichen), 4× Multiple-Testing-Korrektur (BH-FDR über vier Familien), 4× Refit-Compute, und sie verteilt die Evidence statt sie zu bündeln.

**Beobachtbarer Bias-Hinweis aus vorhandenen Daten:** In `artifacts/reports/zone_priority_contextual_calibration.json` sind die Hit-Rates pro Familie pro Kontext-Bucket bereits dokumentiert. Im BEARISH-HTF-Bias-Bucket: OB 333 Events / 37.84% Hit, FVG 1723 Events / 55.77%, BOS 494 Events. Stark unterschiedliche Frequenzen und Hit-Rates — aber ohne den Co-Firing-Test ist nicht entscheidbar, ob das Beweis für Disjunktheit oder Artefakt unterschiedlicher Detektor-Empfindlichkeit ist.

---

## Was dieser Sprint liefert

**Keine Code-Änderung an `ml/`, `rl/`, oder Promotion-Gate.** Diagnostik.

Eine datengestützte Entscheidung zwischen fünf Architektur-Optionen:

| Option | Beschreibung | Wann gewinnt sie |
|---|---|---|
| **Beibehalt** | Vier separate Klassifikatoren wie heute | Co-Firing < 5%, Outcome-Korrelation < 0.2, hohe Feature-Divergenz |
| **A — Pooled** | Strategie-Level-Promotion, family_id als Feature, ein Gate (`120 trades × 90 days` aggregiert) | Co-Firing hoch, Outcome-Korrelation hoch, Features ähnlich |
| **B — Hierarchical Bayes** | Partial Pooling mit globalem Prior + familien-spezifischer Abweichung | Mittlere Korrelation, statistisch saubere Antwort gewünscht, MCMC-Budget vorhanden |
| **C — Single MoE-Modell** | Ein LightGBM mit family_id als kategorischem Feature + Interaktionen | Pragmatischer Mittelweg, behält 95% der heutigen Toolchain |
| **D — Regime-Schnitt statt Familien-Schnitt** | Promotion pro Regime über Familien gepoolt | Wenn die Edge-Quelle das Regime ist, nicht die Familie |

Die Entscheidung erfolgt nach Auswertung der drei unter Methodik genannten Analysen, eingetragen am Ende dieses Dokuments unter "Entscheidung + Begründung".

---

## Methodik

Drei Analysen auf dem vorhandenen Event-Ledger (`smc_core/event_ledger.py` Schema, JSONL-Format `events_<SYMBOL>_<TIMEFRAME>.jsonl`):

### 1 — Co-Firing-Matrix

Auf wie vielen `(symbol, timeframe, bar_timestamp)` feuern jeweils 1 / 2 / 3 / 4 Familien? Ausgegeben als Häufigkeitstabelle plus Anteile am Gesamt-Event-Volumen.

- **Schwelle für "Beibehalt"-Tendenz:** Mehrfach-Firing < 5%
- **Schwelle für "Pooling"-Tendenz:** Mehrfach-Firing > 20%

### 2 — Outcome-Korrelation auf Co-Firing-Bars

Auf den Bars mit ≥ 2 Familien gleichzeitig: paarweise Korrelation der Outcome-Labels (TP-Hit vor SL-Hit). Cramér's V für binäre × binäre, gemessen pro Familien-Paar.

- **Schwelle für "Beibehalt"-Tendenz:** alle paarweisen V < 0.2
- **Schwelle für "Pooling"-Tendenz:** mindestens ein paarweises V > 0.5

### 3 — Feature-Divergenz auf Solo-Firing-Bars

Auf den Bars, wo genau eine Familie feuert: Population-Stability-Index pro Feature zwischen den vier Solo-Populationen (BOS-only, OB-only, FVG-only, SWEEP-only). Berücksichtigt nur Features, die in allen vier Populationen vorhanden sind (mindestens 100 Events pro Population).

- **Schwelle für "Beibehalt"-Tendenz:** Median-PSI über Features > 0.25 (deutlich unterschiedliche Verteilungen)
- **Schwelle für "Pooling"-Tendenz:** Median-PSI < 0.10 (vergleichbare Verteilungen)

### Entscheidungslogik

Drei Ja/Nein-Antworten ergeben einen Empfehlungs-Vektor. Konsens → klare Empfehlung. Mischbild → Schnitt C (MoE) als pragmatischer Default, weil er empirisch entscheidet, wie viel Familien-Spezifik nötig ist.

---

## Schritte + Status

| # | Schritt | Status | Datum | Output |
|---|---|---|---|---|
| 0 | Diese Doc anlegen, committen, pushen | ☑ | 2026-05-13 | `docs/sprints/c10b_family_partition_validation.md` (PR #2196) |
| 1 | Event-Ledger-Snapshot lokalisieren oder Pipeline-Lauf anstoßen (`events_*.jsonl`) | ☑ | 2026-05-13 | Status-Block-Eintrag "Event-Ledger-Lokalisierung (Schritt 2a)" unten. Findings: SMC-Live-Ledger leer, Open-Prep-Ledger gefüllt (235 Records, 7 Tage, 63 % Hit-Rate), Variant-Family-Map enthält 1 Eintrag |
| 2 | Co-Firing-Matrix berechnen | ☐ | | `docs/research/c10b/co_firing_matrix.json` + Tabelle in dieser Doc |
| 3 | Outcome-Korrelation auf Co-Firing-Bars | ☐ | | `docs/research/c10b/cramers_v_pairwise.json` |
| 4 | Feature-Divergenz (PSI) auf Solo-Firing-Bars | ☐ | | `docs/research/c10b/feature_psi_per_family.json` |
| 5 | Architektur-Entscheidung treffen, in dieser Doc unter "Entscheidung + Begründung" eintragen | ☐ | | dieser Abschnitt unten |
| 6 | Falls Entscheidung ≠ Beibehalt: Folge-Sprint C10c als separate Doc skizzieren | ☐ | | `docs/sprints/c10c_<entscheidung>_migration.md` |

---

## Voraussetzung: Cron-Brücke

Die hier genutzten Analysen brauchen einen aktuellen Event-Ledger. Der tägliche Cron `smc-databento-production-export.yml` ist seit 2026-05-11 in 5 aufeinanderfolgenden Runs an einem Workbook-Write-OOM gescheitert (Profil in `/tmp/prod_export_audit/PROFILE_DATA.md`, 4 offene Fragen beantwortet in `/tmp/prod_export_audit/OPEN_QUESTIONS_ANSWERS.md`). Solange dieser Cron rot ist, kommt kein frisches Daten-Material. **Cron-Brücke wird vor Schritt 1 erledigt** als separater 1-Tages-Eingriff (Lösungsraum dokumentiert in `/tmp/prod_export_audit/SOLUTION_SPACE.md`).

---

## Status-Block — Hier kommen Zwischenergebnisse rein

_Dieser Block wird bei jedem Folge-Run ergänzt, nicht überschrieben. Datum als Header pro Eintrag._

### 2026-05-13 — Initial-Anlage
- Doc angelegt als Status-Anker
- Memory-Anker gesetzt (Hauptziel + offene Architekturfrage)
- C12-Trigger-Gate-Check ausgeführt: `BLOCKED`, 0 Familien evaluiert
- Vorhandene Daten in `artifacts/reports/zone_priority_contextual_calibration.json` zeigen Per-Bucket-Hit-Rates pro Familie, aber kein Co-Firing-Material
- Event-Ledger-Pfad noch zu lokalisieren (`events_*.jsonl` nicht im Workspace gefunden)

### 2026-05-13 (Abend) — Event-Ledger-Lokalisierung (Schritt 2a)

**Was wir gesucht haben:** Den persistenten Strom "welches Setup hat gefeuert — welche Familie — welcher Outcome", auf dem Co-Firing, Outcome-Korrelation und Feature-PSI gerechnet werden.

**Was wir gefunden haben:**

1. **Ein erwarteter, aber leerer Pfad: SMC-Live-Incubation-Ledger (Phase-B-Pipeline).**
   - **Producer:** `scripts/run_smc_live_incubation.py` — schreibt ein JSONL pro Submit/Fill (Felder: `ts`, `phase`, `intent_id`, `variant`, `symbol`, `action`, `entry_price`, `stop_loss`, `take_profit`, `quantity`, `size_scale`, `fill_price`, `kill_switch_triggered`; bei Earnings-Block zusätzlich `earnings_filter`).
   - **Outcome-Stamper:** `scripts/backfill_live_outcomes.py` — schreibt nachgelagert `outcome_pnl_usd` und `outcome_r_multiple` auf bereits geschlossene Trades in dieselbe JSONL-Zeile.
   - **Family-Aggregator:** `scripts/build_families_telemetry.py` — mappt `variant` → Familie über `configs/c13/variant_family_map.json`, rollt zu `families[{name, live_days, n_trades, kill_switch_fires, drift_verdict}]` auf. Family-Vokabular hart gepinnt: `("BOS", "OB", "FVG", "SWEEP")`.
   - **Geplanter On-Disk-Pfad:** `cache/live/incubation_<date>.jsonl` (gesetzt in der Doc von `backfill_live_outcomes.py`).
   - **Realität auf Hauptbranch (`main` HEAD `2a82ad5e`):** `cache/` existiert nicht im Repo, **kein einziges `incubation_*.jsonl` vorhanden, weder im Workspace noch unter `artifacts/`**. Der C8-Phase-B-Live-Cron hat also bisher **null Records** produziert. Genau deshalb meldet `check_c12_trigger.py` 0 evaluierte Familien.
   - **Die Variant-Family-Map ist eine 1-Eintrag-Datei.** `configs/c13/variant_family_map.json` enthält heute exakt `{"smc_breaker_btc": "BOS"}`. Selbst wenn der Live-Cron Daten produzieren würde, würden 3 von 4 Familien (OB/FVG/SWEEP) leer bleiben und der Phase-B-Gate würde nie aufgehen. Das ist nicht "Hypothese, die zu validieren ist" — das ist eine **leere Hypothese**.

2. **Ein unerwarteter, aber gefüllter Pfad: Open-Prep-Feature-Importance-Ledger.**
   - **Pfad:** `artifacts/open_prep/outcomes/feature_importance/fi_samples_<date>.jsonl`
   - **Volumen:** 7 Tage (2026-04-30, 05-04, 05-05, 05-06, 05-08, 05-11, 05-12), **235 Records total**, ~30–40 pro Tag.
   - **Outcome-Label vorhanden:** `profitable_30m` (148 wahr / 87 falsch, **63,0 % Hit-Rate**), `pnl_30m_pct`.
   - **Feature-Spalten pro Record:** `total_score`, `confidence_tier` (heute alle `STANDARD`), `gap_component`, `gap_sector_rel_component`, `rvol_component`, `macro_component`, `momentum_component`, `hvb_component`, `earnings_bmo_component`, `news_component`, `ext_hours_component`, `analyst_catalyst_component`, `vwap_distance_component`, `freshness_component`, `institutional_component`, `estimate_revision_component`, `zone_priority_score`.
   - **Fehlt:** Family-Tag oder Variant-Schlüssel — dieser Strom ist eine Open-Prep-Setup-Ledger, kein SMC-Live-Setup-Ledger. Eine Family-Attribution ließe sich nur über `zone_priority_score`-Bucketing nachreichen, nicht 1:1 mappen.
   - **Producer-Bug gefunden** (Nebenbefund, nicht Teil dieses Sprints): **Alle 14 Komponenten-Felder sind in allen 235 Records exakt `0.0`** — selbst bei `total_score=22.05` und `zone_priority_score=61`. Root Cause: `open_prep/outcome_backfill.py::backfill_feature_importance()` (Zeilen 320–346) liest `rec.get("gap_component", 0.0)` aus dem Raw-Outcome-File (`outcomes_<date>.json`). Die Raw-Datei enthält aber `gap_pct`, `rvol`, `score`, `regime` (Roh-Observables) und **keine** `*_component`-Schlüssel (jene werden erst in `open_prep/scorer.py::score_candidate()` als gewichtete Komponenten gebildet und nicht persistiert). Das `score_breakdown` wird also nie in das `outcomes_<date>.json` geschrieben, der Backfill findet die Schlüssel nicht, defaultet jeden auf 0, und das fi_samples-JSONL ist seit Wochen ein konsistent kaputter Strom. Ticket-Kandidat, nicht Teil dieser Doc.

3. **Weitere kandidatische Ledger ohne Outcome-Verknüpfung:**
   - `docs/calibration/calibration_report_public_history.jsonl` — 8 Einträge, **alle leer** (`families: []`), bestätigt direkt den Phase-B-Hunger.
   - `artifacts/reports/zone_priority_calibration_history.jsonl` — 1 Eintrag, Aggregat ohne Per-Setup-Granularität.
   - `docs/ab/g23_history.jsonl` — 0 Zeilen.

**Implikation für Schritt 2b–2d:**
- Die 4-Familien-Partition kann auf Echtdaten **nicht** validiert werden, solange `variant_family_map.json` nur eine Variante kennt und der Live-Cron 0 Records hat. Selbst nachdem die Cron-Brücke #2197 gemergt ist und die Producer-Cron wieder grün wird, **liefert die Open-Prep-Pipeline kein SMC-Setup-Material** — sie liefert Open-Prep-Setup-Material. Das ist eine zusätzliche Inkongruenz, die explizit dokumentiert werden muss, bevor die nächste Stufe Sinn ergibt.
- Der vorläufige Plan, die 235 Open-Prep-Records als **Methodik-Proxy** zu nutzen (Co-Firing/Outcome/PSI auf den 14 Komponenten-Scores als Stand-in für die 4 SMC-Familien), **fällt zurück auf null**, weil alle 14 Komponenten in allen 235 Records exakt 0 sind (siehe Nebenbefund oben). Bevor die Open-Prep-Daten als Proxy taugen, muss der Backfill-Bug behoben werden — das ist eine **eigene Vorbedingung**, kein eigenständiger Sprint-Schritt.
- Das verbleibende Material für eine analyseseitige Prüfung ist heute: `total_score` (variiert 0.22–23.58), `zone_priority_score` (0–61), `profitable_30m` (63 % Hit-Rate), `pnl_30m_pct`. Mit nur zwei kontinuierlichen Features lassen sich Co-Firing und PSI nicht sinnvoll rechnen — die Methodik braucht eine **Familien-ähnliche kategoriale Achse**, und die existiert auf diesem Stream nicht.
- **Konsequenz für den Sprint:** Schritt 2b–2d (Co-Firing-Matrix, Outcome-Korrelation, PSI) können heute auf keinen verfügbaren Echtdatensatz angewendet werden. Die Analyse ist **datenseitig blockiert** — nicht durch fehlende Mathematik, sondern durch fehlende Daten + zwei Producer-Probleme (`variant_family_map.json` 1-Eintrag-File + `outcome_backfill.py` Schlüssel-Mismatch).
- **Ehrliches Verdict zum Zeitpunkt 2026-05-13:** Wir kennen den Lieferpfad. Wir kennen die Schemata. Wir kennen das Hauptziel. Aber **bis zum nächsten grünen Producer-Cron-Lauf + bis Producer-Probleme adressiert sind, ist Schritt 2b–2d eine Trockenrechnung**. Wir halten das offen statt es mit synthetischen Daten zu kaschieren. Das passt zur Disziplin-Regel "Wenn etwas schief geht, fängt die KI an zu lügen. Das brauche ich nicht."

**Beziehung zum Hauptziel:** Bevor wir behaupten, die Track-Record-Methodik könne profitable Setups beweisen, müssen wir zugeben, dass die Datenpipeline **heute nichts beweisen kann** — ein Eintrag im Family-Mapping, null geschriebene Incubation-Records. Das ist eine ehrliche Bestandsaufnahme, kein Buzzword-Kaskaden-Versuch.

**Referenz-PRs:**
- #2196 (diese Doc — Status-Anker)
- #2197 (Cron-Brücke 1c — Voraussetzung für frische Producer-Daten, CI läuft)

---

## Entscheidung + Begründung

_Wird ausgefüllt nach Abschluss Schritte 1-4. Bis dahin: offen._

**Empfohlene Option:** _(offen)_
**Drei Analyse-Ergebnisse:** _(offen)_
**Begründung:** _(offen)_
**Konsequenzen für `ml/`, `rl/`, Promotion-Gate, C8-Phase-B-Kriterien:** _(offen)_

---

## Was dieser Sprint explizit nicht ist

- Kein Code-Refactor in `ml/training/`
- Kein neuer ML-Klassifikator
- Keine Änderung am C8-Runbook
- Keine Änderung am Promotions-Gate (`smc_integration/release_policy.py`)
- Keine Workflow-Änderung außer der separat dokumentierten Cron-Brücke

Wenn die Analyse "Beibehalt" empfiehlt, bleibt der ganze heutige Code unverändert. Das ist ein gültiges Outcome.


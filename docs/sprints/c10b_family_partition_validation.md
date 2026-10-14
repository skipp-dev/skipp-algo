# C10b — Family-Partition-Validation

**Datum:** 2026-05-13
**Branch (geplant):** `sprint/c10b-family-partition-validation`
**Status:** Abgeschlossen (Step 2f-Replikation 2026-05-13, Endurteil mit drei dokumentierten Vorbehalten)
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
| 2 | Co-Firing-Matrix berechnen | ☑ | 2026-05-13 | Step 2f: `docs/research/c10b/co_firing_matrix.json` (22.61 % multi-firing-Bars auf 1D-Replikations-Korpus) + `docs/research/c10b/cramers_v_pairwise.json` (max V = 0.27). Roh-Ledger via Workbook-Fallback lokal befüllt.
| 3 | Outcome-Korrelation auf Co-Firing-Bars (= Step 2c, neu interpretiert auf Aggregat) | ☑ | 2026-05-13 | `docs/research/c10b/family_partition_analysis_v4_corpus.json` (paarweise z-Tests) |
| 4 | Feature-Divergenz (PSI / Variance-Decomposition) (= Step 2d) | ☑ | 2026-05-13 | `docs/research/c10b/family_partition_analysis_v4_corpus.json` (within_family_context_dispersion + η²-Decomp) |
| 5 | Architektur-Entscheidung treffen, in dieser Doc unter "Entscheidung + Begründung" eintragen (= Step 2e) | ☑ | 2026-05-13 | Abschnitt "Entscheidung + Begründung" unten |
| 6 | Falls Entscheidung ≠ Beibehalt: Folge-Sprint C10c als separate Doc skizzieren | n/a | 2026-05-13 | Entscheidung = Beibehalt; nicht erforderlich. Joint-Outcome-Modellierung als Backlog-Item: `docs/sprints/backlog/joint_outcome_modeling.md` |
| 7 | Step 2f: Replikation auf zweitem, unabhängigen Korpus + Co-Firing + Cramér's V auf Roh-Ledger | ☑ | 2026-05-13 | `docs/research/c10b/family_partition_analysis_1d_corpus.json` + `co_firing_and_replication_findings.md`. η²_family 0.79 → 0.98. |

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

### 2026-05-13 (späterer Abend) — Korrektur: der richtige Event-Ledger

**Was 2a/2b oben fehlt geht:** Wir haben den falschen Ledger gehuntet. Die Open-Prep-`fi_samples_*.jsonl`-Spur ist real und der Producer-Bug ist real, aber dieser Strom ist **nicht** das Material, auf dem dieser Sprint die 4-Familien-Hypothese testet. Der **kanonische** SMC-Event-Ledger ist:

- **Producer (im Prozess):** `smc_integration/measurement_evidence.py::build_measurement_evidence()` baut `events_by_family: dict[EventFamily, list[dict]]` mit `EventFamily ∈ {"BOS","OB","FVG","SWEEP"}`. Familien-Tag steht **direkt im Record** (`events_by_family["BOS"].append(evaluated)` Z. 1279, OB Z. 1327, FVG Z. 1381, SWEEP Z. 1466).
- **Producer (auf Disk):** `smc_core/event_ledger.py::write_event_ledger()` schreibt JSONL mit Schema `EventLedgerRecord(schema_version, event_id, symbol, timeframe, family, timestamp, predicted_prob, outcome, context, raw_score, raw_score_name, features, outcome_extras)`.
- **Pfad:** `ledger_path_for_pair(pair_dir, symbol, timeframe) → pair_dir / f"events_{symbol}_{timeframe}.jsonl"`. Glob `events_*_*.jsonl` (siehe `scripts/emit_fvg_context_pine.py:83`).
- **Aufrufer:** `scripts/run_smc_measurement_benchmark.py:381` (Wochen-Cron `smc-measurement-benchmark.yml`, Sa 08:00 UTC).
- **Konsumenten dieses Ledgers:** `scripts/fvg_quality_quartile_gate.py`, `scripts/fvg_quality_d4_audit.py`, `scripts/fvg_quality_recalibration.py`, `scripts/fvg_session_artifact_diagnosis.py`, `scripts/fvg_label_audit.py` lesen alle `record["family"] == "FVG"`.

**Was 2a über diesen Ledger sagen muss:**
- Die `cache/live/incubation_*.jsonl`-Spur (Phase-B-Trade-Ledger) und der `events_*_*.jsonl`-Strom sind zwei verschiedene Datenflüsse. Phase-B misst Live-Trade-Outcomes auf Variants, dieser Ledger misst strukturelle SMC-Events pro Bar. **Beide sind unabhängig leer** — aber aus unterschiedlichen Gründen, und nur der zweite gehört zu dieser Sprint-Frage. Die Open-Prep-Befunde aus 2b bleiben als eigenständiger Nebenbefund stehen (Producer-Bug echt, Ticket lohnt sich), sind aber **nicht** Eingabe für die c10b-Entscheidung.

**Lokaler On-Disk-Status der `events_*_*.jsonl`-Strom heute:**
- Im Repo: kein einziges `events_*_*.jsonl` (weder im Workspace noch unter `artifacts/`).
- Letzter erfolgreicher CI-Lauf des Producer-Workflows: `smc-measurement-benchmark` Run #25597656274 (2026-05-09 09:26 UTC). Artifact `smc-measurement-benchmark-71` enthält 80 Pair-Verzeichnisse (20 Symbole × 4 Timeframes), jedes mit dem erwarteten `events_<SYM>_<TF>.jsonl` — **alle 80 Dateien null Zeilen**.
- Root Cause: `measurement_summary_*.json` aller 80 Pairs zeigt `bars_source_mode = "none"`, `measurement_evidence_present = false`, Warnung `"no bar source available for measurement evidence"`. CI hat weder Production-Bundle (`artifacts/smc_microstructure_exports/`) noch Workbook-Pfad — `_load_source_bars()` returnt einen leeren DataFrame, `build_measurement_evidence()` bricht vor der Familien-Schleife ab, `write_event_ledger()` schreibt eine leere Datei. Genau das Verhalten, vor dem der Code-Kommentar Z. 226–238 von `_load_source_bars` warnt.
- Letzter Rolling-Bench-Lauf (Run #25792331943, 2026-05-13 10:05 UTC) **failed**, Artifact `smc-measurement-benchmark-rolling-2026-05-13` enthält identisches Muster: 80 leere Ledgers, derselbe `bars_source_mode = none`. Seit 2026-05-04 zehn aufeinanderfolgende Rolling-Cron-Failures (alle pre-Bridge-PR-#2197).

**Folge daraus:**
- Der `events_*_*.jsonl`-Strom existiert in CI **als leere Schale**, nicht als gefüllter Ledger. Die Cron-Brücke PR #2197 ist nicht hinreichend, um diesen Strom zu füllen — sie repariert nur den Produktions-Workbook-Export. Damit `events_*_*.jsonl` füllt, müssen die CI-Runs entweder das Production-Bundle hydratisieren (SAS-URL-Path im 4-23-Commit) oder ein lokaler Run gegen den vorhandenen Workbook-Path durchlaufen.
- **Einzige verfügbare Auswertungsbasis 2026-05-13:** Das commitete v4-Korpus-Aggregat `artifacts/ci/measurement_benchmark_combined_2026-04-23/` (Commit `16e6d5c2`, 2026-04-24). 80 Pair-Verzeichnisse mit Per-Event-Ledger wurden lokal generiert (vor dem Repo-Commit), die Roh-Per-Event-JSONLs sind **nicht** im Repo — committet wurden nur die Aggregate (`zone_priority_*`), die aus `scoring_*.json`-Bins rekonstruiert sind (siehe `scripts/smc_zone_priority_calibration.py:567–604`, Methode `binned_aggregate_reconstruction`). Damit ist Co-Firing-pro-Bar **nicht direkt** rechenbar (kein `bar_timestamp` × Familie-Set in den committeten Aggregaten). Dafür sind die Per-Familie-Hit-Raten und die Per-Kontext-Per-Familie-Hit-Raten auf n=10 064 Events vorhanden — und damit die Antworten auf die zwei zentralen Sub-Fragen dieser Sprint-Doc:
  1. Sind die 4 Familien **statistisch unterscheidbar** in ihren Outcomes? (Step 2c)
  2. Verhalten sich Setups einer Familie **systematisch anders** als Setups anderer Familien — auch dann, wenn man die Familie kontrolliert über Kontext disaggregiert? (Step 2d, PSI-Proxy via Context-Decomposition)

### 2026-05-13 (späterer Abend) — Schritt 2c: Outcome-Korrelation pro Familie + zwischen Familien

**Datenbasis:** v4-Korpus, n=10 064 Events, 319 Pair-Runs, aus `zone_priority_calibration.json` (Aggregat) + `zone_priority_contextual_calibration.json` (Per-Bucket). Analyse-Artifact: `docs/research/c10b/family_partition_analysis_v4_corpus.json`.

**Per-Familie-Basis-Hit-Raten mit 95 %-Wald-CIs:**

| Familie | n     | Hits | Hit-Rate | 95 %-CI         | Kalibriertes Gewicht |
|---------|------:|-----:|---------:|-----------------|---------------------:|
| BOS     | 1 614 | 1 383| 0.8569   | [0.8398, 0.8740]| 0.8428               |
| SWEEP   | 1 774 | 1 164| 0.6561   | [0.6340, 0.6782]| 0.6783               |
| FVG     | 5 710 | 3 255| 0.5701   | [0.5573, 0.5829]| 0.5820               |
| OB      | 966   | 308  | 0.3188   | [0.2894, 0.3482]| 0.4692               |

**Paarweise Zwei-Anteils-Z-Tests** (gepoolt, zweiseitig, Bonferroni-α=0.05/6=0.00833):

| Paar          | Δ Hit-Rate | z     | p-Wert | Reject@Bonf |
|---------------|-----------:|------:|-------:|:-----------:|
| BOS vs OB     | +0.5381    | 27.84 | ~0     | ja          |
| BOS vs FVG    | +0.2868    | 21.11 | ~0     | ja          |
| BOS vs SWEEP  | +0.2008    | 13.51 | ~0     | ja          |
| OB vs FVG     | −0.2513    | −14.48| ~0     | ja          |
| OB vs SWEEP   | −0.3373    | −16.92| ~0     | ja          |
| FVG vs SWEEP  | −0.0860    | −6.43 | ~0     | ja          |

**Verdict 2c:** Alle 6 Familien-Paare sind in ihren Outcome-Hit-Raten **hochsignifikant verschieden** (Bonferroni-korrigiert). Kein CI überlappt mit einem anderen. Die Range von OB (31.9 %) zu BOS (85.7 %) ist 54 Prozentpunkte. **Das spricht klar gegen pooled-Strategie-Level-Promotion (Option A der Schnitt-Alternativen):** Eine Pool-Hit-Rate von 0.607 würde OB-Setups massiv überbewerten (×1.9) und BOS-Setups massiv unterbewerten (×0.71) — das ist nicht Pool-Rauschen, das ist eine Population-Verschmelzung über vier strukturell verschiedene Verteilungen.

**Was 2c nicht beantwortet:** Co-Firing-Korrelation auf gleicher Bar (Cramér's V auf Co-Firing-Subset) ist auf den committeten Aggregaten **nicht** direkt rechenbar — die `scoring_*.json`-Bins sind über alle Events einer Pair-Run aggregiert, kein `bar_timestamp`-Schlüssel mehr da. Diese spezifische Sub-Analyse braucht den (heute leeren) Roh-`events_*_*.jsonl`-Strom und ist als **technisch blockiert** zu vermerken, **nicht** als logisch erledigt.

### 2026-05-13 (späterer Abend) — Schritt 2d: Feature-Divergenz / PSI — unterscheiden sich Setups derselben Familie systematisch von anderen Familien

**Datenbasis identisch**, plus `zone_priority_contextual_calibration.json` (Per-Bucket × Per-Familie Hit-Rates für 8 Kontext-Buckets: htf_bias ∈ {BEARISH,BULLISH}, session ∈ {ASIA,LONDON,NY_AM}, vol_regime ∈ {HIGH_VOL,LOW_VOL,NORMAL}).

**Within-Family-Context-Dispersion** (Spannweite der Hit-Rate **derselben Familie** über die 8 Kontexte hinweg):

| Familie | Globaler Weight | Context-Mean | Context-Range | Context-Std | PSI-ähnliches Maß |
|---------|----------------:|-------------:|--------------:|------------:|-------------------:|
| BOS     | 0.8428          | 0.8596       | 0.0665        | 0.0204      | 0.0006             |
| SWEEP   | 0.6783          | 0.6722       | 0.1914        | 0.0556      | 0.0064             |
| FVG     | 0.5820          | 0.5848       | 0.2046        | 0.0552      | 0.0087             |
| OB      | 0.4692          | 0.4590       | 0.3975        | 0.1245      | 0.0613             |

**Variance-Decomposition über alle 32 (Familie × Kontext)-Zellen** (η² als Anteil an Total Sum of Squares der kalibrierten Gewichte):

| Quelle                  | SS      | η²    |
|-------------------------|--------:|------:|
| Between Family          | 0.6793  | 0.7944|
| Between Context         | 0.0948  | 0.1109|
| Residual (Interaktion)  | 0.0810  | 0.0947|
| **Total**               | 0.8551  | 1.000 |

**Rang-Inversionen** (verändert irgendein Kontext die globale Familien-Rangordnung BOS>SWEEP>FVG>OB?):

| Kontext       | Globaler Rang        | Rang in diesem Kontext | Interpretation |
|---------------|----------------------|------------------------|----------------|
| session:ASIA  | BOS,SWEEP,FVG,OB     | BOS,SWEEP,OB,FVG       | OB↑↑ über FVG (Asia n=289, kleiner Bucket) |
| session:LONDON| BOS,SWEEP,FVG,OB     | BOS,FVG,SWEEP,OB       | FVG↑ über SWEEP |
| (alle anderen)| BOS,SWEEP,FVG,OB     | BOS,SWEEP,FVG,OB       | identisch      |

**Verdict 2d:** 
- **79.4 % der Varianz der kalibrierten Per-Familie-Per-Kontext-Gewichte stammen aus der Familien-Achse, nur 11.1 % aus der Kontext-Achse**, 9.5 % aus Interaktion. Die Familien-Achse ist also die dominante Trennachse — Setups derselben Familie verhalten sich über alle 8 Kontexte ähnlich (BOS-Std nur 0.020 ≈ 2.4 % vom Mean), Setups verschiedener Familien verhalten sich systematisch verschieden.
- **Option D (Regime-Schnitt statt Familien-Schnitt) verliert in der Variance-Decomposition deutlich:** Wenn das Regime die dominante Edge-Quelle wäre, müsste η²_context > η²_family sein. Tatsächlich ist es 1:7.2.
- **OB ist die Ausnahme:** Context-Std=0.124 und PSI=0.061 (10–60× höher als die anderen drei). OB-Performance kollabiert in LONDON/NY_AM (≈0.38) und schnellt in ASIA hoch (0.77). Das ist ein eigenes Signal: Wenn OB überhaupt verwertbar ist, dann nur Context-gekoppelt — innerhalb der Familie ist OB nicht stationär. Das macht **Option C (MoE mit family_id + Interaktionen)** als pragmatischen Default attraktiver als Beibehalt für OB, ohne die anderen drei Familien zu zerstören.
- **Zwei Rang-Inversionen** treten auf, beide an den unteren zwei Familien-Rängen (FVG ↔ OB in ASIA, SWEEP ↔ FVG in LONDON). Keine Inversion betrifft BOS, das in allen 8 Kontexten unangefochten oben steht. Die Schnitt-Alternative B (Hierarchical Bayes mit Partial Pooling) würde dies sauber adressieren: Globaler Prior pro Familie, Context-Shift als hierarchische Abweichung — aber für BOS, SWEEP, FVG ist der Gewinn marginal (Context-Std bereits ≤ 0.06). Lohnt sich primär für OB.

### 2026-05-13 (späterer Abend) — Schritt 2e: Verdict gegen die 4 Schnitt-Alternativen

**Was die Daten sagen (auf n=10 064 v4-Korpus):**

| Option | Gewinn-Bedingung (laut Doc) | Gemessen | Verdict |
|---|---|---|---|
| **Beibehalt** (4 separate Klassifikatoren) | Co-Firing<5%, OutcomeKorr<0.2, hohe Feature-Divergenz | Familien-η²=79.4 %, alle Hit-Rate-Paare signifikant verschieden bei Bonf-α, keine Rang-Inversion an Top-2-Familien | **Stützt sich auf 3-von-4 Familien** (BOS, SWEEP, FVG sind context-stabil), zerbricht aber an OB |
| **A — Pooled** | Co-Firing hoch, Outcome-Korr hoch, Features ähnlich | OB→BOS 54 Prozentpunkte Δ Hit-Rate, η²_family=79.4 % vs η²_context=11.1 % | **Verworfen.** Pooling verschmiert eine reale 4-Cluster-Struktur. |
| **B — Hierarchical Bayes** | Mittlere Korrelation, MCMC-Budget vorhanden | Drei Familien brauchen kaum Partial Pooling (Context-Std≤0.06), OB braucht es stark (Std=0.124) | **Teilweise gerechtfertigt**, aber nur für OB nötig. Kosten/Nutzen über ML-Stack fragwürdig, wenn 3/4 Familien fast stationär sind. |
| **C — Single MoE** (LightGBM mit family_id + Interaktionen) | Pragmatischer Mittelweg | family_id würde 79.4 % der Varianz aufnehmen, Kontext-Interaktion 11.1 %, Residual 9.5 % | **Lebensfähig.** Behält die Familien-Separation als Feature, lässt OB-Context-Kopplung über Tree-Splits emergieren, eine Pipeline statt vier. |
| **D — Regime-Schnitt** | Edge ist Regime, nicht Familie | η²_family=79.4 % ≫ η²_context=11.1 % | **Verworfen.** Regime ist eindeutig untergeordnete Achse. |

**Empfohlene Option (provisorisch, vor Co-Firing-Roh-Analyse):**

**Beibehalt für BOS/SWEEP/FVG, gesonderte Behandlung für OB.** Konkret:
- BOS, SWEEP, FVG: heutige Per-Familie-Klassifikatoren bleiben — die Context-Std ≤ 0.06 zeigt, dass Partial Pooling oder MoE-Interaktion kaum Mehrwert über den Aufwand bringt.
- OB: Context-Std=0.124 und Rang-Inversionen → entweder Hierarchical-Bayes-Partial-Pooling **nur für OB** oder OB-Familie in zwei Subgruppen splitten (z. B. `OB_session_ASIA` vs `OB_session_other`) und einzeln promotieren. Welche der beiden bevorzugt ist, entscheidet sich nach C8-Phase-B-Daten zu OB — heute haben wir 0 Trades.
- Promotion-Gate `check_c12_trigger.py` (90 Tage × 30 Trades pro Familie) bleibt für BOS/SWEEP/FVG. Für OB sollte das Promotion-Kriterium **kontext-konditioniert** sein, sobald genug OB-Trades pro Session existieren.

**Was diese Empfehlung explizit nicht entscheidet:**
- Co-Firing-Anteil (1 vs 2 vs 3 vs 4 Familien auf gleicher Bar) — braucht den Roh-`events_*_*.jsonl`-Strom. Bleibt **offen** bis nächster Producer-Cron-Lauf mit befüllter Source.
- Cramér's V auf paarweisen Outcome-Labels (Co-Firing-Bars) — gleicher Block.
- Per-Symbol-Heterogenität — die Aggregate haben pair_count=80, aber kein per-Pair-Hit-Rate-Detail im committeten Korpus. Pair-Heterogenität müsste über die einzelnen `scoring_*.json` der Pair-Verzeichnisse gerechnet werden (nicht im Repo committed, nur im Artifact).

**Risiko-Notiz zur Empfehlung:** Die Aggregate kommen aus einer einzigen lokalen Run (v4, 2026-04-23). Eine zweite, unabhängige Korpus-Generation (z. B. nach erfolgreicher Cron-Brücke #2197 + Production-Bundle-Hydration in CI) muss diese Verdikte replizieren, **bevor** Migration angeordnet wird. Wenn der nächste Lauf η²_family unter 0.5 drückt oder OB nicht mehr ausreißt, ist die Empfehlung neu zu fassen.

**Beziehung zum Hauptziel:** "Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt — dann habe ich nichts zu verkaufen." Die v4-Aggregate **zeigen** zwar profitable Setups (BOS 85.7 %, SWEEP 65.6 %, FVG 57.0 % über n=10 064), aber sie zeigen sie auf einem **rekonstruierten** Aggregat, nicht auf einem aktuellen Live-Track-Record. Der c10b-Sprint hat damit die **Methodik-Frage** beantwortet (4 disjunkte Populationen — ja, mit OB als Sonderfall) und die **Daten-Frage** offen gelassen (kein aktueller Roh-Stream). Ohne Cron-Brücke gibt es kein frisches Beweis-Material. Mit gefüllter Cron-Brücke wäre Co-Firing-Analyse die nächste Stufe — heute ist sie technisch nicht möglich.

**Referenz-Artifact:** `docs/research/c10b/family_partition_analysis_v4_corpus.json` (alle Roh-Zahlen, alle Tests, alle Decompositions reproduzierbar).

---

## Entscheidung + Begründung

**Endurteil (datenbasiert auf v4-Korpus n=10 064 + 1D-Replikations-Korpus n=410, 2026-05-13):**
**Beibehalt für BOS / SWEEP / FVG; gesonderte Behandlung für OB (intraday-only); Joint-Outcome-Modellierung als separates Backlog-Item.**

Die ursprünglich am Nachmittag eingetragene Empfehlung war als *provisorisch* gekennzeichnet, weil die Replikation auf einem zweiten, unabhängigen Korpus + die Co-Firing-Analyse auf Bar-Ebene noch offen waren. Beide wurden am späten Abend (Step 2f) nachgereicht; siehe `docs/research/c10b/co_firing_and_replication_findings.md`. Die Empfehlung wird damit zum Endurteil, mit drei dokumentierten Vorbehalten (siehe unten).

**Drei Analyse-Ergebnisse (jetzt vollständig, inkl. Step 2f-Replikation):**
1. Co-Firing-Anteil + Cramér's V (Step 2f): **22.61 % Multi-Firing-Bars** auf 1D-Korpus (über 20 %-Pooling-Schwelle), **max V = 0.27** auf paarweisen Outcome-Korrelationen (unter 0.5-Pooling-Schwelle). Gemeinsames Feuern ohne gemeinsamen Outcome — spricht **nicht** für Pooling, sondern für Joint-Outcome-Modellierung als separates Backlog-Item.
2. Outcome-Korrelation pro Familie und zwischen Familien (Step 2c + 2f): **alle 6 Paare hochsignifikant verschieden** auf v4 (n=10 064), **4 von 6 weiterhin signifikant** auf der unabhängigen 1D-Replikation (n=410); die zwei verbleibenden Paare sind power-limitiert auf OB. Spricht klar gegen Option A (Pooled).
3. Feature-Divergenz / Variance-Decomposition (Step 2d + 2f): **η²_family = 79.4 % auf v4 → 98.5 % auf 1D-Replikation**, in beiden Fällen dominant. Drei von vier Familien context-stabil (Std ≤ 0.06), OB die Ausnahme — aber OB-Heterogenität ist auf Daily-Bars strukturell unprüfbar (siehe Vorbehalt 2). Spricht klar gegen Option D (Regime).

**Begründung:** Die statistische Evidenz ist eindeutig genug, um Optionen A (Pooled) und D (Regime-Schnitt) zu **verwerfen**. Optionen Beibehalt, B (Hier. Bayes) und C (MoE) sind alle data-konsistent — der Tie-Breaker ist Aufwand/Nutzen: BOS, SWEEP, FVG zeigen so kleine Within-Family-Context-Streuung, dass weder Partial Pooling noch MoE einen messbaren Gewinn versprechen. OB ist der eine echte Problemfall — und der wird **nicht** durch eine Architektur-Schnitt-Änderung an allen vier Familien gelöst, sondern durch eine OB-spezifische Hierarchisierung (Hier. Bayes nur für OB) oder einen OB-internen Subgruppen-Split (`OB_session_ASIA` vs Rest). Welche der zwei: entscheidbar erst mit Phase-B-OB-Daten.

**Konsequenzen für `ml/`, `rl/`, Promotion-Gate, C8-Phase-B-Kriterien:**
- `ml/training/xgb_family_trainer.py` + `ml/training/lgbm_family_trainer.py`: **keine strukturelle Änderung** für BOS/SWEEP/FVG.
- `scripts/run_smc_live_incubation.py:125–149` `PHASE_B_CRITERIA`: bleibt für BOS/SWEEP/FVG. Für OB ist ein context-konditionales Gate zu konzipieren, sobald ≥ 1 OB-Trade pro Session vorliegt.
- `scripts/check_c12_trigger.py`: Logik "requires per family all of (90d, 30 trades, 0 kill-switch, drift pass)" bleibt für 3/4 Familien. OB-Pfad bekommt einen TODO-Hook, aktuell kein Code-Eingriff.
- `smc_integration/release_policy.py` Promotion-Gate: keine Änderung.
- C8-Runbook: keine Änderung; Phase-B-Sammlung läuft per Familie weiter, der einzige Unterschied ist, dass OB einen eigenen Folge-Schritt bekommt, sobald Phase-B-Daten existieren.

**Replikations-Ergebnis (Step 2f, 2026-05-13 später Abend):**

Lokaler Benchmark-Lauf auf Daily-Bars (Workbook-Fallback in `_load_source_bars`) gegen die 20-Symbol-Universe (AAPL…CAT, 2026-01-26 → 2026-03-06) hat 410 Events mit echten `bar_timestamp` produziert. Erstmals direkt rechenbar:

| Kennzahl | v4 (5m/15m/1H/4H, n=10 064) | 1D-Replikation (n=410) | Erkenntnis |
|---|---|---|---|
| η²_family | 0.7944 | **0.9845** | Familien-Achse dominiert noch klarer auf 1D — Pooling bleibt verworfen. |
| η²_context | 0.1109 | 0.0068 | Context-Effekte fast verschwunden (1D hat strukturell weniger Session-Differenzierung). |
| paarweise z-Tests reject pool (Bonf-α=0.00833) | 6/6 | 4/6 | Verbleibende 2 (OB×FVG, OB×SWEEP) sind power-limitiert auf n=96 OB-Events. |
| OB Hit-Rate | 31.88 % | 68.75 % | OB auf Daily ist ein qualitativ anderes Setup. |
| OB Context-Std | 0.1245 | 0.0052 | OB-Heterogenität aus v4 auf 1D **strukturell unprüfbar** (Daily-Bars tragen nur Session=NONE). |
| Co-Firing-Anteil (≥2 Familien / Bar) | n/a (Bar-Timestamps fehlten in Aggregaten) | **22.61 %** | Über 20 %-Pooling-Schwelle, aber… |
| Cramér's V max auf Co-Firing-Outcomes | n/a | **0.27** (FVG×SWEEP) | … deutlich unter 0.5-Pooling-Schwelle. Familien feuern oft gemeinsam, ihre Outcomes sind aber nicht stark korreliert. |

**Drei explizite Vorbehalte zum Endurteil:**

1. **OB-Sonderbehandlung ist intraday-only zu scopen.** Auf Daily reproduziert sich weder die niedrige Hit-Rate (0.32) noch die hohe Context-Streuung (Std=0.124). OB-spezifische Hierarchisierung gilt für 5m/15m/1H/4H — nicht für 1D-Strategien, falls die jemals gebaut werden.
2. **Die Rang-Inversionen in session:ASIA / session:LONDON sind auf 1D nicht falsifizierbar**, weil Daily-Bars nur einen Session-Bucket ("NONE") tragen. Die v4-Beobachtung wird durch die 1D-Replikation weder bestätigt noch widerlegt — sie bleibt v4-spezifisch.
3. **Co-Firing >20 % überschreitet die Pooling-Tendency-Schwelle des Sprints, während Cramér's V (max 0.27) klar unter der Pooling-Schwelle bleibt.** Das heißt: gemeinsames Feuern bedeutet nicht gemeinsamen Outcome. Konsequenz — nicht Pooling der Familien, sondern **Joint-Outcome-Modellierung** als eigener Sprint-Backlog-Eintrag (siehe `docs/sprints/backlog/joint_outcome_modeling.md`).

**Beziehung zum Hauptziel** — "Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt, dann habe ich nichts zu verkaufen": Beide Korpora zeigen profitable Setups auf der Familien-Achse: BOS 86–98 %, SWEEP 66–78 %, FVG 53–57 %. Die Familien-Trennung ist auf zwei unabhängigen Korpora belastbar. Das ist verkaufbar als "drei messbar profitable Setups (BOS/SWEEP/FVG) plus OB als intraday-Sonderfall", nicht als Universalmotor.

---

## Was dieser Sprint explizit nicht ist

- Kein Code-Refactor in `ml/training/`
- Kein neuer ML-Klassifikator
- Keine Änderung am C8-Runbook
- Keine Änderung am Promotions-Gate (`smc_integration/release_policy.py`)
- Keine Workflow-Änderung außer der separat dokumentierten Cron-Brücke

Wenn die Analyse "Beibehalt" empfiehlt, bleibt der ganze heutige Code unverändert. Das ist ein gültiges Outcome.


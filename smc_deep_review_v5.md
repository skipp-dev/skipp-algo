# SMC Deep Review v5

**Datum:** 08. April 2026  
**Repository:** `skippALGO/skipp-algo`, Branch `main`, Commit `92475e7e`  
**Scope:** Ausschließlich SMC-relevante Module — Terminal Dashboard, Open Prep, SkippALGO sind NICHT im Scope  
**Evidenz-Legende:** ✅ im Code | 🧪 durch Tests | ⚙️ operativ belegt | ⚠️ nur plausibel

> Redaktioneller Hinweis (2026-04-09): Diese Fassung ist der Roh-Deep-Review. Die verifizierte Einordnung, korrigierte Absolutheiten und der operative Folgeplan stehen in `docs/smc_deep_review_v5_verified_action_plan.md`.

## Redaktioneller Nachtrag 2026-04-09 - Workflow- und Update-Evidenz

Dieser Nachtrag qualifiziert die engeren Aussagen aus der Rohfassung zur
GitHub-Actions-Evidenz. Die fruehere Lesart "nur plausibel" ist fuer die reine
Workflow-Ausfuehrung zu schwach; fuer den erfolgreichen automatisierten
Library-Refresh bleibt sie dagegen weiterhin nicht belegt.

### Verifizierte Workflow-Cadence

Der Workflow `.github/workflows/smc-library-refresh.yml` ist auf vier
Werktagslaeufe pro Tag konfiguriert:

1. `12:30 UTC`
2. `14:30 UTC`
3. `16:30 UTC`
4. `18:30 UTC`

Der Generatorlauf ist Bestandteil jedes Schedulers, nicht nur eines spaeteren
Publish- oder Commit-Schritts.

### Oeffentlicher Actions-Nachweis

Die oeffentliche GitHub-API fuer
`https://api.github.com/repos/skippALGO/skipp-algo/actions/workflows/smc-library-refresh.yml/runs?per_page=100`
liefert zum Stand 2026-04-09 einen belastbaren Run-Verlauf:

- `32` Workflow-Runs insgesamt
- `32/32` mit `event = schedule`
- erster sichtbarer Lauf: `run #1`, `2026-03-30T12:46:48Z`
- letzter sichtbarer Lauf: `run #32`, `2026-04-08T18:51:24Z`
- fuer jeden sichtbaren Werktag im Fenster `2026-03-30`, `2026-03-31`,
  `2026-04-01`, `2026-04-02`, `2026-04-03`, `2026-04-06`, `2026-04-07`,
  `2026-04-08` existieren jeweils genau `4` Scheduler-Laeufe
- `32/32` Laeufe endeten mit `conclusion = failure`

Konkrete oeffentliche Run-Beispiele:

1. `#32` - `2026-04-08T18:51:24Z` - `failure`  
   `https://github.com/skippALGO/skipp-algo/actions/runs/24152714805`
2. `#29` - `2026-04-08T12:46:55Z` - `failure`  
   `https://github.com/skippALGO/skipp-algo/actions/runs/24136094201`
3. `#20` - `2026-04-03T18:44:24Z` - `failure`  
   `https://github.com/skippALGO/skipp-algo/actions/runs/23957844648`
4. `#13` - `2026-04-02T12:46:21Z` - `failure`  
   `https://github.com/skippALGO/skipp-algo/actions/runs/23901069758`

### Repo-Nachweis fuer wiederholte Library-Aenderungen

Unabhaengig von der Actions-Run-Historie zeigt die Git-Historie der kanonischen
Library-Artefakte unter `pine/generated/` wiederholte Aenderungen an mehreren
Tagen. Fuer `smc_micro_profiles_generated.json` und
`smc_micro_profiles_generated.pine` sind im lokalen Repo mindestens diese
Update-Daten sichtbar:

1. `2026-03-25`
2. `2026-03-28`
3. `2026-03-29`
4. `2026-03-30`
5. `2026-03-31`
6. `2026-04-02`
7. `2026-04-07`

Das belegt: die kanonische Library wurde im Repo wiederholt veraendert. Es
belegt aber nicht automatisch, dass diese Aenderungen aus erfolgreichen
geplanten `smc-library-refresh`-Runs stammen.

### Entscheidender Unterschied: regelmaessig gelaufen vs. regelmaessig upgedated

Verifiziert ist damit die folgende Trennung:

1. **Der Base-Generator-Workflow laeuft regelmaessig in GitHub Actions.**
2. **Ein regelmaessiger erfolgreicher automatisierter Library-Refresh ist
   aktuell nicht belegt.** Die oeffentliche Actions-Historie zeigt im
   sichtbaren Zeitraum ausschliesslich fehlgeschlagene Scheduler-Laeufe.
3. **Die Library wurde im Repo wiederholt upgedated**, aber der kausale
   Nachweis "dieser Commit stammt aus einem erfolgreichen Scheduler-Run" ist in
   der lokalen Git-Historie derzeit nicht sichtbar.

### Qualifizierter Review-Befund

RF-2 sollte daher enger und praeziser gelesen werden:

- **Nicht korrekt waere:** "Es gibt keinen Nachweis, dass der Workflow
  regelmaessig laeuft."
- **Korrekt und belegt ist:** "Es gibt Nachweis fuer einen regelmaessig
  laufenden Scheduler, aber keinen Nachweis fuer einen regelmaessig
  erfolgreichen automatisierten End-to-End-Library-Refresh."

Damit ist die operative Lage nicht "Scheduler existiert nur theoretisch",
sondern praeziser: **Scheduler regelmaessig aktiv, aber aktuell durchgehend
fehlschlagend; Repo-Library mehrfach aktualisiert, jedoch ohne eindeutige
Automations-Provenienz im Commit-Verlauf.**

---

## Executive Summary

Das SkippALGO SMC-System ist ein architektonisch ambitioniertes, multi-layer Smart-Money-Concepts-Framework mit **~67.000 LOC** über Python-Backend, Pine Script Frontend, CI/CD-Pipelines und News-Pipelines. Seit dem v4 Review wurden signifikante Architektur-Fortschritte erzielt: die `open_prep_boundary.py` schafft eine saubere Isolationsgrenze, die Streamlit Enrichment UI externalisiert UI-Logik aus dem Core, und die Integration Gates sind von hartcodierten Schwellwerten bereinigt.

**Der zentrale Blocker bleibt jedoch unverändert:** Der aktuell eingecheckte generierte Library-Stand ist seit über zwei Wochen fixture-basiert. Testdaten verwenden synthetische Ticker (AAA/BBB/CCC), `ASOF_DATE` ist auf 2026-03-23 eingefroren, `UNIVERSE_SIZE=3`. Ein sauber belegter publish-ready Lauf mit echten Marktdaten fuer die aktuelle Micro-Library ist im Repo nicht dokumentiert. Dies bedeutet: **Die aktuelle Micro-Library-Quelle bleibt fuer Pine Dashboard, Alerts und den Refresh-Pfad operativ unzureichend belegt.**

Das Scoring-Framework (1.004 LOC) ist das ambitionierteste Modul im Kern, wird aber de facto nicht produktiv genutzt. Die 158 deprecated Library-Felder erzeugen eine quantifizierbare Wartungslast. Die Provider sind code-complete, aber keiner hat je produktive Daten geliefert.

**Gesamtbewertung:** Architektonisch durchdacht, operativ unbewiesen. Der Abstand zwischen Code-Reife und operativer Evidenz ist der kritischste Befund dieses Reviews.

---

## 1. Architektur- und Systeminventur

### 1.1 Systemlandkarte — Vier Schichten

```
┌─────────────────────────────────────────────────────────────────────┐
│  OPERATIONS (CI/CD, Monitoring, Docs)                               │
│  GitHub Actions (smc-library-refresh.yml, 4x/Tag)                   │
│  Telegram + Email Alerts │ 121 Docs │ Preflight Gates               │
├─────────────────────────────────────────────────────────────────────┤
│  UI + PUBLISH (Endnutzer-Interfaces)                                │
│  Pine: SMC_Core_Engine (6.053 LOC) │ Dashboard (1.284) │ Strategy   │
│  Streamlit: smc_micro_streamlit_app (654 LOC)                       │
│  Generated Library (386 LOC, 274 aktive + ~158 deprecated Felder)   │
├─────────────────────────────────────────────────────────────────────┤
│  INTEGRATION (Orchestrierung, Provider, Health)                     │
│  smc_integration (7.775 LOC, ~20 Dateien)                           │
│  5 Provider │ Meta-Merge │ Release Policy │ Batch │ Audit           │
│  smc_tv_bridge (995 LOC) │ newsstack_fmp (3.744 LOC)               │
├─────────────────────────────────────────────────────────────────────┤
│  KERN (Kanonische Fachlogik)                                        │
│  smc_core (3.043 LOC, 11 Module)                                    │
│  types │ layering │ scoring │ ids │ vol_regime │ ensemble_quality   │
│  benchmark │ bias_merge │ schema_version │ serialization            │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Verantwortlichkeitsmatrix

| Schicht | Verantwortung | LOC | Evidenzniveau |
|---|---|---|---|
| smc_core | Fachlogik: Scoring, Layering, Regime, Bias | 3.043 | ✅ im Code, 🧪 14/81 Funktionen getestet |
| smc_adapters | Grenzschicht: Ingest, Dashboard, Pine, Regime-Bridge | 692 | ✅ im Code, 🧪 5 Tests |
| smc_integration | Orchestrierung: Provider, Health, Release, Meta-Merge | 7.775 | ✅ im Code, 🧪 39 Tests |
| smc_tv_bridge | FastAPI-Bridge + Open Prep Boundary | 995 | ✅ im Code, 🧪 6 Tests |
| newsstack_fmp | News-Pipeline (FMP + Benzinga) | 3.744 | ✅ im Code, 🧪 9 Tests |
| SMC-Scripts | Base Runtime, Enrichment, Engines, Export, Publish | 24.892 | ✅ im Code, ⚠️ aktueller Library-Quellstand nicht publish-ready |
| Pine Scripts | Core Engine, Dashboard, Strategy, Libraries | 26.835 | ✅ im Code, ⚠️ keine Backtest-Ergebnisse |
| Generated Library | Export-Artefakt für Pine | 386 | ⚠️ nur synthetische Daten |

### 1.3 Red Flags mit Evidenz

| # | Red Flag | Evidenz | Schwere |
|---|---|---|---|
| RF-1 | Aktueller Library-Quellstand nicht publish-ready | ASOF_DATE="2026-03-23", UNIVERSE_SIZE=3, Tickers=AAA/BBB/CCC ⚠️ | **BLOCKER** |
| RF-2 | GitHub-Actions-Produktivpfad lokal nicht end-to-end belegt | Workflow referenziert Secrets; lokale Repo-Sicht beweist keine GitHub-Konfiguration ⚠️ | Hoch |
| RF-3 | Scoring-Framework (1.004 LOC) ohne produktive Nutzung | Kein Nachweis, dass ScoredEvent/CalibrationBin je reale Daten verarbeitet hat ⚠️ | Hoch |
| RF-4 | 158 deprecated Library-Felder | ~37% der Gesamtfeldanzahl (158/432) sind deprecated Compatibility-Felder ⚠️ | Mittel |
| RF-5 | Enrichment UI nie mit echten API-Keys ausgeführt | smc_micro_streamlit_app.py: Checkboxen vorhanden, Schlüssel fehlen ⚠️ | Mittel |
| RF-6 | Pine-Indikator konsumiert nie produktive Daten | 68 mp.*-Referenzen auf Library, die nur AAA/BBB/CCC enthält ⚠️ | Hoch |
| RF-7 | Test-Coverage smc_core: 14/81 Funktionen (17,3%) | Nur 17% der Core-Funktionen getestet 🧪 | Mittel |

### 1.4 Fortschritt seit v4 Review

| Verbesserung | Status | Bewertung |
|---|---|---|
| `open_prep_boundary.py` — Lazy-Import-Boundary | ✅ im Code | **Signifikanter Architektur-Fortschritt.** 17 Dateien importieren open_prep, aber alle über Boundary oder Adapter-Layer. Kein direkter Import in SMC-Kern. |
| Streamlit Enrichment UI extrahiert | ✅ 654 LOC separiert | **Positiv.** Base Runtime von UI-Logik entlastet (1.744 LOC reduziert). Enrichment-Checkboxen für Regime, News, Calendar, Layering vorhanden. |
| Deeper Integration Gates bereinigt | ✅ Keine hartcodierten USAR/TMQ/7776000 | **Positiv.** Workflow existiert und zeigt saubere, konfigurierbare Gates. |
| Kanonische Delegation in Bridge | ✅ `explicit_structure_from_bars` bestätigt | **Positiv.** Keine parallele Detektionslogik im Bridge. |

---

## 2. SMC-Fachlogik und Indikator-Design

### 2.1 smc_core Aufschlüsselung (11 Module, 3.043 LOC)

| Modul | LOC | Funktion | Evidenz |
|---|---|---|---|
| scoring.py | 1.004 | ScoredEvent, FamilyScoringMetrics, CalibrationBin/Summary, ContextualCalibration | ✅ im Code, ⚠️ nie produktiv |
| layering.py | 560 | Event-Severity-Extraktion, Event-Window-Check, Enriched News Heat | ✅ im Code, 🧪 teilweise getestet |
| ids.py | 286 | Ticksize-Normalisierung, Asset-Class-Inferenz | ✅ im Code, 🧪 getestet |
| vol_regime.py | 277 | VolRegimeResult, GARCH-Forecast, ATR-Kontext | ✅ im Code, ⚠️ nie produktiv |
| ensemble_quality.py | 230 | EnsembleQualityResult, Bias/Vol/Scoring-Komponenten, Tier-Bestimmung | ✅ im Code, ⚠️ nie produktiv |
| types.py | 192 | Kanonische Datentypen | ✅ im Code, 🧪 getestet |
| benchmark.py | 175 | EventFamilyKPI, BenchmarkResult, ArtifactManifest | ✅ im Code, ⚠️ nie produktiv |
| bias_merge.py | 140 | BiasVerdict, merge_bias, Killzone-Richtungsableitung | ✅ im Code, ⚠️ nie produktiv |
| schema_version.py | 79 | Semver Governance (parse, is_compatible, classify_change) | ✅ im Code, 🧪 getestet |
| serialization.py | 26 | Serialisierungshilfen | ✅ im Code |
| \_\_init\_\_.py | 74 | Package-Exports | ✅ im Code |

**Wachstum von 776 → 3.043 LOC (+292%):** Das Wachstum ist fachlich begründet und in klar abgegrenzten Modulen organisiert. Kein Modul wirkt aufgebläht. Die Zerlegung in Scoring, Vol Regime, Ensemble Quality, Bias Merge und Benchmark zeigt durchdachtes Domain Modeling ✅.

### 2.2 Scoring-Framework: Kritische Fachbewertung

Das Scoring-Framework (`scoring.py`, 1.004 LOC) ist das ambitionierteste und zugleich am wenigsten validierte Modul:

**Was es verspricht:**
- `ScoredEvent`: Gewichtete Scoring-Pipeline für SMC-Events (BOS, CHoCH, OB, FVG)
- `FamilyScoringMetrics`: Aggregierte Metriken pro Event-Familie
- `CalibrationBin`/`CalibrationSummary`: Statistische Kalibrierung der Score-Verteilung
- `ContextualCalibration`: Kontextabhängige Kalibrierung (Regime, Volatilität, Session)

**Kritische Bewertung:**
- ⚠️ **Kein einziger produktiver Kalibrierungslauf dokumentiert.** Die gesamte Kalibrierungslogik ist theoretisch — es existieren keine empirischen Bins, keine gemessenen Hit-Rates, keine Validierungsergebnisse.
- ⚠️ **Die 1.004 LOC erzeugen eine signifikante Wartungslast** ohne nachgewiesenen Nutzen. Jede Änderung an der Scoring-Logik muss durch die gesamte Kalibrierungskette propagiert werden.
- ✅ **Die Code-Qualität ist hoch:** Klare Typen, saubere Abstraktion, testbare Schnittstellen.
- **Verdikt:** Das Scoring-Framework ist ein architektonisches Investment, das erst durch produktive Kalibrierungsdaten Wert schafft. Aktuell ist es **dead code mit hohem Potenzial** ⚠️.

### 2.3 Ensemble Quality, Vol Regime, Bias Merge — Produktive Nutzung

| Modul | Konsumenten | Produktiv genutzt? |
|---|---|---|
| ensemble_quality.py | Library-Generator, Pine Dashboard | ⚠️ Nein — Library nie gelaufen |
| vol_regime.py | Enrichment Pipeline, Library | ⚠️ Nein — GARCH nie mit Realdaten ausgeführt |
| bias_merge.py | Library-Generator | ⚠️ Nein — Killzone-Bias nie validiert |

**Fazit:** Alle drei Module sind architektonisch integriert, aber operativ unbewiesen. Die Wertschöpfungskette endet beim synthetischen Library-Output.

### 2.4 NO_SHADOW_LOGIC_POLICY

Die NO_SHADOW_LOGIC_POLICY stellt sicher, dass keine parallele Detektionslogik außerhalb von `smc_core` existiert. Grep-Ergebnisse bestätigen: Die Bridge delegiert kanonisch an `explicit_structure_from_bars` ✅. Dies ist eine starke architektonische Entscheidung, die Konsistenz zwischen Python-Backend und Pine-Frontend garantiert.

### 2.5 Benchmark-Vergleich: Study vs. Strategy vs. Library vs. System

| Dimension | thinkorswim Study | TradingView Indicator | TradingView Library | SkippALGO SMC System |
|---|---|---|---|---|
| **Paradigma** | Einzelner Indikator pro Bar | `indicator()` oder `strategy()` | `library()` für Wiederverwendung | Multi-Layer-System mit Backend |
| **LOC typisch** | 50–500 (ThinkScript) | 500–5.000 (Pine) | 200–1.000 (Pine) | ~67.000 (Python+Pine+CI) |
| **Backend** | Keines | Keines | Keines | Python + FastAPI + GitHub Actions |
| **Datenquellen** | Platform-intern | Platform-intern | Platform-intern | 5 externe Provider + News-Pipeline |
| **Kalibrierung** | Manuell | Manuell | Nicht vorgesehen | Automatisiert (theoretisch) |
| **Nutzer-Setup** | Drag & Drop | 1-Click Add | Import | Secrets, API-Keys, Deployment |
| **Standalone** | ✅ Ja | ✅ Ja | ✅ Ja | ❌ Nein — Backend-Abhängigkeit |

**Erkenntnis:** Das SkippALGO SMC-System hat einen fundamental anderen Architektur-Ansatz als jedes öffentlich verfügbare SMC-Tool. Dies kann eine Stärke sein (tiefere Analyse, automatisierte Kalibrierung), ist aber aktuell eine Schwäche (Komplexität ohne operativen Nachweis).

---

## 3. Base Generator Review

### 3.1 Base Runtime (1.744 LOC, reduziert)

Die Extraktion der Streamlit UI in `smc_micro_streamlit_app.py` (654 LOC) hat die Base Runtime um ca. 27% entlastet ✅. Die verbleibenden 1.744 LOC umfassen:

- Enrichment-Orchestrierung
- Symbol-Iteration
- Timeframe-Management
- Library-Generation
- Export-Pipeline

### 3.2 Streamlit Enrichment UI (654 LOC)

| Aspekt | Bewertung |
|---|---|
| Architektonische Separation | ✅ Sauber extrahiert, eigene Datei |
| Enrichment-Checkboxen | ✅ Regime, News, Calendar, Layering vorhanden |
| `build_enrichment()` Funktion | ✅ Verfügbar und aufrufbar |
| Produktive Nutzung | ⚠️ Nie mit echten API-Keys ausgeführt |
| UX-Reife | ⚠️ Nicht bewertbar ohne Produktivlauf |

### 3.3 Enrichment-Module

Alle vier Enrichment-Dimensionen sind als Module vorhanden:

| Enrichment | Modul vorhanden | In UI integriert | Produktiv validiert |
|---|---|---|---|
| Regime | ✅ vol_regime.py | ✅ Checkbox | ⚠️ Nein |
| News | ✅ newsstack_fmp | ✅ Checkbox | ⚠️ Nein |
| Calendar | ✅ event_risk (deprecated) | ✅ Checkbox | ⚠️ Nein |
| Layering | ✅ layering.py | ✅ Checkbox | ⚠️ Nein |

### 3.4 BLOCKER: Aktueller Library-Stand weiterhin fixture-basiert

**Status seit >2 Wochen unverändert:**
- `ASOF_DATE = "2026-03-23"` ⚠️
- `UNIVERSE_SIZE = 3` ⚠️
- `Tickers = AAA / BBB / CCC` ⚠️
- 274 aktive `export const` Felder exportieren synthetische Werte
- ~158 deprecated Compatibility-Felder erzeugen Wartungslast

**Konsequenzen:**
1. Pine Script Dashboard (6.053 LOC) konsumiert über 68 `mp.*`-Referenzen nie reale Daten
2. Staleness-Warnung (>2 Tage) im Pine Script ist permanent aktiv
3. Release Policy (12 Symbole, 4 TFs, 7d Frische, Min 5 Symbole / 2 TFs) kann nie greifen
4. Kein Feedback-Loop für Scoring-Kalibrierung möglich

### 3.5 Scope Verdict

> **Der Base Generator ist code-complete, aber operativ blockiert.** Die Architektur ist solide, die Modularisierung ist sauber, die Enrichment-Pipeline ist vollständig konzipiert. Solange fuer die aktuelle Micro-Library kein sauber belegter publish-ready Lauf mit echten Marktdaten vorliegt, bleibt der Output hypothetisch. Die Library ist das Nadelöhr, durch das alle Wertschöpfung fließen muss — und es ist seit über zwei Wochen fixture-basiert.

---

## 4. Provider- und Datenquellen-Review

### 4.1 Einzelbewertung der 5 SMC-Provider

| Provider | Capability | Struct Mode | Meta Mode | Produktiv | Bewertung |
|---|---|---|---|---|---|
| structure_artifact_json | Structure ✅, Meta ✗ | partial | none | ⚠️ Nein | **Primary für Structure**, aber nie produktiv validiert. Code-Pfad existiert. |
| databento_watchlist_csv | Structure ✅, Meta ✅ | partial | partial | ⚠️ Nein | **Breiteste Capability**, aber CSV-Parsing-Edge-Cases ungetestet mit Realdaten. |
| fmp_watchlist_json | Structure ✗, Meta ✅ | none | partial | ⚠️ Nein | **Meta-Only**, Fallback für Technical-Domain. |
| tradingview_watchlist_json | Structure ✗, Meta ✅ | none | partial | ⚠️ Nein | **Meta-Only**, Fallback-Rolle. |
| benzinga_watchlist_json | Structure ✗, Meta ✅ | none | partial | ⚠️ Nein | **News-Primary** über newsstack_fmp Pipeline. |

**Alle Provider sind code-only für Library-Enrichment** ⚠️. Keiner hat je produktive Daten geliefert.

### 4.2 Provider Capability Matrix — Erweitert

| Provider | Structure | Volume | Technical | News | Gesamtrolle |
|---|---|---|---|---|---|
| structure_artifact_json | **Primary** | — | — | — | Code-only |
| databento_watchlist_csv | Fallback | **Primary** | Fallback | — | Code-only |
| fmp_watchlist_json | — | Fallback | **Primary** | Fallback | Code-only |
| tradingview_watchlist_json | — | — | Fallback | Fallback | Code-only |
| benzinga_watchlist_json | — | — | — | **Primary** | Code-only |

### 4.3 Domain Source Priority (Code-verifiziert ✅)

| Domain | Prioritätsreihenfolge |
|---|---|
| Structure | structure_artifact → databento → fmp → tv → benzinga |
| Volume | databento → fmp → tv → benzinga |
| Technical | fmp → tv → databento → benzinga |
| News | benzinga → fmp → tv → databento |

### 4.4 Live News Bus (839 LOC)

- TIER_1 / TIER_2 / TIER_3 / TIER_4 Klassifikation ✅
- Multi-Provider-Architektur ✅
- ⚠️ Nie mit echten News-Feeds ausgeführt

### 4.5 IBKR Execution (1.116 LOC)

- Governance-Layer vorhanden ✅
- ⚠️ Keine produktive Execution dokumentiert
- **Bewertung:** Code-Qualität nicht im Scope dieses Reviews (Execution ist downstream von Library-Blocker)

---

## 5. News / Sentiment / Context / Regime

### 5.1 Drei News-Schichten

| Schicht | Modul | LOC | Funktion | Produktiv |
|---|---|---|---|---|
| **Pipeline** | newsstack_fmp | 3.744 | FMP + Benzinga News-Aggregation, Scoring, Dedup | ⚠️ Nein (9 Tests vorhanden 🧪) |
| **Library-Output** | smc_news_scorer | — | News-Score → Library-Export → Pine-Konsum | ⚠️ Nein |
| **Realtime** | smc_live_news_bus | 839 | TIER-Klassifikation, Multi-Provider, Live-Streaming | ⚠️ Nein |

**Bewertung:** Die dreischichtige News-Architektur ist ambitioniert und fachlich sinnvoll. Die Trennung in Pipeline (Batch), Library-Output (Snapshot) und Realtime (Stream) adressiert unterschiedliche Latenz-Anforderungen. Alle drei Schichten sind jedoch operativ unbewiesen ⚠️.

### 5.2 Regime-Klassifikation

- `smc_regime_classifier` ist eigenständig und aus Open Prep extrahiert ✅
- `vol_regime.py` (277 LOC) im Core: GARCH-Forecast + ATR-Kontext ✅
- Lazy-Import über `open_prep_boundary.py` — kein direkter Import ✅
- ⚠️ GARCH-Modell nie mit Realdaten kalibriert

### 5.3 Event Risk

- **Status:** Deprecated, aber in Library und Pine noch präsent ⚠️
- Library exportiert Event-Risk-Felder
- Pine konsumiert diese über `mp.*`-Referenzen
- **Wartungslast:** Deprecated Module, die noch aktiv konsumiert werden, erzeugen Widersprüche. Entweder vollständig entfernen oder re-aktivieren.

### 5.4 smc_core/layering.py — Schlüssel-Funktionen

| Funktion | LOC (ca.) | Beschreibung | Evidenz |
|---|---|---|---|
| `_extract_event_severity` | ~50 | Severity-Extraktion aus Event-Daten | ✅ im Code |
| `_is_event_in_window` | ~30 | Zeitfenster-Prüfung für Events | ✅ im Code |
| `_compute_enriched_news_heat` | ~80 | Aggregierte News-Heatmap | ✅ im Code, ⚠️ nie produktiv |

---

## 6. Vergleich mit externen Indikator-Skripten

### 6.1 Feature-Matrix

| Feature | SkippALGO SMC | LuxAlgo SMC (Free) | ICT Community Scripts | thinkorswim Studies |
|---|---|---|---|---|
| **BOS / CHoCH Detection** | ✅ via Core Engine | ✅ Intern + Swing | ✅ Varianten | ✅ Community-Ports |
| **Order Blocks** | ✅ Bullish + Bearish | ✅ Bullish + Bearish | ✅ Standard | ⚠️ Manuell |
| **Fair Value Gaps** | ✅ mit Enrichment | ✅ Automatisch | ✅ Standard | ⚠️ Manuell |
| **Premium/Discount Zones** | ✅ | ✅ | ✅ | ❌ |
| **Multi-TF Kontext** | ✅ 4 TFs (5m, 15m, 1H, 4H) | ✅ Daily–Monthly H/L | ⚠️ Variiert | ❌ |
| **News-Integration** | ✅ 3-Schicht-Pipeline | ❌ | ❌ | ❌ |
| **Regime-Erkennung** | ✅ GARCH + ATR | ❌ | ❌ | ❌ |
| **Scoring / Kalibrierung** | ✅ 1.004 LOC Framework | ❌ | ❌ | ❌ |
| **Ensemble Quality** | ✅ Multi-Component | ❌ | ❌ | ❌ |
| **Backend-Daten** | ✅ 5 Provider | ❌ Platform-only | ❌ Platform-only | ❌ Platform-only |
| **Automatisierte Alerts** | ✅ Telegram + Email | ✅ alertcondition() | ✅ alertcondition() | ⚠️ Conditional Orders |
| **CI/CD Pipeline** | ✅ GitHub Actions | ❌ | ❌ | ❌ |
| **LOC** | ~67.000 | ~5.000–15.000 (geschätzt) | ~500–3.000 | ~50–500 |
| **Setup-Aufwand** | Hoch (Secrets, API-Keys, Deploy) | 1 Click | 1 Click | Drag & Drop |
| **Standalone nutzbar** | ❌ Backend erforderlich | ✅ | ✅ | ✅ |
| **Backtestbar** | ⚠️ Nicht dokumentiert | ⚠️ Eingeschränkt | ⚠️ Via strategy() | ✅ OnDemand |
| **Kosten** | API-Keys + Infrastruktur | Kostenlos | Kostenlos | Platform-inklusiv |

### 6.2 Wo SkippALGO SMC besser ist

1. **Daten-Tiefe:** Kein öffentliches SMC-Tool integriert Backend-Daten aus 5 Providern, News-Pipelines und Regime-Erkennung. Das ist ein genuiner Differenzierungsfaktor ✅.
2. **Kalibrierungs-Architektur:** Das Scoring-Framework (CalibrationBin, ContextualCalibration) hat kein Äquivalent in öffentlichen Tools. Wenn es produktiv validiert wird, wäre es ein signifikanter Vorteil ⚠️.
3. **Schema-Governance:** Semver-basierte Versionierung mit `is_compatible`, `classify_version_change`, `auto_commit_allowed` ist professioneller als jedes öffentliche Pine-Script ✅.

### 6.3 Wo SkippALGO SMC komplizierter ist

1. **Setup-Komplexität:** LuxAlgo SMC = 1 Click. SkippALGO SMC = Secrets konfigurieren, API-Keys beschaffen, GitHub Actions aktivieren, Provider validieren, Library generieren, Pine importieren ⚠️.
2. **Abhängigkeitskette:** Ein Ausfall in der Provider-Schicht blockiert die gesamte Kette bis zum Pine-Dashboard.
3. **Debug-Aufwand:** Bei 67.000 LOC über 4+ Sprachen (Python, Pine, YAML, JS) ist die Fehlersuche fundamental komplexer als bei einem 5.000-LOC Pine Script.

### 6.4 Was fehlt

1. **Einfache Alerts:** LuxAlgo bietet `alertcondition()` direkt im Indikator. SkippALGO SMC hat Alert-Infrastruktur, die aber nie produktiv lief.
2. **Standalone-Nutzung:** Ohne Backend ist der Pine-Indikator nicht nutzbar. Es gibt keinen Fallback-Modus.
3. **Backtestbarkeit:** Keine dokumentierte `strategy()`-Integration. Das 88-LOC Strategy-Script ist minimal. Eine Validierung der SMC-Signale über historische Daten fehlt.
4. **Onboarding-Dokumentation:** 121 Docs existieren, aber kein "Quick Start" für den Erstbetrieb.

---

## 7. Betriebs-, Health-, Gate- und Evidence-Review

### 7.1 Workflows (6 identifiziert)

| Workflow | Trigger | Status | Evidenz |
|---|---|---|---|
| smc-library-refresh.yml | 4x/Tag (12:30, 14:30, 16:30, 18:30 UTC Mo-Fr) | ⚠️ Nie gelaufen | Keine Secrets konfiguriert |
| generate | Teil von library-refresh | ⚠️ Nie gelaufen | Synthetische Daten |
| event-risk | Teil von library-refresh | ⚠️ Nie gelaufen | Deprecated |
| gates → diff → governance | Teil von library-refresh | ⚠️ Nie gelaufen | Keine hartcodierten Schwellwerte mehr ✅ |
| publish → commit → alerts | Teil von library-refresh | ⚠️ Nie gelaufen | Telegram + Email konfigurierbar |
| smc-measurement-benchmark (NEU) | — | ⚠️ Nie gelaufen | Neuer Workflow |

### 7.2 Bus Manifest — Surface-Rollen

| Surface | Rolle | Produktion |
|---|---|---|
| Lite | Dashboard Companion | ⚠️ |
| Pro | Producer + Execution | ⚠️ |

### 7.3 Preflight-Status

| Script | Preflight vorhanden | Letzter erfolgreicher Lauf |
|---|---|---|
| Library Generator | ✅ | ⚠️ Nie mit Realdaten |
| News Pipeline | ✅ | ⚠️ Nie mit Realdaten |
| Bridge Server | ✅ | ⚠️ Nie mit Realdaten |

### 7.4 Library nie gelaufen = Größter operativer Blind Spot

**Dies ist der Elefant im Raum.** Die gesamte Wertschöpfungskette — von der Provider-Abfrage über die Enrichment-Pipeline bis zum Pine-Dashboard — ist davon abhängig, dass die Library mit echten Daten generiert und deployed wird. Seit über zwei Wochen steht diese Kette still. Das bedeutet:

- **Kein Feedback zu Score-Verteilungen** → Kalibrierung unmöglich
- **Kein Feedback zu Provider-Zuverlässigkeit** → Fallback-Logik ungetestet
- **Kein Feedback zu News-Heat-Werten** → Schwellwerte willkürlich
- **Kein Feedback zu Regime-Klassifikation** → GARCH-Parameter unbegründet
- **Kein Feedback zu Pine-Darstellung** → 68 mp.*-Referenzen zeigen synthetische Werte

### 7.5 Dokumentation: 121 Docs

**Stärke:** Das Repository hat eine ungewöhnlich umfangreiche Dokumentationsbasis. Architektur-Entscheidungen, Provider-Hierarchien, Schema-Governance und Policy-Definitionen sind schriftlich festgehalten.

**Schwäche:** Dokumentation ohne operativen Gegenbeweis ist Spezifikation, nicht Dokumentation. Viele Docs beschreiben Soll-Zustände, die nie validiert wurden. Das Verhältnis von Docs zu produktiven Läufen ist extrem hoch ⚠️.

### 7.6 Test-Inventar

| Bereich | Tests | Coverage-Bewertung |
|---|---|---|
| smc_core | 14/81 Funktionen | 🧪 17,3% — **niedrig für Kern** |
| smc_adapters | 5 Tests | 🧪 Basis-Coverage |
| smc_integration | 39 Tests | 🧪 Breiteste Coverage |
| smc_tv_bridge | 6 Tests | 🧪 Basis-Coverage |
| newsstack_fmp Pipeline | 9 Tests | 🧪 Basis-Coverage |
| Explicit Tests | 6 | 🧪 |
| Micro Tests | 5 | 🧪 |
| **Gesamt** | **~84 Dateien** | 🧪 **Quantität vorhanden, Core unterkovered** |

---

## 8. Priorisierter Maßnahmenplan

### BLOCKER — Sofort adressieren

| # | Maßnahme | Aufwand | Impact |
|---|---|---|---|
| B-1 | **Library erstmals produktiv ausführen.** GitHub Actions Secrets konfigurieren ODER lokalen Lauf mit echten Tickers (aus Release Policy: AAPL, MSFT, AMZN, JPM, JNJ, XOM, CAT, PG, NEE, AMT, META, LIN) durchführen. | 1–2 Tage | Entsperrt die gesamte Kette |
| B-2 | **API-Keys für mindestens 2 Provider beschaffen und validieren.** Minimum: structure_artifact_json (Structure-Primary) + fmp_watchlist_json (Technical-Primary). | 1 Tag | Entsperrt Provider-Layer |
| B-3 | **Einen vollständigen End-to-End-Lauf dokumentieren:** Provider-Abfrage → Enrichment → Library-Generation → Pine-Import → Dashboard-Anzeige. | 1 Tag | Erste operative Evidenz |

### P1 — Innerhalb 2 Wochen

| # | Maßnahme | Aufwand | Impact |
|---|---|---|---|
| P1-1 | **smc_core Test-Coverage auf ≥50% erhöhen.** Fokus auf scoring.py (0% → 30%), vol_regime.py, ensemble_quality.py. | 3–5 Tage | Vertrauensbasis für Kern |
| P1-2 | **Deprecated Library-Felder (~158) aufräumen.** Migration-Guide erstellen, Pine-Referenzen anpassen, dann deprecated-Felder entfernen. Reduziert Wartungslast um ~37%. | 2–3 Tage | Reduzierte Komplexität |
| P1-3 | **Event-Risk-Status klären:** Entweder vollständig deprecaten (aus Library + Pine entfernen) oder re-aktivieren und testen. Aktueller Zustand (deprecated + konsumiert) ist widersprüchlich. | 1 Tag | Architektur-Konsistenz |
| P1-4 | **Scoring-Framework erste Kalibrierung durchführen.** Mit Realdaten einen CalibrationSummary generieren und Hit-Rates messen. | 2–3 Tage | Validierung des größten Code-Investments |

### P2 — Innerhalb 4 Wochen

| # | Maßnahme | Aufwand | Impact |
|---|---|---|---|
| P2-1 | **Streamlit Enrichment UI mit echten API-Keys testen.** Alle 4 Checkboxen (Regime, News, Calendar, Layering) mit realen Daten durchlaufen. | 1–2 Tage | UI-Validierung |
| P2-2 | **Fallback-Modus für Pine-Indikator implementieren.** Wenn Library stale (>2 Tage), sollte der Indikator grundlegende BOS/CHoCH-Erkennung ohne Backend leisten. | 3–5 Tage | Standalone-Fähigkeit |
| P2-3 | **Quick-Start-Dokumentation erstellen.** Von 121 Docs fehlt ein "Erster Produktivlauf in 30 Minuten"-Guide. | 1 Tag | Onboarding |
| P2-4 | **GitHub Actions erstmals produktiv auslösen.** Secrets konfigurieren, einen Lauf manuell triggern, Output validieren. | 1 Tag | CI/CD-Validierung |

### P3 — Backlog

| # | Maßnahme | Aufwand | Impact |
|---|---|---|---|
| P3-1 | **Strategy-Script (88 LOC) zu vollständigem Backtest ausbauen.** Minimum: Entry/Exit-Regeln auf Basis von SMC-Signalen, Drawdown-Metriken, Sharpe-Ratio. | 5–10 Tage | Backtestbarkeit |
| P3-2 | **GARCH-Parameter empirisch validieren.** `vol_regime.py` GARCH-Forecast mit 1+ Jahren Intraday-Daten kalibrieren. | 3–5 Tage | Regime-Qualität |
| P3-3 | **Live News Bus mit echten News-Feeds testen.** TIER-Klassifikation mit realen Benzinga/FMP-Events validieren. | 2–3 Tage | News-Validierung |
| P3-4 | **Provider Capability Matrix von "code-only" auf "validated" hochstufen.** Jeder Provider mindestens 1x mit echten Daten durchlaufen und Ergebnis dokumentieren. | 3–5 Tage | Provider-Vertrauen |

---

## Abschlussformat

### 1. Executive Summary

Siehe Kapitel-Kopf. Kernaussage: **Architektonisch durchdacht, operativ unzureichend belegt.** Der Library-Blocker (fixture-basierter Stand seit >2 Wochen) ist das dominierende Risiko.

### 2. Base Generator Scope Verdict

> Der Base Generator ist **code-complete, aber operativ blockiert.** 1.744 LOC Runtime + 654 LOC Streamlit UI + 4 Enrichment-Module = architektonisch bereit. Fuer die aktuelle Micro-Library ist kein sauber belegter publish-ready Lauf dokumentiert. Die Library (274 aktive Felder) exportiert AAA/BBB/CCC — das sind keine Marktdaten ⚠️.

### 3. Provider Capability Matrix

| Provider | Structure | Meta | Produktiv-Status |
|---|---|---|---|
| structure_artifact_json | Primary | — | Code-only ⚠️ |
| databento_watchlist_csv | Fallback | Partial | Code-only ⚠️ |
| fmp_watchlist_json | — | Primary (Technical) | Code-only ⚠️ |
| tradingview_watchlist_json | — | Fallback | Code-only ⚠️ |
| benzinga_watchlist_json | — | Primary (News) | Code-only ⚠️ |

### 4. Vergleich mit externen Benchmarks

| Kriterium | SkippALGO SMC | LuxAlgo SMC | ICT Community | thinkorswim |
|---|---|---|---|---|
| Feature-Tiefe | ✅✅✅ | ✅✅ | ✅ | ✅ |
| Operative Reife | ⚠️ | ✅✅✅ | ✅✅ | ✅✅✅ |
| Setup-Einfachheit | ⚠️ | ✅✅✅ | ✅✅✅ | ✅✅✅ |
| Standalone-Fähigkeit | ❌ | ✅ | ✅ | ✅ |
| Daten-Integration | ✅✅✅ | ❌ | ❌ | ❌ |
| Kalibrierung | ✅ (theoretisch) | ❌ | ❌ | ❌ |

**Fazit:** SkippALGO SMC hat den umfassendsten Feature-Satz aller verglichenen Systeme. Es ist gleichzeitig das einzige, das nie operativ validiert wurde. Die Kluft zwischen Ambition und Beweis ist der Kern dieses Reviews.

### 5. Test- und Evidenzlücken

| Lücke | Quantifizierung | Evidenzniveau |
|---|---|---|
| smc_core Test-Coverage | 14/81 Funktionen (17,3%) | 🧪 niedrig |
| scoring.py Tests | 0 Tests für 1.004 LOC | ⚠️ ungetestet |
| Produktive Library-Läufe | 0 | ⚠️ nie gelaufen |
| Provider-Validierung | 0/5 Provider produktiv | ⚠️ code-only |
| GitHub Actions Läufe | 0 | ⚠️ nie gelaufen |
| Enrichment UI mit Realdaten | 0 Durchläufe | ⚠️ nie getestet |
| Pine Backtest-Ergebnisse | 0 | ⚠️ nicht vorhanden |
| GARCH-Kalibrierung | 0 Datensätze | ⚠️ unkalibriert |
| News-Heat-Validierung | 0 Messungen | ⚠️ Schwellwerte willkürlich |

### 6. Priorisierter Maßnahmenplan

**BLOCKER (sofort):**
- B-1: Library erstmals produktiv ausführen
- B-2: API-Keys für ≥2 Provider beschaffen
- B-3: End-to-End-Lauf dokumentieren

**P1 (2 Wochen):**
- P1-1: Core Test-Coverage ≥50%
- P1-2: 158 deprecated Felder aufräumen
- P1-3: Event-Risk-Status klären
- P1-4: Scoring erste Kalibrierung

**P2 (4 Wochen):**
- P2-1: Streamlit UI mit echten Keys
- P2-2: Fallback-Modus für Pine
- P2-3: Quick-Start-Guide
- P2-4: GitHub Actions erstmals produktiv

**P3 (Backlog):**
- P3-1: Strategy-Script zu Backtest ausbauen
- P3-2: GARCH empirisch validieren
- P3-3: Live News Bus testen
- P3-4: Provider auf "validated" hochstufen

### 7. Optionaler nächster Schritt

**Empfohlener sofortiger nächster Schritt:** Einen lokalen Library-Lauf mit den 12 Release-Policy-Symbolen (AAPL, MSFT, AMZN, JPM, JNJ, XOM, CAT, PG, NEE, AMT, META, LIN) auf Timeframe 1H durchführen. Dafür werden API-Keys für mindestens `structure_artifact_json` und `fmp_watchlist_json` benötigt. Ziel: Ein einziges Library-Artefakt mit realen Daten generieren und manuell im Pine-Dashboard validieren. Dieser eine Schritt verwandelt das System von "theoretisch entworfen" in "erstmals operativ belegt" und entsperrt den gesamten Feedback-Loop für Scoring, Kalibrierung und Regime-Validierung.

---

*Quellen: Repository-Analyse `skippALGO/skipp-algo` Commit `92475e7e`, Branch `main`. Externe Benchmark-Daten: [LuxAlgo SMC Indicator](https://www.luxalgo.com/blog/smart-money-concept-indicator-for-tradingview-free/), [TradingView SMC Community Scripts](https://in.tradingview.com/scripts/smartmoneyconcept/), [ICT Smart Money Trading Suite (SwissAlgo)](https://www.tradingview.com/script/ygABdJp8-ICT-Smart-Money-Trading-Suite-SwissAlgo/), [thinkorswim SMC Community Port](https://usethinkscript.com/threads/smart-money-concepts-smc-luxalgo-for-thinkorswim.19143/). Stand: 08. April 2026.*

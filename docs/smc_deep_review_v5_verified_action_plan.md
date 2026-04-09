# SMC Deep Review v5: Verifikation und Action Plan

Stand: 2026-04-08
Quelle: `smc_deep_review_v5.md`

## Zweck

Dieses Dokument bewertet die wichtigsten Aussagen aus `smc_deep_review_v5.md`
gegen den aktuellen Repo-Stand auf `main` und leitet daraus einen belastbaren
Action Plan ab. Es ersetzt den Review nicht. Es grenzt nur ein, welche Findings
belegt, welche nur teilweise belegt und welche in der aktuellen Form zu stark
formuliert sind.

## Kurzfazit

Der operative Kernbefund des Reviews ist richtig, aber enger zu fassen:

- Das aktuelle generierte Micro-Library-Source-Artefakt ist nicht
  publish-ready.
- Der konkrete Blocker ist sichtbar und maschinenlesbar:
  `fixture_input`, `default_event_risk`, `placeholder_symbols`.
- Das Repo belegt aber nicht die Totalbehauptung "nie gelaufen" oder
  "keine operative Evidenz". Es gibt erfolgreiche Publish-/Preflight-Spuren und
  mehrere reale Artefakte mit echten Symbolen.

Die richtige Prioritaet ist daher nicht ein breiter Architektur-Umbau, sondern
der erste nachweislich publish-ready Library-Lauf mit echten Daten plus
saubere End-to-End-Evidenz.

## Verifizierte Findings

### V-1: Der aktuelle generierte Library-Stand ist fixture-basiert und stale

Belegt durch:

- `pine/generated/smc_micro_profiles_generated.pine`
  - `ASOF_DATE = "2026-03-23"`
  - `UNIVERSE_SIZE = 3`
  - Platzhalterlisten wie `AAA`, `BBB`, `CCC`
- `pine/generated/smc_micro_profiles_generated.json`
  - `input_path = tests/fixtures/seed_base_snapshot.csv`
  - `productivity_gate.publish_ready = false`
  - `fixture_input_detected = true`
  - `placeholder_symbols = [AAA, BBB, CCC]`

Bewertung:

- Dieser Finding-Block ist voll gerechtfertigt.
- Das ist der eigentliche Freigabe-Blocker fuer den produktiven SMC-Pfad.

### V-2: Der aktuelle Source-Stand ist trotz Publish-Spuren nicht produktiv freigegeben

Belegt durch:

- `artifacts/tradingview/library_release_manifest.json`
  - `publishedVersion = 1`
  - `publishStatus = "published"`
  - gleichzeitig `productivityGate.publishReady = false`
  - Blocking reasons: `fixture_input`, `default_event_risk`,
    `placeholder_symbols`

Bewertung:

- Entscheidend ist die Unterscheidung zwischen:
  - es existiert ein publiziertes TradingView-Artefakt
  - der aktuelle generierte Quellstand ist publish-ready
- Nur der zweite Punkt ist aktuell rot.

### V-3: Der Workflow-Pfad existiert und haengt real von Secrets ab

Belegt durch:

- `.github/workflows/smc-library-refresh.yml`
  - `workflow_dispatch` vorhanden
  - 4 Cron-Slots vorhanden
  - Secrets fuer `FMP_API_KEY`, `BENZINGA_API_KEY`, `DATABENTO_API_KEY`,
    `TV_STORAGE_STATE`, `GH_PAT` referenziert
  - Generator-Aufruf:
    `python scripts/generate_smc_micro_base_from_databento.py --run-scan --enrich-all`

Bewertung:

- Voll gerechtfertigt als operativer Schritt im Plan.
- Nicht gerechtfertigt als lokale Repo-Aussage "Secrets sind nicht konfiguriert".
  Das kann das Repo allein nicht beweisen.

### V-4: Boundary- und Delegations-Fortschritt seit frueheren Reviews ist real

Belegt durch:

- `open_prep_boundary.py`
- `smc_tv_bridge/smc_api.py`
- `tests/test_open_prep_boundary_regressions.py`
- `tests/test_smc_api_canonical_delegation.py`

Bewertung:

- Dieser positive Teil des Reviews trifft zu.
- Das spricht gegen einen grossen Architektur-Neustart als erste Reaktion.

### V-5: Event Risk ist weiterhin ein Mischzustand aus deprecated + konsumiert

Belegt durch:

- `pine/generated/smc_micro_profiles_generated.pine`
  - Kommentar: `Event Risk (v5, compatibility-only deprecated)`
  - Felder wie `EVENT_WINDOW_STATE`, `EVENT_RISK_LEVEL` werden weiter exportiert
- `SMC_Core_Engine.pine`
  - konsumiert mehrere `mp.EVENT_*`-Felder
- `SMC_Dashboard.pine`
  - Event-Risk-Zeilen weiter vorhanden
- gleichzeitig existiert `event_risk_light` in Tests und Integrationspfaden

Bewertung:

- Das Finding ist im Kern richtig.
- Es ist aber kein Sofort-Blocker vor dem ersten produktiven Lauf, sondern ein
  gezielter Konsolidierungspunkt direkt danach.

## Findings mit Korrekturbedarf

### K-1: "Kein einziger produktiver Lauf" ist in dieser Form zu absolut

Gegenbelege im Repo:

- `automation/tradingview/reports/publish-micro-library-2026-04-04T07-50-33-372Z.json`
  - `ok = true`
  - `publishOk = true`
  - `publishStatus = published`
- `docs/smc-validation-status.md`
  referenziert denselben erfolgreichen Publish-Report
- `reports/open_prep_ranked_candidates_20260221_081340Z.csv`
  enthaelt echte Symbole wie `AMZN`, `META`, `MSFT`
- `reports/smc_structure_artifact.json`
  enthaelt echte Symbole wie `AAPL`, `AMZN`, `META`, `MSFT`
- `artifacts/smc_microstructure_exports/smc_live_news_snapshot.json`
  enthaelt echte Symbole wie `AAPL`, `MSFT`, `AMZN`, `META`, `XOM`

Korrigierte Formulierung:

- Nicht: "es gab nie einen produktiven Lauf"
- Sondern: "es gibt noch keinen sauber belegten publish-ready Source-Stand fuer
  die aktuelle Micro-Library auf echten Daten"

### K-2: "GitHub Actions nie produktiv / keine Secrets konfiguriert" ist lokal nicht beweisbar

Was belegbar ist:

- der Workflow benoetigt Secrets
- der Workflow ist fuer produktiven Einsatz gedacht

Was lokal nicht belegbar ist:

- ob die Secrets in GitHub fehlen
- ob Workflows dort nie gelaufen sind

Korrigierte Formulierung:

- "Secrets und erster manueller Actions-Lauf muessen validiert werden"

### K-3: "scoring.py hat 0 Tests" ist falsch

Gegenbelege:

- `tests/test_smc_scoring.py`
- `tests/test_smc_vol_regime.py`
- `tests/test_smc_core_ensemble_quality.py`

Korrigierte Formulierung:

- Die Module sind getestet, aber noch nicht auf produktiven Daten kalibriert.
- Das ist etwas anderes als ungetestet.

### K-4: Die smc_core-Coverage-Zahl im Review ist zu eng oder veraltet

Gegenbelege:

- es existieren viele weitere `smc_core`-nahe Tests, unter anderem zu IDs,
  Layering, Signals, Schema, Purity, Sweep-Layering, Engine-Semantik,
  Zone-Style-Coverage und Event-Risk-Verhalten

Korrigierte Formulierung:

- Die exakte Funktionsabdeckung ist aus dem lokalen Repo nicht direkt als
  belastbare Prozentzahl ableitbar.
- Was man sicher sagen kann: Der Review unterschlaegt vorhandene Tests.

### K-5: "Kein Quick Start" ist nur teilweise richtig

Gegenbelege:

- `docs/SkippALGO_Deep_Technical_Documentation.md`
  enthaelt einen `Quick Start`
- `docs/smc-microstructure-ui-operator-runbook.md`
  beschreibt einen `publish-ready`-Pfad

Korrigierte Formulierung:

- Es fehlt eher ein schlanker, dedizierter SMC-First-Productive-Run-Guide,
  nicht allgemeine Einstiegsdokumentation ueberhaupt.

### K-6: "Provider sind code-only" ist zu grob

Gegenbelege:

- reale Open-Prep-Artefakte
- reale Structure-Artefakte
- reale Live-News-Artefakte
- echter Publish-/Preflight-Nachweis auf TradingView-Seite

Korrigierte Formulierung:

- Es fehlt nicht jede operative Evidenz.
- Es fehlt die durchgaengige, gruen belegte Produktivkette fuer die aktuelle
  generierte SMC-Micro-Library.

## Technischer Kern des Blockers

Der Blocker ist nicht abstrakt, sondern sehr konkret:

1. Die aktuell eingecheckte Library wurde aus dem Seed-CSV erzeugt.
2. Das Manifest markiert den Stand deshalb als nicht publish-ready.
3. Dieselben Kriterien werden zusaetzlich durch
   `scripts/verify_smc_micro_publish_contract.py` und zugehoerige Tests
   abgesichert.

Das eigentliche Arbeitsziel ist daher:

- von `tests/fixtures/seed_base_snapshot.csv` weg
- zu einem realen Scan-/Enrichment-Lauf hin
- mit gruenem `productivity_gate.publish_ready`

## Verifizierter Action Plan

## Phase 1: Ersten publish-ready Source-Stand herstellen

Ziel:

- Die generierte Micro-Library darf nicht mehr fixture-basiert sein.

Arbeitspakete:

- Den produktiven Generatorpfad ueber
  `scripts/generate_smc_micro_base_from_databento.py --run-scan --enrich-all`
  ausfuehren.
- Fuer einen echten lokalen Lauf mindestens folgende Inputs absichern:
  - `DATABENTO_API_KEY`
  - mindestens ein funktionierender Enrichment-Pfad ueber `FMP_API_KEY` und/oder
    `BENZINGA_API_KEY`
- Danach die erzeugten Artefakte gegen folgende Kriterien pruefen:
  - `input_path` zeigt nicht mehr auf `tests/fixtures/...`
  - `placeholder_symbols` ist leer
  - `fixture_input_detected = false`
  - `event_risk_source != defaults`
  - `productivity_gate.publish_ready = true`

Exit-Kriterien:

- `pine/generated/smc_micro_profiles_generated.json` ist publish-ready
- `scripts/verify_smc_micro_publish_contract.py` laeuft ohne Fehler
- `artifacts/tradingview/library_release_manifest.json` traegt keinen roten
  Productivity-Gate-Status mehr fuer den aktuellen Source-Stand

## Phase 2: End-to-End-Evidenz fuer den produktiven Pfad aufnehmen

Ziel:

- Nicht nur gruen generieren, sondern den gesamten SMC-Hauptpfad einmal sauber
  belegen.

Arbeitspakete:

- Das erzeugte Library-Artefakt nach TradingView publizieren
- Pine-Import in `SMC_Core_Engine.pine` gegen den aktuellen Importpfad pruefen
- den Hauptpfad mit dem bestehenden TradingView-Preflight erneut verifizieren
- die entstandenen Artefakte in `automation/tradingview/reports/` und den
  relevanten Docs referenzieren

Exit-Kriterien:

- neuer Publish-Report mit `ok = true`, `publishOk = true`
- SMC-Mainline-Preflight bleibt gruen
- mindestens ein dokumentierter End-to-End-Lauf mit echten Daten ist vorhanden

## Phase 3: Provider- und Credential-Realitaet explizit verifizieren

Ziel:

- Aus plausiblen Annahmen werden dokumentierte Ist-Zustaende.

Arbeitspakete:

- minimalen Credential-Satz fuer lokalen Produktivlauf dokumentieren
- separaten Credential-Satz fuer GitHub Actions dokumentieren
  - `DATABENTO_API_KEY`
  - `FMP_API_KEY`
  - `BENZINGA_API_KEY`
  - `TV_STORAGE_STATE`
  - `GH_PAT`
- einen manuellen `workflow_dispatch`-Lauf von
  `.github/workflows/smc-library-refresh.yml` ausfuehren und archivieren
- degradierte Provider explizit festhalten, zum Beispiel FMP-Planlimit- oder
  401-Faelle

Exit-Kriterien:

- erster erfolgreicher manueller Actions-Lauf ist dokumentiert oder mit
  konkreten Fehlercodes gescheitert
- Provider-Status ist nicht mehr "code-only" formuliert, sondern anhand echter
  Ergebnisse beschrieben

## Phase 4: Produktive Folgemaßnahmen nach dem ersten echten Lauf

Ziel:

- Erst jetzt die groesseren Architektur- und Konsolidierungsfragen anfassen.

Arbeitspakete:

- Event-Risk-Pfad entscheiden:
  - Lean-only priorisieren und breite Compatibility-Felder schrittweise
    abbauen
  - oder Broad + Lean bewusst parallel halten und dokumentieren
- erste echte Scoring-/Calibration-Evidenz aus produktiven Daten erzeugen
- dedizierten "First Productive Run"-Guide schreiben
- Validation-Status-Dokumente auf den echten Produktionspfad aktualisieren

Exit-Kriterien:

- Event-Risk-Strategie ist festgelegt
- erste reale Kalibrierungs- oder Benchmark-Artefakte existieren
- Onboarding fuer den produktiven SMC-Pfad ist in einem kompakten Guide
  dokumentiert

## Bewusst nicht erste Prioritaet

Diese Punkte sind sinnvoll, aber nicht vor Phase 1/2:

- pauschales Ziel "smc_core auf >=50% Coverage"
- Pine-Standalone-Fallback-Modus
- grossflaechige Entfernung aller deprecated Felder
- groesserer Strategy-/Backtest-Ausbau
- empirische GARCH-Feinjustierung

Begruendung:

- Solange der erste publish-ready Lauf fehlt, erzeugen diese Arbeiten zwar
  Strukturverbesserung, aber noch keine belastbare Betriebs-Evidenz fuer den
  eigentlichen Hauptpfad.

## Empfohlener Sofortschritt

Der naechste konkrete Schritt ist:

1. Den Generatorpfad mit echten Daten lokal oder per `workflow_dispatch`
   laufen lassen.
2. Danach strikt auf `publish_ready`, `event_risk_source`, `input_path` und
   `placeholder_symbols` schauen.
3. Erst wenn diese vier Signale gruen sind, den Publish-/Preflight-End-to-End-
   Pfad erneut fahren.

Der konkrete lokale Ablauf dafuer ist in
`docs/smc_local_first_productive_run.md` beschrieben.

Das adressiert den echten Blocker direkt an der Wurzel und trennt ihn sauber
von den im Review mitlaufenden, aber nachrangigen Architekturthemen.

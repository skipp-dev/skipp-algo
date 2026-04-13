# SMC Deep Review v9: Verifikation und Action Plan

Stand: 2026-04-13
Quelle: externer Review `smc_deep_review_v9.md`

## Zweck

Dieses Dokument bewertet die wichtigsten Aussagen aus dem v9-Review gegen den
aktuellen Repo-Stand auf `main` und leitet daraus einen belastbaren Action Plan
ab. Es ersetzt den Review nicht. Es trennt nur zwischen:

- verifizierten Findings
- Review-Drift oder Uebertreibungen
- den naechsten sinnvollen Implementierungsschritten

## Kurzfazit

Der Review ist in der Richtung nuetzlich, aber an mehreren Stellen zu gross
geschnitten.

Die wichtigsten Korrekturen sind:

- Es gibt aktuell sehr wohl einen harten produktiven Blocker: der eingecheckte
  generierte Library-Stand ist laut Produktivitaets-Gate nicht publish-ready.
- `bias_merge.py` und `benchmark.py` sind nicht "unklar produktiv", sondern in
  produktiven Integrationspfaden importiert.
- Die Pine-Hauptlinie konsumiert PE-Felder direkt, aber die neuen
  Library-Felder fuer Volatility und Ensemble werden in den aktiven Pine-
  Consumern noch nicht direkt gelesen.
- Die Repo-Tests fuer Macro Scope, News-Polarity/Snippet-Nutzung,
  PE-Fallbacks und Pre-Market-Timing existieren bereits. Der Gap liegt weniger
  bei fehlender Unit-Abdeckung als bei produktiver End-to-End-Evidenz und bei
  noch fehlenden Pine-Consumern fuer die neuen Library-Domaenen.

Die richtige Reihenfolge ist daher:

1. produktiven Library-Source-Stand gruen bekommen
2. Review-P1 fuer Volatility/Ensemble sauber in Pine einhaengen
3. operative Fallback- und Workflow-Haertung gezielt testen
4. erst danach Cleanup und groessere Scope-Erweiterungen angehen

## Verifizierte Findings

### V-1: Der aktuelle generierte Library-Stand ist nicht publish-ready

Belegt durch:

- `artifacts/tradingview/library_release_manifest.json`
  - `publishStatus = "published"`
  - gleichzeitig `productivityGate.publishReady = false`
  - Blocking reasons: `fixture_input`, `default_event_risk`,
    `placeholder_symbols`
- `pine/generated/smc_micro_profiles_generated.json`
  - `event_risk_source = "defaults"`
  - `productivity_gate.publish_ready = false`
  - `fixture_input_detected = true`
  - `default_event_risk_detected = true`
  - `placeholder_symbols = ["AAA", "BBB", "CCC"]`

Bewertung:

- Das Review-Statement "Keine Blocker" ist in der aktuellen Repo-Lage nicht
  haltbar.
- Der erste Action-Plan-Punkt darf deshalb nicht nur "auf den naechsten Run
  warten" sein, sondern muss den produktiven Gate-Wechsel auf gruen als
  messbares Ziel definieren.

### V-2: PE ist in der Pine-Hauptlinie bereits direkt konsumiert

Belegt durch:

- `SMC_Core_Engine.pine`
  - `mp.MARKET_PE_FORWARD`
  - `mp.MARKET_PE_REGIME`
  - `mp.MACRO_BIAS_PE_ADJUSTMENT`
  - daraus abgeleitete `lib_market_valuation_caution`

Bewertung:

- Das P1-Item "PE in Pine" ist erledigt.
- Es braucht hier keinen neuen Implementierungspunkt, sondern nur Regression-
  Schutz.

### V-3: Volatility und Ensemble sind im Backend/Library-Vertrag vorhanden, aber nicht direkt im aktiven Pine-Consumer verankert

Belegt durch:

- Generator-, Contract- und Pipeline-Tests exportieren und pruefen:
  - `VOLATILITY_REGIME`, `VOLATILITY_REGIME_CONFIDENCE`,
    `VOLATILITY_ATR_RATIO`, `VOLATILITY_MODEL_SOURCE`,
    `VOLATILITY_FALLBACK_REASON`, `VOLATILITY_PROXY_SYMBOL`,
    `VOLATILITY_PROXY_SOURCE`
  - `ENSEMBLE_QUALITY_SCORE`, `ENSEMBLE_QUALITY_TIER`,
    `ENSEMBLE_AVAILABLE_COMPONENTS`
- `SMC_Core_Engine.pine` hat keine direkten `mp.VOLATILITY_*`- oder
  `mp.ENSEMBLE_*`-Referenzen.
- Die bestehende Pine-Volatility-Logik ist lokal berechnet (`compute_vol_regime`
  plus `use_volatility_regime`) und nicht aus der Library gelesen.

Bewertung:

- Das Review-Finding ist im Kern richtig.
- Der Action Plan muss aber explizit vermeiden, zweite Schattenlogik
  einzubauen. Erstentscheidung ist deshalb:
  - entweder Library-Volatility zunaechst nur anzeigen
  - oder die lokale Pine-Volatility-Logik bewusst durch Library-Werte ersetzen
  - aber nicht beides parallel als fachliche Gate-Quelle betreiben

### V-4: `bias_merge.py` und `benchmark.py` sind produktiv genutzt

Belegt durch:

- `smc_integration/service.py`
  - `from smc_core.benchmark import BenchmarkResult, build_benchmark`
  - `from smc_core.bias_merge import merge_bias`
- `smc_integration/measurement_evidence.py`
  - `from smc_core.bias_merge import merge_bias`
  - `from smc_core.benchmark import EventFamily`
- `scripts/run_smc_measurement_benchmark.py`
- `scripts/run_smc_release_gates.py`

Bewertung:

- Die Review-Punkte `bias_merge.py Import-Status klaeren` und
  `benchmark.py Import-Status klaeren` sind ueberholt.
- Das sind keine offenen Arbeitsauftraege mehr.

### V-5: Macro Scope, News Snippet/Polarity, PE-Fallbacks und Pre-Market-Timing sind testseitig bereits gut belegt

Belegt durch:

- `tests/test_smc_macro_bias.py`
  - Non-US-USD-Rejection
  - US-Alias-Normalisierung
  - Consensus-/Dedupe-Verhalten
- `tests/test_smc_news_scorer.py`
  - Snippet-basierte positive/negative/neutral-Verteilung
- `tests/test_smc_fmp_client_isolation.py`
  - `get_market_pe_forward` faellt auf alternatives Marktsymbol zurueck
- `tests/test_generate_databento_watchlist.py`
  - vor/nach `04:00 ET`
  - fruehe Anchor-Profile
  - duenne Pre-Market-Profile
  - Relax-Fallbacks
- `tests/test_v4_pipeline_e2e.py`
  - Regime/PE/Volatility/Ensemble im Enrichment-Pfad
  - News-Diagnostik mit `polarity_distribution`

Bewertung:

- Der Review hat Recht, dass diese Fixes deployed sind.
- Die verbleibende Luecke ist nicht primaer Unit-Test-Abdeckung, sondern der
  produktive Nachweis auf echten Inputs.

### V-6: Modal-Recovery und Push-Retry sind im Code, aber nicht als gezielte E2E-Regression abgesichert

Belegt durch:

- `automation/tradingview/lib/tv_shared.ts`
  - `ensurePineEditor` enthaelt wiederholte `closeModal(...)`-Recovery-Versuche
- `.github/workflows/smc-library-refresh.yml`
  - `git push` mit bis zu drei Versuchen
  - `fetch + rebase + retry` bei Push-Reject

Bewertung:

- Das Review ist hier plausibel bis korrekt.
- Die richtige Konsequenz ist ein gezielter Regression-Harness fuer diese
  Pfade, nicht nur eine textliche Notiz im Review.

### V-7: Benzinga-Fallback ist weiterhin ein sinnvoller operativer Gap

Belegt durch:

- Provider-Policy und Fallback-Pfade existieren im Code.
- Im aktuell verifizierten Stand liegt aber keine direkte operative Evidenz
  fuer einen bewusst durchgefahrenen Benzinga-Fallback-Lauf vor.

Bewertung:

- Dieses P1/P2-Thema bleibt sinnvoll.
- Es ist kein Architekturproblem, sondern ein kontrollierter
  Betriebs-/Validierungsschritt.

## Findings mit Korrekturbedarf

### K-1: "Keine Blocker" ist zu stark formuliert

Korrektur:

- Es gibt einen klaren produktiven Blocker fuer den aktuellen generierten
  Library-Source-Stand: `publishReady = false`.
- Das muss im Plan als Phase 0 gefuehrt werden.

### K-2: Die Workflow-Inventur ist nur als grobe Betriebsbeschreibung brauchbar

Repo-Stand:

- `.github/workflows/` enthaelt 7 Workflow-Dateien
  - `ci.yml`
  - `smc-deeper-integration-gates.yml`
  - `smc-fast-pr-gates.yml`
  - `smc-library-refresh.yml`
  - `smc-live-newsapi-refresh.yml`
  - `smc-measurement-benchmark.yml`
  - `smc-release-gates.yml`

Korrektur:

- Die Review-Tabelle beschreibt eher Betriebsfaehigkeiten als die exakte
  Workflow-Dateiliste.
- Das ist fuer Architekturtext ok, aber kein belastbares Umsetzungs-Backlog.

### K-3: `MARKET_REGIME != NEUTRAL` taugt nicht als harte Abnahmebedingung

Korrektur:

- `SECTOR_BREADTH`, `NEWS_*`, `MACRO_BIAS`, `MARKET_PE_FORWARD` und
  `productivity_gate` koennen harte Akzeptanzkriterien sein.
- `MARKET_REGIME != NEUTRAL` bleibt datenabhaengig und darf nur als
  Beobachtungskriterium gelten.

### K-4: Die Review-Punkte zu `bias_merge.py` und `benchmark.py` sind keine offenen Aufgaben mehr

Korrektur:

- Diese Punkte aus dem Review nicht in den neuen Plan uebernehmen.

## Action Plan

## Phase 0: Produktivitaets-Gate auf gruen bringen

Ziel:

- Der generierte Library-Source-Stand muss von fixture/default/placeholder auf
  einen produktiven Stand wechseln.

Konkrete Schritte:

1. Den `smc-library-refresh`-Pfad auf echten Inputs durchlaufen lassen oder
   lokal aequivalent vorbereiten.
2. Danach diese Artefakte pruefen:
   - `pine/generated/smc_micro_profiles_generated.json`
   - `artifacts/tradingview/library_release_manifest.json`
3. Erfolg nur dann als erreicht markieren, wenn alle Bedingungen gelten:
   - `productivity_gate.publish_ready = true`
   - `fixture_input_detected = false`
   - `default_event_risk_detected = false`
   - `placeholder_symbols = []`
   - `productivityGate.publishReady = true` im Release-Manifest

Warum zuerst:

- Solange dieser Schritt rot ist, sind alle weiteren Review-Aussagen zur
  vollen Produktionsreife vorzeitig.

## Phase 1: Verifizierte v9-Fixes auf echtem Run validieren

Ziel:

- Die im Review genannten Backend-Fixes sollen nicht nur unit-getestet,
  sondern auf einem echten Refresh-Lauf sichtbar sein.

Konkrete Checks:

1. `SECTOR_BREADTH` ist nicht mehr Template-Default.
2. `NEWS_BULLISH`/`NEWS_BEARISH` bzw. die zugrunde liegenden
   News-Diagnostiken zeigen nicht-leere echte Daten, wenn FMP Snippets liefert.
3. `MACRO_BIAS` ist nicht auf Default-/Fixture-Niveau eingefroren.
4. `MARKET_PE_FORWARD` und `MARKET_PE_REGIME` sind aus echten Inputs befuellt.
5. `publishReady` bleibt gruen nach dem Refresh.

Hinweis:

- `MARKET_REGIME != NEUTRAL` nicht als Pflichtkriterium verwenden.

## Phase 2: Volatility und Ensemble sauber in Pine einhaengen

Ziel:

- Die neuen Library-Domaenen sollen im aktiven Pine-Pfad sichtbar werden,
  ohne NO_SHADOW_LOGIC_POLICY zu verletzen.

Empfohlene Reihenfolge:

1. **Ensemble zuerst, display-only**
   - `ENSEMBLE_QUALITY_SCORE`
   - `ENSEMBLE_QUALITY_TIER`
   - `ENSEMBLE_AVAILABLE_COMPONENTS`
2. **Volatility danach, zunaechst display-only oder diagnostisch**
   - `VOLATILITY_REGIME`
   - `VOLATILITY_REGIME_CONFIDENCE`
   - `VOLATILITY_MODEL_SOURCE`
   - `VOLATILITY_FALLBACK_REASON`

Implementierungsprinzipien:

- Dashboard und Strategy bleiben bus-/manifest-getrieben.
- Neue Felder nicht einfach direkt in mehrere Consumer streuen.
- Bei neuen BUS-Kanaelen Plot-Budget und Manifest synchron pruefen.
- Fuer Volatility keine zweite fachliche Gate-Quelle neben lokaler
  `compute_vol_regime()` einbauen, solange die Prioritaet nicht bewusst
  umgestellt wurde.

Minimale Abnahme fuer diese Phase:

1. sichtbarer Consumer fuer Ensemble im aktiven Pine-Pfad
2. sichtbarer Consumer fuer Library-Volatility im aktiven Pine-Pfad
3. passende Contract-/Semantic-Tests fuer Export und Consumer-Bindung

## Phase 3: Operative Regression-Haertung

Ziel:

- Die neuen v9-Haertungen gegen TradingView-/GitHub-Automationsprobleme sollen
  reproduzierbar abgesichert werden.

Konkrete Punkte:

1. **Benzinga-Fallback gezielt validieren**
   - FMP fuer News/Calendar kontrolliert deaktivieren oder mocken
   - Erfolgskriterium: klarer Fallback-Nachweis in Diagnostik/Artefakten
2. **`ensurePineEditor`-Recovery regressionstestbar machen**
   - Modal-blocked Zustand simulieren
   - Erfolgskriterium: Recovery ueber internen `closeModal`-Pfad
3. **Push-Retry-Harness absichern**
   - Konflikt-/Reject-Szenario simulieren
   - Erfolgskriterium: Retry mit `fetch + rebase + push` arbeitet wie erwartet

## Phase 4: Cleanup nach gruener Produktionsbasis

Ziel:

- Erst nach produktiv gruener Kette die Repo-Komplexitaet reduzieren.

Konkrete Punkte:

1. deprecated Pine-Dateien entfernen
2. `SkippALGO.pine` entfernen, falls wirklich abgeloest und ohne Restkonsumenten
3. Sunset-Plan fuer Compatibility-Felder schreiben

Bewertung:

- Diese Punkte sind sinnvoll, aber nicht vor Phase 0 bis 3.

## Nicht in den Plan uebernehmen

- `bias_merge.py Import-Status klaeren`
- `benchmark.py Import-Status klaeren`
- `MARKET_REGIME != NEUTRAL` als harte Abnahmebedingung
- ein grosser Architekturumbau vor dem ersten gruenen produktiven Library-Run

## Priorisierte Reihenfolge

### P0

- Produktivitaets-Gate auf gruen bringen

### P1

- echten Refresh-Lauf validieren
- Ensemble in Pine konsumieren
- Library-Volatility in Pine konsumieren
- Benzinga-Fallback operativ pruefen

### P2

- E2E-Regressionsschutz fuer Modal-Recovery
- E2E- oder Harness-Regressionsschutz fuer Push-Retry

### P3

- deprecated Pine-Cleanup
- Compatibility-Sunset-Plan
- spaetere Scope-Themen wie ETF-Expansion oder Health-Dashboard

## Schlussbewertung

Der v9-Review ist als Lagebild brauchbar, aber nicht 1:1 als Backlog.

Belastbar und umsetzungsreif sind vor allem diese Punkte:

- produktiver Library-Stand noch blockiert
- PE bereits sauber in Pine
- Volatility/Ensemble noch ohne direkten aktiven Pine-Consumer
- Benzinga-Fallback weiter sinnvoll als Validierungsziel
- Modal-Recovery und Push-Retry im Code, aber noch ohne gezielten
  Regressionsharness

Der naechste sinnvolle Commit ist daher nicht eine breite Codewelle, sondern
dieser verifizierte Plan als Arbeitsgrundlage fuer die eigentliche Umsetzung.

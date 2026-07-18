# Databento Dataset- und Subscription-Optimierung: Action Plan

Stand: 2026-07-18
Status: zur Umsetzung durch den naechsten Agenten
Ausgangsbasis: aktuelles `origin/main`; lokale Haupt-Working-Copy ist nicht als
Implementierungsort geeignet, da sie bereits fremde Aenderungen enthaelt
Subscription-Stichtag: 2026-08-01

## 1. Auftrag und Endzustand

Der naechste Agent soll die Databento-Nutzung so umbauen, dass jedes Dataset
eine eindeutige fachliche Rolle besitzt, keine Pipeline ihre Semantik durch eine
globale Fallback-Reihenfolge wechselt und die beiden bezahlten Subscriptions
messbar genutzt oder begruendet beendet werden koennen.

Der Auftrag ist erst abgeschlossen, wenn:

1. die vertauschte Databento-Aggressor-Semantik korrigiert und regressionsfest
   ist;
2. Katalogsicht, historischer Zugriff und Live-Entitlement nicht mehr
   verwechselt werden;
3. produktive Dataset-Auswahl ueber explizite Rollen statt ueber eine globale
   Rangfolge erfolgt;
4. `EQUS.MINI` die breite Equity-Live-Basis und `EQUS.SUMMARY` die kanonische
   Tagesbasis ist;
5. neue produktive Pfade `DBEQ.BASIC` nicht mehr als Default verwenden;
6. NYSE Arca korrekt als `ARCX`/`ARCX.PILLAR` modelliert ist;
7. venue-spezifische Daten nicht mehr unbemerkt konsolidierte Basisbars
   ueberschreiben;
8. OPRA entweder als echter Live-Shadow-Consumer arbeitet und seinen Nutzen
   belegt oder die Verlangerung nachvollziehbar abgelehnt wird;
9. Dataset-, Schema-, Kosten- und Nutzentelemetrie eine Subscription-
   Entscheidung ermoeglicht;
10. veraltete Behauptungen ueber einen Pine-/TradingView-HTTP-Consumer aus dem
    Repository entfernt und durch einen Suchtest gegen Wiederkehr geschuetzt
    sind.

Nicht Teil dieses Programms ist der Abschluss weiterer Databento-
Subscriptions. `GLBX.MDP3`, `OCEA.MEMOIR` und weitere Datasets duerfen nur als
historische, kostenabgeschaetzte Forschungsvorhaben betrachtet werden.

## 2. Verbindliche Dataset-Rollen

Diese Matrix ist die fachliche Zielvorgabe. Ein Dataset darf nicht
stillschweigend eine andere Rolle ersetzen.

| Rolle | Dataset | Modus | Zweck |
| --- | --- | --- | --- |
| `EQUITY_LIVE_BROAD` | `EQUS.MINI` | Live | breite Equity-Bars und aggregierte L1-/Trade-Sicht |
| `EQUITY_INTRADAY_PARITY` | `EQUS.MINI` | Historical/Live | gleiche Quellensemantik fuer Training und Live-Auswertung |
| `EQUITY_EOD_CANONICAL` | `EQUS.SUMMARY` | Historical | Daily OHLC, Previous Close, konsolidiertes Tagesvolumen, EOD-Abgleich |
| `VENUE_NASDAQ_DEPTH` | `XNAS.ITCH` | Historical oder explizit lizenziertes Live | Nasdaq-Orderbuch-, Auction- und Venue-Features |
| `VENUE_NYSE` | `XNYS.PILLAR` | Historical oder explizit lizenziertes Live | NYSE-spezifische Features |
| `VENUE_AMERICAN` | `XASE.PILLAR` | Historical oder explizit lizenziertes Live | NYSE-American-/AMEX-spezifische Features |
| `VENUE_ARCA` | `ARCX.PILLAR` | zunaechst Historical | NYSE-Arca- und ETF-spezifische Features |
| `EQUITY_BROAD_TRADES_RESEARCH` | `XNAS.BASIC` | zunaechst Historical | Nasdaq-Venues plus TRF-orientierte Forschung |
| `OPTIONS_LIVE` | `OPRA.PILLAR` | Live | Options-Flow, TCBBO/Trades und UOA |
| `FUTURES_RESEARCH` | `GLBX.MDP3` | Historical PAYG | ES/NQ-/Futures-Regime nur nach separater Studie |
| `OVERNIGHT_RESEARCH` | `OCEA.MEMOIR` | Historical PAYG | 20:00-04:00-ET-Forschung nur nach separater Studie |

Zulaessige Degradation geschieht innerhalb derselben Rolle, zum Beispiel
Last-Good-Snapshot oder klar markierter Delayed-Modus. Ein Wechsel von
konsolidierten Equity-Bars auf eine einzelne Boerse ist kein Fallback, sondern
ein Semantikwechsel und muss fehlschlagen.

## 3. Ausfuehrungsregeln fuer den Agenten

### 3.1 Arbeitsweise

- Vor jedem Arbeitspaket `git fetch origin --prune` ausfuehren.
- Pro PR einen frischen Sibling-Worktree von `origin/main` verwenden.
- Den Skill `skipp-pr-flow` fuer jeden zu landenden PR befolgen.
- Keine vorhandenen Aenderungen im Haupt-Checkout uebernehmen, restoren oder
  bereinigen.
- Vor dem Fix aktuelle offene PRs auf Ueberschneidung pruefen. Bei einem
  ueberlappenden PR nicht doppelt implementieren.
- Kleine, fachlich geschlossene PRs erstellen. Kein Sammel-PR fuer das gesamte
  Programm.
- Line-pin-/Ledger-Guards, Ruff und zielgerichtete Tests vor jedem Commit
  ausfuehren.
- Externe PR-Erstellung, Kommentare, Workflow-Dispatches, Deployments oder
  credential-gestuetzte Live-Abfragen erst nach der dafuer vorgeschriebenen
  konkreten Freigabe ausfuehren.

Beispiel fuer den lokalen Start eines Arbeitspakets:

```bash
git fetch origin --prune
git worktree add ../skipp-algo-wt-<task> -b fix/<task> origin/main
cd ../skipp-algo-wt-<task>
```

### 3.2 Sicherheits- und Produktregeln

- API-Keys nie loggen, in Testartefakte schreiben oder in Exceptions
  ungefiltert weiterreichen.
- Neue Live-Consumer beginnen mit `off`, danach `shadow`, danach `observe`.
- Kein neues OPRA-Signal darf vor Promotion produktive Nutzerwirkung oder
  bestehende Alerts veraendern.
- Keine grossen Historical-Abfragen ohne vorherige Kostenabschaetzung.
- Historische Verfuegbarkeit darf nicht als Live-Entitlement bezeichnet
  werden.
- Ein leerer Datenrahmen darf nicht als erfolgreicher Datenabruf gewertet
  werden, wenn das angeforderte Ende neuer als `available_end` ist.

## 4. Abhaengigkeiten und Reihenfolge

```text
DBO-000 Baseline und Inventar
   |
   +--> DBO-100 Aggressor-Semantik -----+
   |                                    |
   +--> DBO-110 Dataset-Zugriffsvertrag +--> DBO-500 OPRA Live Shadow
   |                                              |
   |                                              +--> DBO-505 UI-Entkopplung
   |                                              |
   |                                              +--> DBO-510 Messfenster
   |                                                        |
   |                                                        v
   |                                              DBO-600 Subscription-Entscheid
   |
   v
DBO-120 Rollenbasierte Auswahl
   |
   +--------------------+
   |                    |
   v                    v
DBO-200 EQUS.SUMMARY   DBO-300 ARCA/Venue-Semantik
   |                    |
   +----------+---------+
              v
       DBO-400 Gesamttelemetrie

DBO-050 TradingView-Dokument-Cleanup ist unabhaengig und soll frueh als
eigener Dokumentations-PR erledigt werden.
```

DBO-100 und DBO-110 sind Correctness-Gates. Kein neuer Live- oder
Produktionspfad darf vorher promotet werden. Wegen des Renewal-Stichtags wird
DBO-500 unmittelbar danach im Shadow gestartet. Er bringt die fuer die
OPRA-Entscheidung zwingenden lokalen Metriken selbst mit; DBO-400 generalisiert
diese spaeter fuer alle Databento-Consumer. Die Equity-Migration blockiert das
OPRA-Messfenster dadurch nicht.

## 5. Arbeitspakete

### DBO-000: Baseline, Zugriffsinventar und Kostenbild einfrieren

**Ziel**

Vor Codeaenderungen einen reproduzierbaren Ist-Stand herstellen. Diese Aufgabe
ist read-only und erzeugt nur lokale, nicht geheime Artefakte.

**Arbeiten**

1. Aktuelles `origin/main`, offene PRs und gesetzte GitHub-Variablen erfassen.
2. Alle produktiven Dataset-Defaults und Overrides inventarisieren:
   `DATABENTO_DATASET`, `DBEQ.BASIC`, `EQUS.MINI`, `EQUS.SUMMARY`,
   `XNAS.ITCH`, `XNAS.BASIC`, `XNYS.PILLAR`, `XASE.PILLAR`, `ARCX.PILLAR`,
   `OPRA.PILLAR` und `GLBX.MDP3`.
3. Pro Fundstelle klassifizieren:
   - produktiver Runtime-Default;
   - Workflow-Konfiguration;
   - Forschungs-/CLI-Default;
   - Testfixture;
   - altes Manifest/Archiv;
   - Dokumentation.
4. Vorhandene Databento-Portal-Usage nach Dataset fuer den laufenden und den
   vorherigen Abrechnungsmonat lokal sichern, sofern eine konkrete Freigabe
   fuer diesen Abruf vorliegt.
5. Fuer die letzten zehn erfolgreichen Production-Export-Runs Dauer,
   Dataset-Angabe, Cache-Status, Row Counts und Fehler erfassen. Fehlende
   Messwerte explizit als `unknown` markieren.

**Vorgeschlagenes Artefakt**

`artifacts/monitoring/databento_usage_baseline_2026-07-18.json` plus eine kurze
Markdown-Auswertung. Keine Keys, Request-Header oder Rohdaten einchecken.

**Abnahme**

- Jede Runtime-Fundstelle besitzt genau eine Klassifikation.
- Subscription-Kosten sind getrennt von zusaetzlichen Exchange-/Lizenzkosten.
- Unbekannte Usage wird nicht als Nullnutzung interpretiert.
- Die Baseline veraendert weder Workflows noch externe Systeme.

**Zeitbedarf:** 0,5 bis 1 Tag.

---

### DBO-050: Veraltete TradingView-Provider-/HTTP-Consumer-Behauptungen entfernen

**Ziel**

Die bereits verworfene TradingView-Provider-Integration darf bei einer
Repository-Suche nicht mehr als implementierbare oder aktive Loesung
erscheinen. Legitime Pine-Skripte, Publish-Automation und TradingView-E2E-Tests
bleiben erhalten.

**Betroffene Startpunkte**

- `services/live_overlay_daemon/README.md`, insbesondere der alte
  `request.raw`-/Pine-Consumer-Abschnitt;
- `services/live_overlay_daemon/OPS.md`;
- ADR-0028 und Verweise darauf;
- weitere Treffer fuer `request.raw`, `TradingView provider`,
  `Pine HTTP consumer`, `TV bridge` und sinngleiche Versprechen.

**Arbeiten**

1. Treffer in vier Klassen teilen: aktive legitime TradingView-Funktion,
   historische Notiz, falsches Produktversprechen, Test-/Negativbeleg.
2. Falsche Produktversprechen und Implementierungsanleitungen entfernen.
3. Historische Erklaerungen nur behalten, wenn sie unmissverstaendlich die
   Nichtverfuegbarkeit dokumentieren und nicht wie eine aktuelle Integration
   wirken.
4. Einen kleinen Repository-Truth-Test ergaenzen, der verbotene
   Consumer-Behauptungen in aktiver Dokumentation erkennt. Der Test darf
   legitime TradingView-Publish- und Pine-Begriffe nicht pauschal verbieten.

**Abnahme**

```bash
rg -n "request\.raw|TradingView[- ]Provider|Pine HTTP consumer" docs services README.md
```

liefert keine aktive Integrationsanleitung. Der neue Negativtest ist gruen.

**Zeitbedarf:** 0,5 Tag.

---

### DBO-100: Databento-Aggressor-Semantik korrigieren

**Ziel**

Alle Trade-Pfade verwenden denselben Databento-Vertrag:

- `B` = Buy Aggressor;
- `A` = Sell Aggressor;
- `N`/unbekannt = neutral.

**Betroffene Dateien**

- `scripts/smc_trades_microstructure.py`
- `scripts/smc_flow_qualifier.py`
- `scripts/pull_databento_edge_input.py` als bereits korrekte Referenz
- `tests/test_smc_trades_microstructure.py`
- `tests/test_smc_flow_qualifier.py`
- alle Tests, die daraus abgeleitete Flow-Richtung erwarten

**Arbeiten**

1. Konstanten und Docstring korrigieren.
2. DataFrame- und Iterable-Pfad mit derselben Golden Fixture testen.
3. Eine asymmetrische Fixture verwenden, damit eine Vertauschung nicht durch
   50/50-Daten verborgen bleibt.
4. Downstream-Test sichern: mehr `B`-Volumen muss positives Delta, mehr
   `A`-Volumen negatives Delta ergeben.
5. Tests und Artefakte pruefen, die bisher die falsche Richtung festschreiben;
   nur echte Erwartungen aendern, keine pauschalen Snapshots neu erzeugen.

**Abnahme**

```bash
.venv/bin/python -m pytest \
  tests/test_smc_trades_microstructure.py \
  tests/test_smc_flow_qualifier.py \
  tests/test_smc_live_overlay_endpoint.py -q
.venv/bin/python -m ruff check scripts/smc_trades_microstructure.py \
  scripts/smc_flow_qualifier.py tests/test_smc_trades_microstructure.py \
  tests/test_smc_flow_qualifier.py
git diff --check
```

**Rollback:** reiner Code-Rollback; keine Datenmigration. Historische, mit der
falschen Semantik erzeugte Artefakte muessen als solche markiert und duerfen
nicht still neu interpretiert werden.

**Zeitbedarf:** 0,5 bis 1 Tag.

---

### DBO-110: Katalog, Historical Access und Live-Entitlement trennen

**Ziel**

`metadata.list_datasets()` wird nur noch als Katalogabfrage bezeichnet. Kein
Code darf daraus behaupten, ein Key sei fuer ein Dataset entitled.

**Betroffene Dateien**

- `databento_provider.py`
- `databento_client.py`
- `databento_utils.py`
- `scripts/probe_providers.py`
- `scripts/probe_databento_entitlement.py`
- `scripts/databento_preopen_fast.py`
- `scripts/smc_micro_streamlit_app.py`
- zugehoerige Tests

**Vorgeschlagener Vertrag**

```python
class DatasetAccessStatus:
    catalog_present: bool
    historical_range_available: bool | None
    historical_start: str | None
    historical_end: str | None
    live_checked: bool
    live_entitled: bool | None
    reason: str
```

Die genaue Form darf repo-konform angepasst werden, die drei Wahrheiten
muessen jedoch getrennt bleiben.

**Arbeiten**

1. `list_accessible_datasets` deprecaten und in `list_catalog_datasets`
   umbenennen. Kompatibilitaetsalias nur mit Warning und ohne falschen
   Docstring belassen.
2. Historische Zugriffssicht ueber `metadata.get_dataset_range(dataset)`
   implementieren. Ein vorhandener Zeitraum belegt historischen Zugriff,
   nicht Live-Zugriff.
3. Live-Entitlement nur durch einen expliziten, kleinen Live-Subscribe-Probe
   oder einen vom Anbieter dafuer vorgesehenen Endpunkt pruefen.
4. Probe-Ergebnisse als `yes`, `no` oder `unknown/not_checked` ausgeben. Kein
   optimistisches Boolean-Default.
5. Fehler nach Auth, Lizenz, Rate Limit, Netzwerk und unklar klassifizieren;
   Secrets redigieren.
6. Alle Tests korrigieren, die `list_datasets()` als Entitlement simulieren.

**Abnahme**

- Ein Katalogeintrag ohne Historical Access wird nicht als accessible
  gemeldet.
- Ein Historical Range beweist nicht Live Access.
- Ein nicht ausgefuehrter Live-Probe erscheint als `unknown`, nicht als `true`.
- Bestehende Offline-/Degraded-Tests bleiben fail-closed.

```bash
.venv/bin/python -m pytest \
  tests/test_databento_provider.py \
  tests/test_databento_boundary.py \
  tests/test_databento_decomposition.py \
  tests/test_databento_preopen_fast.py -q
.venv/bin/python -m ruff check databento_provider.py databento_client.py \
  databento_utils.py scripts/probe_providers.py \
  scripts/probe_databento_entitlement.py scripts/databento_preopen_fast.py
git diff --check
```

**Zeitbedarf:** 1 bis 2 Tage.

---

### DBO-120: Rollenbasierte Dataset Policy und fail-closed Auswahl

**Ziel**

`PREFERRED_DATABENTO_DATASETS` und `choose_default_dataset()` werden aus
produktiven Pfaden entfernt. Dataset-Auswahl erfolgt anhand einer benoetigten
Rolle und eines expliziten Vertrags.

**Vorgeschlagene neue Datei**

`databento_dataset_policy.py`

Sie soll mindestens enthalten:

- Role Enum oder stabile String-Konstanten;
- Default-Dataset pro Rolle;
- erlaubte Schemas;
- erwartete Marktabdeckung (`consolidated`, `single_venue`, `options`);
- erlaubter Modus (`live`, `historical`, `both`);
- optionale, semantikgleiche Degradation;
- Validierung von Overrides.

**Arbeiten**

1. Alle Aufrufer von `choose_default_dataset()` inventarisieren.
2. Jeden produktiven Aufrufer einer Rolle zuordnen.
3. Ein explizites Override wie `DATABENTO_DATASET` nur akzeptieren, wenn es
   zur Rolle passt. Ein unpassendes Override muss mit klarer Fehlermeldung
   abbrechen.
4. Workflows auf rollenspezifische Variablen migrieren, zum Beispiel:
   - `DATABENTO_EQUITY_INTRADAY_DATASET=EQUS.MINI`;
   - `DATABENTO_EQUITY_EOD_DATASET=EQUS.SUMMARY`;
   - `DATABENTO_OPTIONS_LIVE_DATASET=OPRA.PILLAR`.
5. Den alten globalen Override waehrend einer kurzen Deprecation-Phase nur
   lesen, wenn die Rolle eindeutig ist; Warning und Abschaltdatum ausgeben.
6. Manifesten Dataset, Rolle, Schema, Coverage und Modus hinzufuegen.

**Verbotene Fallbacks**

- `EQUS.MINI` auf `XNAS.ITCH` oder `XNYS.PILLAR`;
- `EQUS.SUMMARY` auf ein Intraday-Venue-Dataset;
- `OPRA.PILLAR` auf Equity-Daten;
- ein fehlendes Override auf den ersten Katalogeintrag.

**Abnahme**

- Ohne Override waehlt jede Rolle genau das Dataset aus Abschnitt 2.
- Unpassende Overrides schlagen vor dem ersten kostenpflichtigen Datenabruf
  fehl.
- Katalogreihenfolge und Account-Entitlements veraendern die fachliche Quelle
  nicht.
- Unit-Tests decken Gross-/Kleinschreibung, fehlende Config, unpassendes Schema,
  historische-only und live-only Rollen ab.

**Zeitbedarf:** 1,5 bis 2,5 Tage.

---

### DBO-200: `EQUS.SUMMARY` erschliessen und `DBEQ.BASIC` kontrolliert migrieren

**Ziel**

Das bereits bezahlte `EQUS.SUMMARY` wird kanonische Tagesquelle. Es findet
keine blinde Repository-weite String-Ersetzung statt.

**Erste produktive Kandidaten**

- `open_prep/outcome_backfill.py`
- `scripts/credential_health_check.py`
- Tagesbaseline-/Previous-Close-Pfade in den SMC-Generatoren
- Health- und Grafana-Beschreibungen, die noch `DBEQ.BASIC` versprechen

**Arbeiten**

1. Aus DBO-000 alle `DBEQ.BASIC`-Treffer nach Tages-, Intraday-, Test-, Legacy-
   und Archivnutzung aufteilen.
2. Einen kleinen, kostenabgeschaetzten Paritaets-POC fuer mindestens zehn
   Symbole und zehn Handelstage definieren:
   - OHLC;
   - Previous Close;
   - Tagesvolumen;
   - Corporate-Action-/Definition-Auswirkungen;
   - Verfuegbarkeitszeitpunkt.
3. Tagespfade auf `EQUS.SUMMARY` migrieren und Schema explizit auf
   `ohlcv-1d`/benoetigte Statistics begrenzen.
4. Intraday-Pfade nicht auf Summary umstellen. Fuer Live-/Train-Paritaet
   `EQUS.MINI` verwenden, sofern Historienabdeckung und Kosten den Vertrag
   erfuellen.
5. Alte Manifeste und reproduzierbare historische Artefakte nicht
   nachtraeglich umetikettieren. Ihre Provenienz bleibt `DBEQ.BASIC`.
6. Deprecation-Metrik fuer verbleibende Runtime-Nutzung einfuehren.

**Abnahme**

- Neue Outcome-Backfills auf Tagesebene verwenden `EQUS.SUMMARY`.
- Daily Health prueft die neue Quelle und beruecksichtigt deren
  Veroeffentlichungszeitpunkt.
- Kein Intraday-Consumer erhaelt versehentlich Daily-only-Daten.
- Alte Artefakte bleiben reproduzierbar und korrekt beschriftet.
- Eine Restliste dokumentiert begruendete Legacy-Nutzungen und deren
  Abschaltdatum.

**Zeitbedarf:** 2 bis 4 Tage, in zwei PRs aufteilen: Summary-Adapter/Tests und
Consumer-Migration.

---

### DBO-300: ARCA korrigieren und Venue-Daten semantisch trennen

**Ziel**

NYSE Arca wird nicht mehr als AMEX behandelt. Direkte Venue-Daten liefern
separate Merkmale und ueberschreiben keine breite Basiszeitreihe.

**Betroffene Dateien**

- `scripts/databento_preopen_fast.py`
- `scripts/databento_production_export.py`
- Exchange-Normalisierung und Production-Export-Tests

**Arbeiten**

1. `ARCX -> ARCA` normalisieren und `ARCX.PILLAR` separat abbilden.
2. Golden Fixtures fuer Nasdaq, NYSE, NYSE American und NYSE Arca anlegen,
   darunter mindestens ein ETF.
3. Die jetzige timestamp-basierte Source-Priority-Mischung analysieren.
4. Breite Basisbars unveraendert aus der Rollenquelle halten.
5. Venue-Features mit eigener Provenienz ausgeben, beispielsweise
   `nasdaq_*`, `nyse_*`, `american_*`, `arca_*` oder eine klar versionierte
   strukturierte Form.
6. Falls Consumer noch die hybride Reihe erwarten, zunaechst additive Spalten
   einfuehren; alten Pfad im Shadow vergleichen und erst in einem zweiten PR
   entfernen.
7. Manifest um Source Coverage und angewendete Venue-Datasets erweitern.

**Abnahme**

- `ARCX` wird nie als `AMEX` normalisiert.
- Basis-OHLCV bleibt bei zusaetzlichen Venue-Daten bitweise unveraendert.
- Venue-Werte besitzen eindeutige Source-Provenienz.
- Fehlende ARCA-Daten fuehren zu `unknown/not_loaded`, nicht zu AMEX-Fallback.

```bash
.venv/bin/python -m pytest \
  tests/test_databento_preopen_fast.py \
  tests/test_databento_production_export_uplift.py \
  tests/test_databento_production_export_uplift_n.py -q
```

**Zeitbedarf:** 2 bis 3 Tage.

---

### DBO-400: Databento-Usage- und Value-Telemetrie

**Ziel**

Kosten und Nutzen werden pro Dataset und Schema messbar, ohne hohe
Symbolkardinalitaet in Prometheus zu erzeugen.

**Zu erfassende Dimensionen**

- Dataset;
- Schema;
- Modus `live`/`historical`;
- Consumer/Job;
- Request-/Subscribe-Anzahl;
- angeforderte Symbolanzahl;
- Records und Bytes, soweit SDK-seitig messbar;
- Latenz;
- `requested_end - available_end`;
- Cache Hit/Miss;
- Reconnects, Gaps und gedroppte Records;
- erzeugte Kandidaten/Signale;
- tatsaechliche Downstream-Leser;
- Outcome-/Lift-Metrik in separaten Offline-Reports.

Die minimalen OPRA-Metriken aus DBO-500 werden nicht auf DBO-400 verschoben.
DBO-400 uebernimmt sie in einen gemeinsamen, rueckwaertskompatiblen Vertrag und
ergaenzt die Equity-/Historical-Consumer.

**Designregeln**

- Keine einzelnen Symbole als Prometheus-Label.
- Persistente Monats-Snapshots muessen atomar und prozesssicher aktualisiert
  werden.
- Telemetrie ist fail-soft; ein Schreibfehler darf Ingest nicht stoppen.
- `unknown` und Null sind verschieden.
- `provider_usage.json` nur erweitern, wenn Rueckwaertskompatibilitaet sauber
  gewahrt bleibt; andernfalls ein eigenes versioniertes Databento-Artefakt
  anlegen.

**Betroffene Startpunkte**

- `newsstack_fmp/provider_usage.py`
- `services/live_overlay_daemon/feed.py`
- `services/live_overlay_daemon/metrics.py`
- `services/live_overlay_daemon/provider_usage_bridge.py`
- gemeinsamer Historical-Provider in `databento_provider.py`/
  `databento_client.py`

**Abnahme**

- Ein synthetischer Historical-Abruf und ein synthetischer Live-Record werden
  getrennt gezaehlt.
- Cache Hits erzeugen keinen angeblichen externen Request.
- Ein leerer, zu frischer OPRA-Abruf ist als Availability-Lag sichtbar.
- Das Monatsartefakt kann die Kosten-/Nutzenfrage je Subscription beantworten.
- Bestehende FMP-/Benzinga-Telemetrie bleibt unveraendert lesbar.

**Zeitbedarf:** 1,5 bis 2,5 Tage.

---

### DBO-500: OPRA als echten Live-Shadow-Consumer implementieren

**Ziel**

Den historischen Rolling-Poll fuer die letzten 15 Minuten nicht als Live-
Quelle verwenden. Ein zentraler Dienst konsumiert OPRA live, normalisiert
Definitions- und Trade-Kontext einmal und stellt daraus abgeleitete UOA-Daten
lokal fuer bestehende Consumer bereit.

**Vorgeschlagene Struktur**

```text
services/opra_live_daemon/
  config.py
  feed.py
  definitions.py
  state.py
  metrics.py
  main.py
  README.md
```

Die bestehende fachliche Detektion aus `newsstack_fmp/opra_uoa.py` soll
wiederverwendet werden. Keine zweite UOA-Regelwelt im Service aufbauen.

**Feed-Vertrag**

1. Feature Flag beginnt `off`; Shadow ist explizit zu aktivieren.
2. Universum ist eine dynamische Hotlist/Parent-Symbology, nicht ganz OPRA.
3. Im POC `tcbbo` gegen `trades` vergleichen. Das Schema wird erst nach
   nachgewiesener SDK-/Entitlement-Unterstuetzung festgelegt.
4. Instrument Definitions:
   - historischer, UTC-Tages-ausgerichteter Bootstrap fuer den letzten
     vollstaendig verfuegbaren Zeitraum;
   - Live-Definition-Updates abonnieren oder anderweitig aktuell halten;
   - Cache nach `instrument_id` und Session;
   - unbekannte Instrumente nicht raten, sondern zaehlen und zurueckhalten.
5. Rolling Windows im Speicher fuehren; UI und andere Consumer lesen daraus,
   statt Databento selbst abzufragen.
6. Reconnect mit exponentiellem Backoff und Jitter.
7. Historischen Gap-Backfill nur bis zum tatsaechlichen `available_end`
   ausfuehren. Die juengste OPRA-Historical-Luecke als offen markieren und
   spaeter reconciliieren.
8. State-Snapshot atomar lokal persistieren; keine Rohdaten veroefentlichen.
9. Bereits im ersten Shadow-Stand mindestens Feed-Uptime, Reconnects,
   Records, Definition-Coverage, Processing-Latenz, Unknown Instruments und
   erzeugte UOA-Kandidaten lokal messen. Damit darf das Renewal-Messfenster vor
   DBO-400 beginnen.

**Output-Vertrag**

Mindestens:

- underlying und option symbol;
- event timestamp und receive timestamp;
- strike, expiry, call/put;
- price, size, premium/notional;
- aggressor side plus confidence/source;
- NBBO-Kontext, soweit Schema vorhanden;
- cluster/sweep identifiers;
- Definition age;
- data age;
- source dataset/schema;
- Shadow-only status.

**Bestehenden Historical-Wrapper behandeln**

`newsstack_fmp/ingest_opra_options_flow.py` bleibt fuer Historical Research und
Backfill erhalten, darf aber nicht mehr die aktuelle 15-Minuten-Live-Sicht
versprechen. Sein Definitionsfenster muss auf den dokumentierten
session-/UTC-ausgerichteten Vertrag umgestellt und gecacht werden.

**Tests**

- synthetische Live-Messages ohne Netzwerk;
- Definition vor/nach Trade;
- unbekannte `instrument_id`;
- Duplicate/Reconnect;
- Out-of-order Events;
- Sessionwechsel;
- Available-end-Lag;
- Hotlist add/remove;
- kein Signal ausserhalb Shadow;
- korrekte A/B-Aggressor-Semantik.

**Abnahme vor Shadow-Deployment**

```bash
.venv/bin/python -m pytest \
  tests/test_opra_uoa.py \
  tests/test_pull_databento_edge_input.py \
  tests/test_feature_flags.py \
  tests/test_family_abs_uoa_activity_v2.py \
  tests/test_family_signed_uoa_notional_v2.py -q
.venv/bin/python -m ruff check services/opra_live_daemon \
  newsstack_fmp/ingest_opra_options_flow.py newsstack_fmp/opra_uoa.py
git diff --check
```

Zusaetzlich neue Service-Unit- und Contract-Tests ausfuehren. Ein echter
credential-gestuetzter Smoke Test benoetigt eine konkrete Freigabe und darf nur
eine kleine Hotlist nutzen.

**Zeitbedarf:** 3 bis 5 Entwicklungstage.

---

### DBO-505: Streamlit-Optionsansicht entkoppeln und lazy machen

**Ziel**

Ein nicht geoeffneter Options-Tab verursacht keine Databento-Abfragen. Die UI
liest nur den zentralen OPRA-Snapshot.

**Betroffene Datei**

- `open_prep/streamlit_monitor.py`

**Arbeiten**

1. Direkten `_cached_bz_options_op`-Databento-Abruf aus dem Renderpfad
   entfernen.
2. Die vom verwendeten Streamlit-Stand unterstuetzte Lazy-Tab-Variante nutzen
   oder einen expliziten `Load/Refresh`-Button einsetzen.
3. Snapshot-Alter, letzte Aktualisierung, Shadow-Status und Fehler sichtbar
   machen.
4. Bei nicht laufendem Sidecar fail-closed `unavailable` zeigen, nicht
   `Benzinga retired` oder einen leeren erfolgreichen Live-Stand vortaeuschen.
5. UI-Tests mit einem Fake-Snapshot ergaenzen; Test muss beweisen, dass Rendern
   anderer Tabs keinen Providerzugriff ausloest.

**Abnahme**

- Null externe Provideraufrufe beim Rendern ohne geoeffneten Options-Tab.
- Wiederholtes UI-Rerendern aendert keine Provider-Usage.
- Datenalter und `unavailable` sind nutzerfreundlich sichtbar.

**Zeitbedarf:** 0,5 bis 1 Tag.

---

### DBO-510: OPRA-Shadow-Messfenster und Ablation

**Ziel**

Vor der Verlangerung entscheiden, ob OPRA einen eigenstaendigen, zeitnahen und
technisch belastbaren Mehrwert liefert.

**Mindestfenster**

- Ziel: 7 bis 10 vollstaendige US-Handelssitzungen;
- mindestens Open, Midday und Close;
- mindestens ein kontrollierter Reconnect;
- keine produktive Nutzerwirkung.

Wenn der Live-Shadow erst spaet fertig wird, darf das Messfenster nicht durch
optimistische Annahmen ersetzt werden. Dann ist die korrekte Entscheidung,
OPRA nicht auf Hoffnung zu verlaengern und spaeter erneut zu aktivieren.

**Zu messen**

- Feed uptime und reconnect count;
- event/receive/process latency p50/p95/p99;
- Definition coverage und unknown-instrument rate;
- Records, Bytes und aktive Underlyings;
- UOA-Kandidaten pro Stunde und Symbol;
- Dublettenrate;
- Anteil verwertbarer aggressor-signed Events;
- Datenalter im UI-Snapshot;
- inkrementeller Lift gegen Equity-only Baseline;
- Ablation: Premium allein, Aggressor allein, Cluster allein, kompletter
  OPRA-UOA-Vertrag;
- fruehe/spaete Datenhaelfte und Tageszeitslices;
- Konfidenzintervalle statt nur Punktwerte.

**Provisorische technische Gates**

| Metrik | Gate |
| --- | --- |
| Regular-hours Feed-Uptime | >= 99,5 % |
| Process latency | p95 <= 3 s, p99 <= 8 s |
| Definition coverage | >= 99,5 % der verarbeiteten Records |
| Unbeabsichtigte produktive Alerts | 0 |
| UI-Provider-Direktabrufe | 0 |
| Unklassifizierte Gaps | 0 |
| Messbarer inkrementeller Nutzen | positiv oder klar begruendete strategische Evidenz |

Das letzte Gate darf nicht durch reine Signalmenge ersetzt werden. Viele
Optionsereignisse ohne inkrementellen Nutzwert rechtfertigen keine
Subscription.

**Artefakte**

- lokales, nicht veroeffentlichtes Shadow-Ledger;
- `artifacts/monitoring/opra_shadow_summary_<date>.json` ohne Rohdaten/Secrets;
- interner Entscheidungsreport mit Konfidenzintervallen und Slice-Tabelle.

**Zeitbedarf:** 7 bis 10 Handelssitzungen plus 1 Tag Auswertung.

---

### DBO-600: Subscription-Entscheidung vor 2026-08-01

**Entscheidungszeitpunkt**

Spaetestens 2026-07-30 einen vorlaeufigen Entscheid vorbereiten; spaetestens
2026-07-31 die Nutzerentscheidung einholen. Der Agent darf selbst keine
Subscription kuendigen oder veraendern.

**US Equities Standard**

Standardentscheidung: **behalten**, sofern:

- `EQUS.MINI` Live weiterhin gesund laeuft;
- `EQUS.SUMMARY` erreichbar und fachlich integrierbar ist;
- Lizenz-/Nutzungsform fuer den geplanten Consumer-Pfad geklaert bleibt.

**OPRA Standard**

Verlaengerung nur empfehlen, wenn:

- der echte Live-Consumer arbeitet;
- das Shadow-Fenster ausreichend belastbar ist;
- Telemetrie aktive Nutzung belegt;
- es inkrementellen technischen oder gemessenen Signalwert gibt;
- die geplante kommerzielle Nutzung lizenzseitig separat geklaert werden kann.

Andernfalls Empfehlung: **nicht verlaengern**, Historical PAYG fuer Forschung
nutzen und Live erst bei Produktreife erneut aktivieren.

**GLBX.MDP3 und weitere Datasets**

Keine Subscription. Ein spaeterer Historical-PAYG-POC braucht:

- klare Hypothese;
- Kostenlimit;
- Walk-forward-Design;
- Ablation gegen die bestehende Equity-Baseline;
- Entscheidungsgate vor jedem Live-Upgrade.

**Abnahme**

Ein einseitiger Entscheidungsreport enthaelt je Subscription:

- Kosten;
- tatsaechliche Nutzung;
- technische Reife;
- inkrementellen Wert;
- Lizenz-/Distributionsrisiko als offene Prueffrage;
- klare Empfehlung `keep`, `cancel` oder `insufficient evidence`;
- naechsten Entscheidungszeitpunkt.

**Zeitbedarf:** 0,5 bis 1 Tag.

## 6. PR-Schnitt und empfohlene Reihenfolge

| PR | Inhalt | Darf Produktionswirkung haben? |
| --- | --- | --- |
| 1 | DBO-050 TradingView-Dokument-Cleanup und Negativtest | Nein |
| 2 | DBO-100 Aggressor-Semantik und Regressionen | Nach Merge Korrektheitswirkung; historische Artefakte nicht umdeuten |
| 3 | DBO-110 Katalog/Historical/Live-Vertrag | Nein, Probes werden ehrlicher |
| 4 | DBO-500 OPRA-Live-Sidecar samt minimaler Messung | Nur `off`/`shadow` |
| 5 | DBO-505 Streamlit-Snapshot-Consumer | Observe-only |
| 6 | DBO-120 Rollenpolicy und fail-closed Auswahl | Zunaechst shadow/config-only |
| 7 | DBO-200 EQUS.SUMMARY-Adapter und Paritaetstests | Nein |
| 8 | DBO-200 Consumer-Migration plus DBEQ-Deprecation | Gestuft |
| 9 | DBO-300 ARCA-Normalisierung | Ja, aber mit Golden Tests |
| 10 | DBO-300 additive Venue-Provenienz; kein Overwrite | Zunaechst shadow/additiv |
| 11 | DBO-400 gemeinsame Usage-/Value-Telemetrie | Ja, fail-soft und beobachtend |
| 12 | DBO-510 Report und DBO-600 Entscheidung | Keine Codewirkung |

PR 1 ist unabhaengig. PRs 2 und 3 sind die fachlichen Voraussetzungen fuer den
OPRA-Shadow in PR 4. Nach dessen Start sammelt der Dienst unbeaufsichtigt lokale
Evidenz, waehrend PRs 6 bis 11 die breitere Dataset-Architektur umsetzen. Jeder
PR ist gegen den dann aktuellen `origin/main` und offene PR-Ueberschneidungen zu
verifizieren.

## 7. Gesamttest-Gates

Nach jedem PR:

```bash
git diff --check
.venv/bin/python -m ruff check <geaenderte-python-pfade>
.venv/bin/python -m pytest <zielgerichtete-tests> -q
```

Vor einer Rollen-, Workflow- oder Deployment-Promotion zusaetzlich:

```bash
.venv/bin/python -m pytest \
  tests/test_databento_boundary.py \
  tests/test_databento_decomposition.py \
  tests/test_databento_provider.py \
  tests/test_databento_preopen_fast.py \
  tests/test_databento_production_export_uplift.py \
  tests/test_smc_trades_microstructure.py \
  tests/test_smc_flow_qualifier.py \
  tests/test_opra_uoa.py \
  tests/test_pull_databento_edge_input.py -q
```

Ausserdem alle repo-spezifischen Line-pin-, Workflow- und Ledger-Guards
ausfuehren, die `skipp-pr-flow` fuer die tatsaechlich geaenderten Dateien
vorschreibt.

## 8. Stop-/Rollback-Kriterien

Sofort stoppen und nicht promoten, wenn:

- ein Dataset-Override die Marktabdeckung unbemerkt veraendert;
- `EQUS.SUMMARY` und alte Daily-Daten ohne erklaerten Corporate-Action- oder
  Verfuegbarkeitsgrund materiell divergieren;
- OPRA-Live-Definitionscoverage unter 99,5 % liegt;
- Live-Gaps als erfolgreiche leere Fenster erscheinen;
- Telemetrie Keys, Symbole als hochkardinale Labels oder Rohdaten exponiert;
- ein Shadow-Feature bestehende Alerts oder Nutzeranzeigen beeinflusst;
- ein Production Export keine eindeutige Dataset-/Schema-/Coverage-Provenienz
  besitzt;
- Kosten vor einer grossen Historical-Abfrage nicht abgeschaetzt werden
  koennen;
- Lizenz- oder Distributionsannahmen als geklaert dargestellt werden, obwohl
  sie nicht konkret bestaetigt sind.

Rollback erfolgt pro PR. Rollenpolicy, neue Consumer und OPRA-Sidecar muessen
ueber Flags deaktivierbar sein. Last-Good-Artefakte bleiben erhalten; ein
Rollback darf nicht durch Neuetikettierung alter Daten simuliert werden.

## 9. Realistische Timeline

Die technische Arbeit umfasst etwa 12 bis 20 Agententage. Teile koennen als
getrennte PRs nacheinander landen; es soll keine nutzersichtbare
Zwischenloesung geben. POCs und Shadow-Betrieb sind ausdruecklich erlaubt.

| Zeitraum | Ziel |
| --- | --- |
| 2026-07-18 | DBO-000; DBO-100 offline implementieren und testen; DBO-050 vorbereiten |
| 2026-07-19 | DBO-110 und OPRA-Servicegeruest; synthetische Feed-/Reconnect-/Definition-Tests |
| 2026-07-20 | nach konkreter Freigabe kleiner Live-Smoke-Test; OPRA Shadow starten, falls Gates gruen |
| 2026-07-20 bis 2026-07-30 | bis zu neun Handelssitzungen DBO-510 messen; Dienst unbeaufsichtigt beobachten |
| waehrend des Shadow-Fensters | DBO-505, DBO-120, DBO-200, DBO-300 und DBO-400 umsetzen |
| bis 2026-07-30/31 | DBO-600 Subscription-Empfehlung |
| danach | kontrollierte Summary-/Rollen-Promotion, sofern Gates gruen sind |

Der Termin 2026-08-01 ist selbst bei diesem aggressiven POC-/Shadow-Zeitplan
eng. Der 20. Juli ist ein Ziel, kein Grund, Correctness- oder Safety-Gates zu
umgehen. Wenn der Sidecar nicht spaetestens am 22. Juli stabil im Shadow laeuft
oder das Fenster weniger als sieben vollstaendige Sitzungen umfasst, ist
`insufficient evidence` das ehrliche Ergebnis. In diesem Fall soll die
OPRA-Empfehlung nicht auf zukuenftig erwarteten Code gestuetzt werden.

## 10. Abschlussbericht des ausfuehrenden Agenten

Der Agent soll nach jedem Arbeitspaket knapp festhalten:

- verifizierter `origin/main`-Commit;
- PR/Branch oder lokaler Commit;
- geaenderte Dataset-Semantik;
- Tests und Ergebnisse;
- offene Risiken;
- Rollout-Status `off`, `shadow`, `observe` oder `promoted`;
- naechstes unblocked Arbeitspaket.

Der finale Programmbericht muss die zehn Endzustandskriterien aus Abschnitt 1
einzeln als `erfuellt`, `nicht erfuellt` oder `bewusst verschoben` bewerten.
Ein erfolgreicher Code-Merge allein schliesst das Programm nicht: OPRA-Nutzen,
Subscription-Entscheidung und eindeutige Datenprovenienz sind eigenstaendige
Abnahmekriterien.

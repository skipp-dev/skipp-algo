# SMC Deep Review 2026-04-20: Engineering Backlog

Stand: 2026-04-20
Status: aktiv
Quelle: `docs/smc_deep_review_2026-04-20_improvement_plan.md`

## Zweck

Dieses Dokument uebersetzt den uebergreifenden Improvement Plan in konkrete,
ticketfaehige Engineering-Arbeitspakete ohne Kalenderbindung.

Jedes Ticket beschreibt:

- den fachlichen Zweck,
- den technischen Scope,
- primaere Repo-Anker,
- Abhaengigkeiten,
- und eine klare Definition of Done.

## Delivery Rules

1. Keine neue Schattenlogik zwischen Engine, Dashboard und generierten
   Profilen.
2. Keine neue Pine-zu-Python-Live-Runtime als Vorbedingung.
3. Freshness und Trust gelten als Produktsignale.
4. Operator-only-Grenzen bleiben explizit markiert.
5. Jede sichtbare Kennzahl braucht eine Nutzerfunktion.
6. Release- und Validation-Gates sind Teil des Deliverables.

## Ticket-Format

Die Ticket-IDs folgen dem Schema `ENG-WSx-yy`.

## WS1 - Pine Evidence Lane

### ENG-WS1-01 - Kanonischen Szenario-Katalog definieren

- Ziel: die wichtigsten Pine-Entscheidungsfaelle als formale Soll-Szenarien
  festlegen.
- Scope: BOS, CHoCH, OB-Reclaim, FVG-Fill, Sweep-Reclaim, HTF-aligned,
  stale-context, degraded-trust, watch-only, no-trade.
- Primaere Dateien: `scripts/run_smc_release_gates.py`,
  `scripts/run_smc_post_release_validation.py`, `SMC_Dashboard.pine`.
- Abhaengigkeiten: keine.
- Definition of Done:
  - kanonische Liste produktrelevanter Szenarien existiert,
  - pro Szenario sind Input, erwarteter Zustand und erwartete Aktion
    beschrieben,
  - Szenarien sind als Gate-Eingang wiederverwendbar.

### ENG-WS1-02 - Deterministische Evidence-Artefakte erzeugen

- Ziel: aus definierten Szenarien generatorseitig reproduzierbare Soll-Artefakte
  ableiten.
- Scope: Fixture-Daten, Soll-Ausgaben, referenzierbare Artefakte fuer
  Release-Gates und Validation.
- Primaere Dateien: `scripts/generate_smc_micro_base_from_databento.py`,
  `scripts/smc_microstructure_base_runtime.py`,
  `scripts/generate_smc_micro_profiles.py`.
- Abhaengigkeiten: `ENG-WS1-01`.
- Definition of Done:
  - jedes Kernszenario hat ein reproduzierbares Soll-Artefakt,
  - Artefakte sind generatorseitig deterministisch,
  - Artefakte koennen in CI gelesen und verglichen werden.

### ENG-WS1-03 - Evidence-Pruefung in Release-Gates einhaengen

- Ziel: zentrale Entscheidungsdrifts blockieren Releases.
- Scope: Release-Gates um Evidence-Vergleiche ergaenzen.
- Primaere Dateien: `scripts/run_smc_release_gates.py`,
  `.github/workflows/smc-release-gates.yml`.
- Abhaengigkeiten: `ENG-WS1-02`.
- Definition of Done:
  - Release-Gates vergleichen Kernszenarien gegen Soll-Artefakte,
  - semantische Drifts blockieren den Gate-Lauf,
  - Fehlerausgaben benennen das betroffene Szenario nachvollziehbar.

### ENG-WS1-04 - TradingView-Preflight auf reale Runtime-Pfade normalisieren

- Ziel: compile, add-to-chart und runtime validieren, ohne an instabilen
  Input-Tab-Annahmen zu haengen.
- Scope: Preflight- und Post-Release-Validation vereinheitlichen.
- Primaere Dateien: `scripts/run_smc_post_release_validation.py`,
  `.github/workflows/smc-release-gates.yml`.
- Abhaengigkeiten: `ENG-WS1-01`.
- Definition of Done:
  - TV-Validierung prueft compile, add und runtime,
  - sichtbare Input-Tabs sind keine harte Vorbedingung mehr,
  - Flake-resistente Fehlerbilder sind sauber klassifiziert.

## WS2 - Trust And Freshness UX

### ENG-WS2-01 - Einheitliches Trust-State-Modell definieren

- Ziel: Provider- und Artefaktzustand auf wenige stabile Produktzustaende
  abbilden.
- Scope: healthy, degraded, stale, unavailable, watch-only.
- Primaere Dateien: `smc_integration/provider_health.py`,
  `smc_tv_bridge/provider_status.py`.
- Abhaengigkeiten: keine.
- Definition of Done:
  - ein kanonisches Zustandsmodell ist im Code und in der Doku verankert,
  - Provider- und Artefaktlagen mappen deterministisch auf Produktzustaende,
  - Health-Ausgaben benennen Ursache und Auswirkung getrennt.

### ENG-WS2-02 - Trust/Freshness in den Export-Pfad ziehen

- Ziel: die Zustandslage bis in den Pine-Consumer tragen.
- Scope: generierte Profile und Library-Exports um Trust/Freshness-Felder
  erweitern.
- Primaere Dateien: `scripts/generate_smc_micro_profiles.py`,
  `scripts/generate_smc_micro_base_from_databento.py`.
- Abhaengigkeiten: `ENG-WS2-01`.
- Definition of Done:
  - Pine-seitig stehen explizite Zustandsfelder zur Verfuegung,
  - Degradierungsgruende sind fuer die Surface lesbar,
  - keine doppelte Berechnung derselben Zustandslage im Dashboard.

### ENG-WS2-03 - Trust/Freshness-Badges im Dashboard produktisieren

- Ziel: Frische und Vertrauen direkt in der sichtbaren Decision-Lage zeigen.
- Scope: kompakte UI-Elemente fuer Status, Datenalter und Degradierungsgrund.
- Primaere Dateien: `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`.
- Abhaengigkeiten: `ENG-WS2-02`.
- Definition of Done:
  - Default-Surface zeigt den Trust-State ohne Audit-Modus,
  - stale/degraded ist auf einen Blick erkennbar,
  - mobile Variante folgt derselben Semantik.

### ENG-WS2-04 - Handlung aus Trust und Freshness degradieren

- Ziel: eingeschraenkte Datenlage soll die Produkthandlung beeinflussen.
- Scope: Action-State ueber Trust/Freshness degradieren.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `scripts/generate_smc_micro_base_from_databento.py`,
  `smc_integration/provider_health.py`.
- Abhaengigkeiten: `ENG-WS2-03`.
- Definition of Done:
  - stale oder degraded fuehrt deterministisch zu Watchlist, selektiv oder
    no-trade,
  - die UI erklaert, warum die Aktion degradiert wurde,
  - Release- und Validation-Artefakte reflektieren dieselbe Logik.

## WS3 - Hero Surface

### ENG-WS3-01 - Hero-Informationsarchitektur fixieren

- Ziel: Standardoberflaeche auf Marktmodus, Setup-Qualitaet und Handlung
  reduzieren.
- Scope: lesbare Informationshierarchie fuer Default, Compact, Pro.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`.
- Abhaengigkeiten: `ENG-WS2-01`.
- Definition of Done:
  - jede sichtbare Zeile ist einer der drei Ebenen zugeordnet,
  - hero-first Lesestufe ist explizit dokumentiert,
  - keine konkurrierenden Primaerbotschaften in derselben Ansicht.

### ENG-WS3-02 - Default-Surface auf Compact Detail reduzieren

- Ziel: Diagnose-First-Eindruck der Default-Ansicht abbauen.
- Scope: sichtbare Kernzeilen reduzieren, operator-only Begriffe ausblenden.
- Primaere Dateien: `SMC_Dashboard.pine`, `pine_input_surface.py`.
- Abhaengigkeiten: `ENG-WS3-01`.
- Definition of Done:
  - Default-Ansicht hat einen klar begrenzten Visual Budget,
  - BUS- und Operator-Terminologie ist nicht Teil der ersten Lesestufe,
  - Pro-Diagnostics bleiben gesondert verfuegbar.

### ENG-WS3-03 - Marktmodus-Hero bauen

- Ziel: Regime, Bias, Session, Trust und Freshness als zusammenhaengender Kopf
  lesbar machen.
- Scope: Hero-Block fuer Marktmodus.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `scripts/generate_smc_micro_profiles.py`.
- Abhaengigkeiten: `ENG-WS2-03`, `ENG-WS3-01`.
- Definition of Done:
  - Marktmodus ist in einem Blick lesbar,
  - Trust/Freshness ist in denselben Kopfblock integriert,
  - keine zweite konkurrierende Modusdarstellung bleibt aktiv.

### ENG-WS3-04 - Setup-Qualitaetskarte mit Begruendung bauen

- Ziel: Prioritaet, Konfluenz und Familien-Health als begruendete Qualitaetslage
  zeigen.
- Scope: Quality-Block mit Why now und Main risk.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `scripts/generate_smc_micro_profiles.py`, `smc_core/scoring.py`.
- Abhaengigkeiten: `ENG-WS3-03`.
- Definition of Done:
  - Setup-Qualitaet ist nicht nur ein Rohwert,
  - Why now und Main risk sind sichtbar,
  - die gleiche Logik ist in Default und Audit konsistent.

### ENG-WS3-05 - Handlungsempfehlung als primaere Ausgabe modellieren

- Ziel: das Produkt soll explizit sagen handeln, warten, beobachten oder
  vermeiden.
- Scope: Action-State plus klare Aktionssprache.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `scripts/generate_smc_micro_base_from_databento.py`.
- Abhaengigkeiten: `ENG-WS2-04`, `ENG-WS3-04`.
- Definition of Done:
  - pro Zustand existiert genau eine primaere Handlung,
  - Action-State ist fuer Nutzer lesbar statt nur intern codiert,
  - Main risk und Hauptblocker widersprechen der Aktion nicht.

## WS4 - Scorer Tuning Activation

### ENG-WS4-01 - Outcome-Backfill automatisieren

- Ziel: gelabelte Outcomes nicht mehr manuell wachsen lassen.
- Scope: Backfill in Workflow oder Cron ueberfuehren.
- Primaere Dateien: `open_prep/outcome_backfill.py`,
  `open_prep/run_open_prep.py`, passende Workflow-Dateien.
- Abhaengigkeiten: keine.
- Definition of Done:
  - Backfill ist regelmaessig ausfuehrbar,
  - Ergebnisse sind persistiert und nachvollziehbar,
  - Fehlfaelle sind sichtbar und nicht still.

### ENG-WS4-02 - Feature-Importance-Artefakte laufend erzeugen

- Ziel: aus gelabelten Outcomes dauerhaft auswertbare FI-Daten erzeugen.
- Scope: FI-Samples und Reports direkt an Backfill anbinden.
- Primaere Dateien: `open_prep/outcomes.py`, `open_prep/outcome_backfill.py`.
- Abhaengigkeiten: `ENG-WS4-01`.
- Definition of Done:
  - FI-Sample-Dateien wachsen reproduzierbar,
  - FI-Reports koennen ab Mindestmenge automatisch erzeugt werden,
  - fehlende Labelmenge wird als Zustand statt als stiller Leerlauf behandelt.

### ENG-WS4-03 - Candidate Weight Sets plus Drift-Gate produktisieren

- Ziel: Candidate Weights aus FI erzeugen und gegen Drift absichern.
- Scope: Candidate Weight Set schreiben, Drift pruefen, Artefakt ablegen.
- Primaere Dateien: `open_prep/outcomes.py`, `open_prep/scorer.py`.
- Abhaengigkeiten: `ENG-WS4-02`.
- Definition of Done:
  - Candidate Weight Set kann automatisch erzeugt werden,
  - Drift-Gate blockiert extreme Spruenge,
  - Candidate und Default sind sauber unterscheidbar versioniert.

### ENG-WS4-04 - OV7-Vergleich static vs auto_tuned operationalisieren

- Ziel: nicht nur Infrastruktur besitzen, sondern echten Vergleich fahren.
- Scope: Control = default, Treatment = auto_tuned, Promotion-Report.
- Primaere Dateien: `scripts/smc_ab_experiment.py`,
  `scripts/run_ab_comparison.py`, `open_prep/scorer.py`.
- Abhaengigkeiten: `ENG-WS4-03`.
- Definition of Done:
  - Experimente koennen deterministisch pro Symbol arm-weise laufen,
  - Comparison-Output enthaelt Promote/Hold/Rollback-Empfehlung,
  - die Entscheidung ist an klare KPI-Schwellen gebunden.

## WS5 - Release And Refresh Hardening

### ENG-WS5-01 - Manifest-basierte Artefaktaufloesung haerten

- Ziel: produktive Discovery gegen lokale oder stale Schattenartefakte
  absichern.
- Scope: Manifest-bevorzugte Aufloesung in Health und Validation.
- Primaere Dateien: `smc_integration/provider_health.py`,
  `smc_integration/structure_audit.py`,
  `scripts/run_smc_pre_release_artifact_refresh.py`.
- Abhaengigkeiten: keine.
- Definition of Done:
  - produktive Pfade bevorzugen manifest-backed Artefakte,
  - lokale Scratch-Artefakte koennen die produktive Sicht nicht mehr
    unbemerkt ueberlagern,
  - Fehlermeldungen erklaeren die gewaehlte Quelle nachvollziehbar.

### ENG-WS5-02 - Stale-batch-Schutz in Refresh und Release einziehen

- Ziel: stale-by-design Batch-Lagen frueh blockieren.
- Scope: Altersgrenzen, Statusflags und Freshness-Pruefungen in Refresh und
  Release.
- Primaere Dateien: `.github/workflows/smc-library-refresh.yml`,
  `.github/workflows/smc-release-gates.yml`,
  `scripts/run_smc_pre_release_artifact_refresh.py`.
- Abhaengigkeiten: `ENG-WS5-01`.
- Definition of Done:
  - stale Batch-Lagen werden explizit erkannt,
  - produktive Laeufe schlagen bei veralteter Datenlage sauber fehl,
  - Refresh-Berichte zeigen Ursache und Reichweite des Problems.

### ENG-WS5-03 - TradingView-Retry- und Reinsert-Pfade idempotent machen

- Ziel: TV-UI-Flakes sollen bekannte, saubere Recovery-Pfade haben.
- Scope: Retry, Reinsert, Recovery und Wiederholbarkeit der Validation.
- Primaere Dateien: `scripts/run_smc_post_release_validation.py`,
  `.github/workflows/smc-library-refresh.yml`,
  `.github/workflows/smc-release-gates.yml`.
- Abhaengigkeiten: `ENG-WS1-04`.
- Definition of Done:
  - bekannte TV-Flakes fuehren nicht zu nondeterministischem Verhalten,
  - Recovery-Pfade sind idempotent,
  - Validation bleibt lesbar und diagnosetauglich.

### ENG-WS5-04 - Post-Release-Validation auf Nutzerpfade fokussieren

- Ziel: nach Release das sichtbare Produkt verifizieren, nicht nur den Build.
- Scope: Hero-State, Action-State und Trust-State pruefen.
- Primaere Dateien: `scripts/run_smc_post_release_validation.py`,
  `SMC_Dashboard.pine`.
- Abhaengigkeiten: `ENG-WS3-05`, `ENG-WS5-03`.
- Definition of Done:
  - Validation berichtet ueber sichtbare Produktzustandspaare,
  - Nutzerkritische Pfade sind nach Release explizit abgesichert,
  - Fehlerbilder referenzieren Produktfunktionen statt nur technische Schritte.

## WS6 - Product Consolidation

### ENG-WS6-01 - Unterstuetzte Produktflaechen explizit definieren

- Ziel: klar sagen, welche Surfaces produktiv, operator-only, experimentell
  oder historisch sind.
- Scope: Surface-Matrix und Zustandsklassifikation.
- Primaere Dateien: `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`,
  relevante Produktdokumente.
- Abhaengigkeiten: `ENG-WS3-01`.
- Definition of Done:
  - Surface-Matrix ist dokumentiert,
  - produktive Default-Pfade sind eindeutig,
  - historische Varianten sind nicht mehr implizit gleichrangig.

### ENG-WS6-02 - Input-Oberflaeche auf Produktbedarf reduzieren

- Ziel: sichtbare Inputs auf echte Produktentscheidungen reduzieren.
- Scope: Gruppen, Display-Sichtbarkeit, Operator-only-Trennung.
- Primaere Dateien: `pine_input_surface.py`, `SMC_Dashboard.pine`,
  `SMC_Mobile_Dashboard.pine`.
- Abhaengigkeiten: `ENG-WS6-01`.
- Definition of Done:
  - Standardnutzer sehen nur produktrelevante Inputs,
  - Operator-Inputs bleiben verfuegbar, aber sauber isoliert,
  - sichtbare Input-Flaeche ist deutlich kleiner als heute.

### ENG-WS6-03 - Gemeinsame Produktsprache fuer Surface und Release etablieren

- Ziel: dasselbe Produktversprechen in UI, Doku und Validation sprechen.
- Scope: Action, Quality, Trust, Risk und Main blocker sprachlich angleichen.
- Primaere Dateien: `SMC_Dashboard.pine`,
  `scripts/run_smc_release_gates.py`,
  `scripts/run_smc_post_release_validation.py`, relevante Doku.
- Abhaengigkeiten: `ENG-WS3-05`.
- Definition of Done:
  - dieselben Kernbegriffe werden konsistent verwendet,
  - Default-Surface und Release-Berichte sprechen dieselbe Produktsprache,
  - interne Terminologie tritt in der Nutzerlage zurueck.

### ENG-WS6-04 - Legacy- und Experimental-Flaechen klassifizieren

- Ziel: alte oder experimentelle Varianten sichtbar von produktiven Flaechen
  trennen.
- Scope: Markierung, Doku, spaetere Cleanup-Vorbereitung.
- Primaere Dateien: relevante Pine-Dateien, `pine_input_surface.py`, Doku.
- Abhaengigkeiten: `ENG-WS6-01`.
- Definition of Done:
  - Legacy- und Experimental-Dateien sind explizit markiert,
  - die Produktidentitaet wird dadurch nicht mehr verwaessert,
  - spaetere Cleanup-Schritte koennen gezielt statt breit erfolgen.

## Abschlusskriterium fuer den Backlog

Der Backlog ist inhaltlich abgearbeitet, wenn:

- WS1 bis WS5 produktiv wirksame Ergebnisse liefern,
- WS6 die daraus entstandene Produktgrenze sauber konsolidiert,
- und die sichtbare Default-Surface als belastbare Decision-First-Lage statt
  als Diagnose-Cockpit wahrgenommen wird.
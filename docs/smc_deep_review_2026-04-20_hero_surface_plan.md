# SMC Deep Review 2026-04-20: Hero Surface Plan

Stand: 2026-04-20
Status: aktiv
Fokus: Pine- und Dashboard-Umsetzung fuer die Decision-First-Hero-Surface

## Zweck

Dieses Dokument beschreibt den konkreten Umsetzungsrahmen fuer die Hero
Surface, die aus dem Deep Review als zentrale Produktchance abgeleitet wurde.

Es ist kein Ersatz fuer das bestehende Decision-First-PRD. Es ist die
fokussierte Umsetzungsableitung fuer die aktuelle Repo-Lage und verbindet den
externen Deep Review mit den bereits vorhandenen Decision-First-Dokumenten.

## Verknuepfte Dokumente

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc_deep_review_2026-04-20_improvement_plan.md`
- `docs/smc_deep_review_2026-04-20_hero_surface_implementation_preparation.md`
- `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`

## Problem Statement

Die aktuelle SMC-Surface besitzt technische Tiefe, aber ihr Mehrwert wird im
ersten Blick noch zu schwach kommuniziert.

Die Default-Lage zeigt noch zu oft:

- interne statt entscheidungsorientierter Sprache,
- zu viele gleich laute Informationen,
- zu wenig klare Hierarchie zwischen Modus, Qualitaet und Handlung,
- und zu wenig explizite Sichtbarkeit von Trust und Freshness.

## Produktziel der Hero Surface

Die Hero Surface soll in wenigen Sekunden beantworten:

1. In welchem Marktmodus befinde ich mich?
2. Wie gut ist das aktuelle Setup?
3. Wie vertrauenswuerdig ist die Daten- und Kontextlage?
4. Was soll ich jetzt tun?
5. Warum jetzt und was ist der Hauptblocker?

## Nicht im Scope

- neue Signal-Engine-Familien,
- neue Datenprovider,
- eine parallele zweite Pine-Engine,
- ein Pine-zu-Python-Live-Runtime-Rewrite,
- ein genereller Totalumbau des Audit- oder Operator-Pfads.

## Designprinzipien

1. Decision-first vor Diagnose-first.
2. Dieselbe Produktlogik fuer Desktop und Mobile, nur andere Dichte.
3. Keine Hero-Zeile ohne Entscheidungsfunktion.
4. Unsicherheit wird explizit gezeigt, nicht versteckt.
5. Visual-only Toggles bleiben visuell; sie duerfen keine Engine-Semantik
   still umschalten.
6. Dashboard-Zusammenbau bleibt top-level und nicht als monolithischer UDF-
   Wrapper organisiert.
7. Keine Schattenlogik fuer Regime, Qualitaet oder Aktion im Dashboard.

## Informationsarchitektur

Die Hero Surface hat drei primaere Ebenen.

### Ebene 1 - Marktmodus

Zweck:

- Regime,
- Bias,
- Session,
- Trust,
- Freshness.

Der Nutzer soll sofort wissen, ob das Umfeld offensiv, selektiv oder defensiv
 gelesen werden muss.

### Ebene 2 - Setup-Qualitaet

Zweck:

- Strukturqualitaet,
- Konfluenz,
- HTF-Ausrichtung,
- Familien-Health,
- Kalibrierungsqualitaet,
- Why now.

Der Nutzer soll verstehen, warum dieses Setup staerker oder schwaecher als der
 Durchschnitt ist.

### Ebene 3 - Handlung

Zweck:

- aggressiv,
- selektiv,
- beobachten,
- nicht handeln.

Die Hero Surface soll nicht nur Status liefern, sondern eine explizite
 Handlungslesart.

## Empfohlene Hero-Struktur

### Block A - Market Mode Header

Inhalte:

- Regime
- Bias
- Session
- Trust-State
- Freshness-State

Leseregel:

- muss mit einem Blick erfassbar sein,
- darf keine operator-only Begriffe enthalten,
- Trust und Freshness gehoeren in denselben Kopfblock.

### Block B - Setup Quality Card

Inhalte:

- Primary setup quality
- Why now
- Main risk
- HTF-Ausrichtung
- Family / context health

Leseregel:

- Qualitaet ist nicht nur Score, sondern begruendeter Zustand,
- Why now und Main risk sind Pflichtbestandteile,
- rohe Audit-Metriken gehoeren nicht in die erste Lesestufe.

### Block C - Action Card

Inhalte:

- Hauptaktion
- Degradierungsgrund falls nicht offensiv
- optionaler Risk-Plan nur wenn wirklich relevant

Leseregel:

- genau eine primaere Aktion,
- keine konkurrierenden Signale,
- Risk-Plan nur bei `READY`, `ENTER` oder aktivem Trade-Kontext.

## Hero-first Lesestufe (ENG-WS3-01)

Die sichtbare Surface kennt genau drei Lesestufen, in fester Reihenfolge:

1. **Hero** - Marktmodus, Setup-Qualitaet, Handlung. Drei Zeilen, drei
   Botschaften, keine konkurrierende Primaerinformation. Pinned in
   `scripts/smc_hero_information_architecture.HERO_PRIMARY_LINES`.
2. **Compact** - Trust+Daten, Session/Markt, Event-Risk, Pressure,
   Risk-Plan, Why-now, Struktur, Main-Blocker. Lesbar nach Hero, niemals
   davor.
3. **Pro** - Audit-Tabelle, BUS-Diagnostics, Calibration-Confidence,
   Family-Performance, FVG-Health, Library-Diagnostics. Nur in der
   Audit-View sichtbar.

Jede sichtbare Zeile ist genau einer Stufe zugeordnet
(`scripts/smc_hero_information_architecture.HERO_ROW_CATALOG`); doppelte
Zuordnung ist ein Architekturfehler. Die View-Modi der Pine-Surface
(`Focus`, `Hero`, `Decision Brief`, `Explain`, `Audit View`, `Mobile`)
mappen deterministisch auf erlaubte Lesestufen
(`VIEW_MODE_LEVELS`); kein View darf Zeilen einer Stufe rendern, die er
nicht deklariert hat.

## State Model fuer die Hero Surface

| Bereich | Empfohlene Zustandsklasse |
| --- | --- |
| Market Mode | bullish, neutral, risk-off, degraded |
| Trust | healthy, warmup, degraded, stale, unavailable |
| Setup Quality | high, medium, low, blocked |
| Action | act, selective, watch, avoid |

Diese Klassen muessen generator- und surface-seitig dieselbe Bedeutung haben.

## Sichtbare Pflichtsignale der Hero Surface

Die erste Lesestufe soll nur diese Signale sichtbar machen:

- Market mode
- Primary bias
- Trust/freshness
- Setup quality
- Why now
- Main risk
- Action

Alles andere bleibt second-level Detail oder Pro Diagnostics.

## Technische Grenzen

### Keine monolithische Dashboard-Renderfunktion

Der Dashboard-Zusammenbau soll im top-level Renderpfad bleiben.
Kleine pure Helfer sind ok, aber kein grosser Render-UDF, der den kompletten
 Runtime-Zustand schliesst.

### Keine semantischen UI-Toggles

Inputs mit `Show ...` bleiben visuell.
Sie duerfen die zugrunde liegende Engine, Alerts oder Event-Semantik nicht
 still deaktivieren.

### Keine doppelte Zustandsberechnung

Regime, Trust, Freshness, Action und Quality sollen generator- oder
 engine-seitig entstehen und im Dashboard angezeigt werden.
Das Dashboard darf sie nicht fachlich neu erfinden.

## Repo-Anker fuer die Umsetzung

- `SMC_Dashboard.pine`
- `SMC_Mobile_Dashboard.pine`
- `scripts/generate_smc_micro_profiles.py`
- `scripts/generate_smc_micro_base_from_databento.py`
- `pine_input_surface.py`
- `smc_integration/provider_health.py`

## Hero-Surface-Ticketset

### HERO-01 - Kanonischen Hero-State-Contract definieren

- Scope: Feldliste und Semantik fuer Market Mode, Trust, Freshness, Quality,
  Why now, Main risk, Action.
- Dateien: `scripts/generate_smc_micro_profiles.py`,
  `scripts/generate_smc_micro_base_from_databento.py`, Doku.
- Done when:
  - Contract ist dokumentiert,
  - Feldherkunft ist klar,
  - Dashboard muss keine Schattenlogik bauen.

### HERO-02 - Market Mode Header in Desktop-Surface umsetzen

- Scope: kompakter Kopfblock fuer Regime, Bias, Session, Trust und Freshness.
- Dateien: `SMC_Dashboard.pine`.
- Done when:
  - Marktmodus ist der erste sichtbare Block,
  - Trust/Freshness sind dort integriert,
  - operator-only Begriffe tauchen nicht auf.

### HERO-03 - Setup Quality Card mit Why now und Main risk umsetzen

- Scope: begruendeter Qualitaetsblock statt Zahlencollage.
- Dateien: `SMC_Dashboard.pine`, `scripts/generate_smc_micro_profiles.py`.
- Done when:
  - Why now und Main risk sind sichtbar,
  - Setup-Qualitaet ist erklaert statt nur gerankt,
  - Familien- oder Kontextschwaechen koennen sichtbar gemacht werden.

### HERO-04 - Action Card mit klarer Produktsprache umsetzen

- Scope: explizite Handlungsausgabe mit Degradierungslogik.
- Dateien: `SMC_Dashboard.pine`,
  `scripts/generate_smc_micro_base_from_databento.py`.
- Done when:
  - genau eine primaere Handlung sichtbar ist,
  - degradierte Aktion einen sichtbaren Grund hat,
  - WAIT/WATCH keine ueberladene Plan-Lage anzeigen.

### HERO-05 - Compact Default und Pro Diagnostics sauber trennen

- Scope: Default-Ansicht kompakt, Pro-Tiefe bewusst opt-in.
- Dateien: `SMC_Dashboard.pine`.
- Done when:
  - Default zeigt nur Hero plus wenige Kernzeilen,
  - Pro Diagnostics bleibt funktional,
  - beide Lesestufen widersprechen sich nicht.

### HERO-06 - Mobile-Hero auf dieselbe Semantik spiegeln

- Scope: mobile Variante der Hero Surface mit identischer Bedeutungslogik.
- Dateien: `SMC_Mobile_Dashboard.pine`.
- Done when:
  - mobile und desktop teilen denselben Hero-State,
  - Unterschiede bestehen nur in Dichte und Layout,
  - keine eigene mobile Produktlogik entsteht.

### HERO-07 - Trust/Freshness-Degradierung in die Action-Lage einhaengen

- Scope: stale/degraded/warmup beeinflussen die Hero-Handlung explizit.
- Dateien: `SMC_Dashboard.pine`, `smc_integration/provider_health.py`.
- Done when:
  - Handlung reagiert sichtbar auf eingeschraenkte Datenlage,
  - degradierte Zustandswechsel sind nachvollziehbar,
  - Audit und Default zeigen dieselbe Logik.

### HERO-08 - Input-Surface fuer Hero-Nutzung reduzieren

- Scope: sichtbare Inputs auf Produktbedarf reduzieren, Operator-Pfade
  separat halten.
- Dateien: `pine_input_surface.py`, `SMC_Dashboard.pine`,
  `SMC_Mobile_Dashboard.pine`.
- Done when:
  - Hero-Surface ist ohne Operator-Komplexitaet konfigurierbar,
  - sichtbare Inputs dienen echten Nutzerentscheidungen,
  - operator-only Felder bleiben versteckt oder klar markiert.

### HERO-09 - Produktsprache vereinheitlichen

- Scope: Entscheidungssprache fuer Action, Quality, Risk, Trust und Blocker.
- Dateien: `SMC_Dashboard.pine`, relevante Doku.
- Done when:
  - Default-Surface spricht in Nutzer- statt Systemsprache,
  - dieselben Begriffe tauchen in Doku und Surface auf,
  - Fachjargon wird auf die Pro-Lage begrenzt.

### HERO-10 - Hero-Surface-Validierung in Release- und Post-Release-Pfad einhaengen

- Scope: die sichtbare Hero-Funktion wird Teil der Validation.
- Dateien: `scripts/run_smc_release_gates.py`,
  `scripts/run_smc_post_release_validation.py`.
- Done when:
  - Hero-relevante Zustandsfaelle werden validiert,
  - Validation prueft sichtbare Produktpfade,
  - UI-Regressionen sind frueh erkennbar.

## Akzeptanzkriterien auf Surface-Ebene

Die Hero Surface ist fachlich erreicht, wenn:

- ein Nutzer in wenigen Sekunden Marktmodus, Qualitaet und Aktion versteht,
- Trust und Freshness nicht mehr im Audit versteckt sind,
- die Action-Lage explizit statt implizit ist,
- Compact Default und Pro Diagnostics klar getrennt sind,
- Mobile dieselbe Semantik in reduzierter Form liefert,
- und keine neue Schattenlogik in Dashboard oder Mobile-Surface entstanden ist.

## Reihenfolge innerhalb des Hero-Plans

1. zuerst Contract und Pflichtsignale,
2. dann Desktop-Hero,
3. danach Action- und Trust-Degradierung,
4. danach Compact-vs-Pro-Trennung,
5. dann Mobile-Spiegelung,
6. zum Schluss Input- und Sprachkonsolidierung plus Validation.

## Abschlusszustand

Der Hero-Surface-Plan ist abgeschlossen, wenn `SMC_Dashboard.pine` und
`SMC_Mobile_Dashboard.pine` nicht mehr primar als Diagnose-Cockpit wirken,
sondern als sichtbare Decision-First-Produktflaeche fuer bessere Entscheidungen
unter Unsicherheit.
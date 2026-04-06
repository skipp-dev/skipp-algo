# SMC / SkippALGO First-Release Ticketset

## Status

Draft

## Zweck

Dieses Dokument schneidet aus PRD, Backlog und Screen Spec das kleinste
wirklich auslieferbare Ticketset fuer das erste Decision-First-Release heraus.

Es ist absichtlich enger als der Gesamt-Backlog. Alles, was keinen klaren
First-Release-Nutzerwert liefert, bleibt draussen.

## Source Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-lite-pro-product-cut.md`

## First-Release Definition

Das First Release ist erreicht, wenn ein normaler Nutzer auf allen drei
Surfaces in wenigen Sekunden lesen kann:

1. was die aktuelle Hauptaktion ist,
2. warum diese Aktion jetzt plausibel ist,
3. welches Hauptrisiko aktiv ist,
4. wie Lite und Pro voneinander getrennt sind.

## Arbeitsannahmen

1. Es wird keine neue Signal-Engine gebaut.
2. Bestehende Logik bleibt funktional intakt; umgebaut wird primaer die
   sichtbare Produktlage.
3. Pro Diagnostics darf bestehen bleiben, muss aber klar aus dem Lite-Default
   herausgedraengt werden.
4. Die erste Release-Welle deckt alle drei Surfaces ab, aber nur den engsten
   sichtbaren UI-Cut.

## Nicht Im First Release

- vollstaendige Pro-Neuordnung aller Diagnosezeilen
- Automatisierung der BUS-Bindung fuer Public-Nutzer
- tiefer Forecast- oder Modellumbau
- zusaetzliche Datenquellen oder neue Target-Familien
- zweite Lite-Logik neben der aktiven Engine

## Priorisierungslogik

`P0` bedeutet release-blockierend.

`P1` bedeutet direkt nachgelagert, aber nicht notwendig fuer den ersten
auslieferbaren UX-Cut.

## Must-Ship Ticket Overview

| ID | Prioritaet | Ticket | Surfaces | Warum es im First Release sein muss |
| --- | --- | --- | --- | --- |
| FR-01 | P0 | Shared Action And Trust Contract | Core, Dashboard, SkippALGO, Docs | Ohne gemeinsame Produktsprache zerfaellt die UX in drei Teilprodukte. |
| FR-02 | P0 | Lite Input Gate | Core, Dashboard, SkippALGO | Ohne Input-Cut bleibt der Produkt-Eindruck laborhaft. |
| FR-03 | P0 | SMC Core Hero Surface Cut | SMC_Core_Engine | Der Core braucht eine echte Lite-Hauptflaeche. |
| FR-04 | P0 | Dashboard Compact Detail Default | SMC_Dashboard | Das Dashboard muss Entscheidung erklaeren statt Diagnose dominieren. |
| FR-05 | P0 | SkippALGO Decision Header | SkippALGO | Der groesste Nutzerkontaktpunkt braucht klare Aktionsfuehrung. |
| FR-06 | P0 | SkippALGO Outlook And Forecast Lite Panels | SkippALGO | Outlook und Forecast sind heute zu modellnah fuer First-Readability. |
| FR-07 | P0 | Label And Alert Parity | Core, SkippALGO | Chart, Header und Alerts duerfen nicht drei Sprachen sprechen. |
| FR-08 | P0 | Release Validation And Documentation | alle drei, Docs | Ohne Visual QA und Guide-Abgleich ist der UX-Cut nicht release-faehig. |

## Hold For R1.1

| ID | Prioritaet | Ticket | Grund fuer spaeter |
| --- | --- | --- | --- |
| FR-09 | P1 | Dashboard Pro Row Regrouping | Wertvoll, aber nicht noetig fuer den ersten Lite-Release-Cut. |
| FR-10 | P1 | Preset Migration Hardening | Wichtig fuer Stabilisierung, aber nicht fuer die erste sichtbare Produktverbesserung. |
| FR-11 | P1 | Operator Binding Workflow Cleanup | Relevant fuer Betrieb, nicht fuer die Nutzerwirkung des First Release. |

## FR-01 - Shared Action And Trust Contract

- Ziel: Ein gemeinsames Action-, Risk- und Trust-Vokabular fuer alle drei
  Surfaces festziehen.
- Scope:
  - `WAIT`, `PREPARE`, `READY`, `ENTER`, `MANAGE`, `REDUCE RISK`, `AVOID`,
    `BLOCKED`
  - `Strong`, `Usable`, `Thin`, `Provisional`
  - gemeinsames `Why now` und `Main risk` Muster
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SkippALGO.pine`
  - Doku
- Code anchor:
  - Core: aktueller Compact-/Alert-Einstieg rund um die Mode- und Alert-Inputs
  - SkippALGO: `confidence`, `lastSig` und Alert-Titel sind bereits vorhanden
- Definition of Done:
  - Alle Lite-Surfaces zeigen exakt einen Product State.
  - Confidence ist in Lite nie nur Zahl.
  - Alerts, Header und Dashboard benutzen dieselbe Begriffswelt.

## FR-02 - Lite Input Gate

- Ziel: Den sichtbaren Standard-Input-Surface pro Skript auf echte
  Produktsteuerung reduzieren.
- Scope:
  - sichtbare Lite-Inputs definieren
  - `Advanced Settings` klar abgrenzen
  - bestehende interne Variablennamen duerfen bleiben; wichtig ist die sichtbare
    Produktflaeche
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SMC_Dashboard.pine`
  - `SkippALGO.pine`
- Code anchor:
  - Core: Input-Cluster ab `User Preset`, `compact_mode`, `show_dashboard`,
    `enable_dynamic_alerts`
  - Dashboard: Inputs fuer BUS-Bindung plus `show_table` / `show_risk_lines`
  - SkippALGO: breite Input-Flaeche von `Configuration` ueber Forecast,
    Risk und Labels
- Definition of Done:
  - Lite zeigt pro Surface maximal 10 direkt sichtbare Standard-Inputs.
  - Experten- und Diagnoseinputs bleiben standardmaessig versteckt.

## FR-03 - SMC Core Hero Surface Cut

- Ziel: Den bestehenden Compact-Mode in eine echte Hero-Surface ueberfuehren.
- Scope:
  - Hero Card mit `Action`, `Bias`, `Quality`, `Why now`, `Main risk`
  - Risk Plan nur ab actionable State
  - Health Badge nicht als zweite Parallelbotschaft behandeln
- Hauptartefakt:
  - `SMC_Core_Engine.pine`
- Code anchor:
  - `compact_mode`
  - `show_dashboard`
  - Mini Health Badge am letzten Balken
  - dynamische Alert-Komposition fuer Lifecycle-Zustaende
- Definition of Done:
  - Core-Lite ist in <= 5 Sekunden lesbar.
  - Risk-Linien erscheinen nur bei reifem Setup oder aktiver Position.
  - Compact-Mode ist nicht mehr nur ein Unterdrueckungsmodus, sondern eine
    klare Produkt-Surface.

## FR-04 - Dashboard Compact Detail Default

- Ziel: Das Dashboard standardmaessig in einen Compact Detail Screen drehen.
- Scope:
  - Default-Tabelle auf kompakte Entscheidungserklaerung reduzieren
  - bestehende Pro-Tiefe erhalten, aber nicht als Default anzeigen
  - Operator-only BUS-Bindung explizit dokumentieren
- Hauptartefakt:
  - `SMC_Dashboard.pine`
- Code anchor:
  - BUS-Bindungsinputs am Dateikopf
  - 58-Zeilen-Tabelle mit Hero- und Diagnostic-Sektionen
- Definition of Done:
  - Default-Detail hat maximal 8 Kernzeilen.
  - Pro bleibt verfuegbar.
  - BUS-Terminologie taucht in der Lite-Default-Surface nicht mehr sichtbar auf.

## FR-05 - SkippALGO Decision Header

- Ziel: Einen echten Decision Header in SkippALGO schaffen.
- Scope:
  - `Action`, `Trade Threshold`, `Position`, `Last Action`, `Why now`,
    `Main risk`
  - Confidence nur noch sekundar
- Hauptartefakt:
  - `SkippALGO.pine`
- Code anchor:
  - `confidence`
  - `lastSig`
  - `pos`
  - bestehende Label- und Alert-Semantik
- Besondere Realitaet:
  - Im aktuellen Stand besitzt SkippALGO keine dedizierte Table/HUD-Surface.
    Dieses Ticket fuehrt die erste echte Decision-HUD ein.
- Definition of Done:
  - Der Header ist ohne Guide lesbar.
  - `Confidence`, `MinTrust`, `Pos`, `LastSig` wirken nicht mehr wie vier
    gleich schwere Debug-Felder.

## FR-06 - SkippALGO Outlook And Forecast Lite Panels

- Ziel: Outlook und Forecast als nutzerlesbare Regime- und Prognosehilfen
  umbauen.
- Scope:
  - Outlook: `TF`, `Bias`, `Strength`, `State note`
  - Forecast: `Stable Forecast`, `Early Forecast`, `Evidence`, `Risk Hint`
  - `Pred(N)` / `Pred(1)` verschwinden aus Lite
- Hauptartefakt:
  - `SkippALGO.pine`
- Code anchor:
  - Forecast arrays und bestehende Forecast-/Evidence-Inputs
  - bestehende Confidence- und Forecast-Gates
- Definition of Done:
  - Outlook ist eine schnelle State-Lesehilfe.
  - Forecast zeigt Nutzen, nicht Modellselbsterklaerung.
  - Geringe Evidenz ist explizit sichtbar.

## FR-07 - Label And Alert Parity

- Ziel: Chart-Labels und Alerts an dieselbe Produktsprache anbinden wie Header
  und Dashboard.
- Scope:
  - Core-Dynamic-Alerts priorisieren
  - SkippALGO-Labeltexte und Alerttitel angleichen
  - Legacy-Signale fuer Kompatibilitaet bewusst behandeln
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SkippALGO.pine`
- Code anchor:
  - Core: Dynamic Alert Gate und Message Builder
  - SkippALGO: PRE-/BUY-/SHORT-/EXIT-/COVER-Labels und Alertconditions
- Definition of Done:
  - Header, Chart und Alerts widersprechen sich nicht.
  - Pro Bar gibt es maximal eine primaere Nutzerbotschaft.
  - Legacy-Alerte werden entweder aliasiert oder klar als Legacy markiert.

## FR-08 - Release Validation And Documentation

- Ziel: Den UX-Cut als release-faehiges Produktpaket absichern.
- Scope:
  - PRD, Screen Spec, Ticketset, Implementierungsvorbereitung
  - Guide-/Copy-Abgleich
  - visuelle Screenshot-QA fuer Lite und Pro
- Hauptartefakte:
  - Doku
  - manuelle Validierung
- Definition of Done:
  - Lite/Pro-Surfaces sind dokumentiert.
  - Die wichtigsten Screenshots und Copy-Regeln sind abgeglichen.
  - Compile- und Behavior-Checks sind Teil des Release-Gates.

## Suggested Delivery Order

1. FR-01 Shared Action And Trust Contract
2. FR-02 Lite Input Gate
3. FR-03 SMC Core Hero Surface Cut
4. FR-04 Dashboard Compact Detail Default
5. FR-05 SkippALGO Decision Header
6. FR-06 SkippALGO Outlook And Forecast Lite Panels
7. FR-07 Label And Alert Parity
8. FR-08 Release Validation And Documentation

## Executive Release Rule

Wenn ein Ticket die Diagnose verbessert, aber nicht die schnellere,
vertrauenswuerdigere Nutzerentscheidung auf einer der drei Default-Surfaces,
dann ist es kein First-Release-Ticket.

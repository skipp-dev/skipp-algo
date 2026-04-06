# SMC / SkippALGO Decision-First UX Implementation Backlog

## Status

Draft

## Zweck

Dieses Dokument uebersetzt das Decision-First-PRD in einen konkreten
Lieferplan mit Epics, Tickets und Akzeptanzkriterien.

Es ist kein Architektur-Fork und kein offener Feature-Spielplatz. Alle Tickets
muessen die aktive Produktgrenze respektieren:

- Lite ist die Default-Surface.
- Pro ist optional und diagnose-lastig.
- Es gibt keine zweite Signal-Engine.

## Companion Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-tradingview-first-release-ticketset.md`
- `docs/smc-tradingview-first-ui-cut-implementation.md`
- `docs/smc-lite-pro-product-cut.md`
- `docs/SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md`

## Delivery Rules

1. Keine neue Logikfamilie fuer Lite.
2. Keine Pro-Diagnose auf der Lite-Default-Surface.
3. Jede UI-Aenderung braucht eine klare Nutzerfunktion.
4. Copy, Visual Hierarchy und Alert-Semantik muessen synchron sein.
5. Doku und visuelle Validierung sind Teil des Deliverables.

## Epic Overview

| ID | Epic | Hauptresultat | Hauptartefakte | Prioritaet |
| --- | --- | --- | --- | --- |
| E1 | Shared Action Model | Einheitliche Handlungslogik und Begriffswelt | `SMC_Core_Engine.pine`, `SkippALGO.pine`, Docs | P1 |
| E2 | SMC Core Lite Surface | Decision-first Hero-Surface fuer aktive Nutzung | `SMC_Core_Engine.pine` | P1 |
| E3 | SMC Dashboard Split | Trennung zwischen Compact Detail und Pro Diagnostics | `SMC_Dashboard.pine` | P1 |
| E4 | SkippALGO Surface Redesign | Status-, Outlook-, Forecast- und Label-Fuehrung | `SkippALGO.pine` | P1 |
| E5 | Settings Simplification | Preset-first Bedienung statt Tuning-Labor | alle drei Pine-Skripte | P1 |
| E6 | Trust And Evidence UX | Explizite Unsicherheit statt falscher Praezision | `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SkippALGO.pine` | P2 |
| E7 | Docs And Validation | Benutzerfuehrung, Visual QA und Release-Gates | Docs, Checklists, Validation | P2 |

## E1 - Shared Action Model And Product Language

### T1.1 Shared Product Action Resolver

- Scope: Ein gemeinsames sichtbares Aktionsmodell fuer Lite-Surfaces definieren.
- Ergebnis: `WAIT`, `PREPARE`, `READY`, `ENTER`, `MANAGE`, `REDUCE RISK`,
  `AVOID`, `BLOCKED`.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SkippALGO.pine`, Docs.
- Abhaengigkeiten: keine.
- Acceptance Criteria:
  - Alle Lite-Surfaces zeigen genau einen primaeren Product State.
  - `READY` und `ENTER` sind sichtbar von `WAIT` und `AVOID` getrennt.
  - `BLOCKED` wird nur bei echten Hard-Blockern verwendet.
  - Das Mapping ist in Doku und UI-Textern synchron beschrieben.

### T1.2 Shared Top-Surface Terminology Map

- Scope: Top-Surface-Begriffe auf Handlungssprache umstellen.
- Ergebnis: technische Begriffe bleiben in Pro oder Guides, nicht in Lite.
- Hauptartefakte: `SMC_Dashboard.pine`, `SkippALGO.pine`, Guides.
- Abhaengigkeiten: T1.1.
- Acceptance Criteria:
  - Lite zeigt keine BUS-, Pack-, Reason- oder Debug-Namen.
  - Begriffe wie `MinTrust`, `Pred(N)`, `Pred(1)`, `LTF Delta` sind
    nutzerseitig uebersetzt.
  - Die Copy ist zwischen Chart, Dashboard und Alerts konsistent.

### T1.3 Shared Uncertainty Vocabulary

- Scope: Vertrauens- und Unsicherheitszustande vereinheitlichen.
- Ergebnis: `Strong`, `Usable`, `Thin`, `Provisional` plus klare Risiko-Texte.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SkippALGO.pine`, Guides.
- Abhaengigkeiten: T1.1.
- Acceptance Criteria:
  - Confidence ist in Lite nie nur nackte Zahl.
  - Warmup, degraded und thin evidence sind verbal sichtbar.
  - Exact-percent precision ist sekundar, nicht primaer.

## E2 - SMC Core Lite Surface

### T2.1 Compact Hero Card For `SMC_Core_Engine.pine`

- Scope: Eine Hero-Surface fuer die aktive Nutzung implementieren.
- Ergebnis: 5 bis 6 Zeilen mit Action, Bias, Quality, Why Now, Main Risk und
  optional Risk Plan.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Abhaengigkeiten: E1.
- Acceptance Criteria:
  - Die Default-Surface ist in <= 5 Sekunden erfassbar.
  - Action, Why Now und Main Risk sind immer sichtbar.
  - Tiefe Diagnose ist standardmaessig nicht sichtbar.

### T2.2 Actionable-Only Risk Presentation

- Scope: Trigger, Invalidation und Risk Plan nur dann zeigen, wenn sie
  nutzerseitig relevant sind.
- Ergebnis: kein permanentes Linien- und Level-Rauschen ohne Setup-Reife.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Abhaengigkeiten: T2.1.
- Acceptance Criteria:
  - Risk-Linien erscheinen nur bei `READY`, `ENTER`, `MANAGE` oder aktiver
    Position.
  - `WAIT` und `PREPARE` erzeugen kein volles Risk-Overlay.
  - Ein Nutzer kann aktive von vorbereitenden Zustanden visuell klar trennen.

### T2.3 Default Visual Budget Reduction

- Scope: Historische Labels, tiefe Marker und additive Chart-Elemente im
  Default reduzieren.
- Ergebnis: mehr Prioritaet fuer Hero-Signal und aktive Zone.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Abhaengigkeiten: T2.1.
- Acceptance Criteria:
  - Default-Modus zeigt nur die fuer den aktuellen Zustand relevanten Marker.
  - Historische Debug- oder Diagnoseobjekte sammeln sich im Lite-Modus nicht.
  - Mobile- oder kleine Chartflaechen bleiben lesbarer als zuvor.

### T2.4 Compact Detail Handoff To Dashboard

- Scope: Lite-Hero und Dashboard-Detail sauber trennen.
- Ergebnis: Core zeigt Entscheidung, Dashboard erklaert Entscheidung.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`.
- Abhaengigkeiten: T2.1, E3.
- Acceptance Criteria:
  - Im Core gibt es keine Pro-Diagnose-Redundanz.
  - Dashboard-Detail erklaert Hero-Zustand, dupliziert ihn aber nicht nur.

## E3 - SMC Dashboard Split

### T3.1 Compact Detail Mode For `SMC_Dashboard.pine`

- Scope: Eine reduzierte Dashboard-Ansicht mit 5 bis 8 zeilenorientierten
  Entscheidungserklaerungen schaffen.
- Ergebnis: Structure, Session, Event/Data, Pressure, Risk Plan als
  komprimierte Nutzererklaerung.
- Hauptartefakt: `SMC_Dashboard.pine`.
- Abhaengigkeiten: E1.
- Acceptance Criteria:
  - Compact Detail nutzt keine internen BUS-Namen.
  - Maximal 8 Zeilen im Default-Detail.
  - Jede Zeile endet in einem klaren Verdict wie `supports`, `mixed`, `blocks`.

### T3.2 Pro Diagnostics Mode

- Scope: Die aktuelle Diagnosetiefe fuer Power-User erhalten, aber explizit als
  Pro ausweisen.
- Ergebnis: Lifecycle, Quality, Gate, Support, Risk und Debug bleiben
  verfuegbar, aber nicht Default.
- Hauptartefakt: `SMC_Dashboard.pine`.
- Abhaengigkeiten: T3.1.
- Acceptance Criteria:
  - Pro Diagnostics ist nicht die Standardansicht.
  - Debug- und Detailzeilen bleiben funktional verfuegbar.
  - Lite- und Pro-Texte widersprechen sich nicht.

### T3.3 Dashboard Row Regrouping

- Scope: Bestehende Zeilen in Nutzerkategorien statt Technikfamilien gruppieren.
- Ergebnis: `Decision Detail`, `Context`, `Risk`, `Diagnostics`.
- Hauptartefakt: `SMC_Dashboard.pine`.
- Abhaengigkeiten: T3.1, T3.2.
- Acceptance Criteria:
  - Nutzer sieht zuerst Entscheidungserklaerung, erst spaeter Diagnose.
  - Row-Gruppen sind im Code und in der Guide-Doku deckungsgleich.

### T3.4 Operator-Only Binding Strategy

- Scope: Die `input.source()`-Bindungsflaeche fuer den BUS als Operator-Lage
  markieren oder spaeter automatisierbar vorbereiten.
- Ergebnis: keine Endnutzer-Illusion, dass dies eine normale Public-UI ist.
- Hauptartefakt: `SMC_Dashboard.pine` und Doku.
- Abhaengigkeiten: keine.
- Acceptance Criteria:
  - Binding-Surface ist als operator-only dokumentiert.
  - Public Lite-Nutzer muessen keine BUS-Reihenfolge manuell verdrahten.

## E4 - SkippALGO Surface Redesign

### T4.1 Status Header To Decision Header

- Scope: Die bestehende Statuszeilenlogik in eine klare Decision Header Surface
  ueberfuehren.
- Ergebnis: Action, Trade Threshold, Position, Last Action und Why/Why Not in
  klarer Hierarchie.
- Hauptartefakt: `SkippALGO.pine`.
- Abhaengigkeiten: E1.
- Acceptance Criteria:
  - `Confidence`, `MinTrust`, `Pos`, `LastSig` wirken nicht mehr wie vier
    gleich laute Datenfelder.
  - Hauptaktion und Hauptrisiko stehen vor Sekundaermetriken.

### T4.2 Outlook Block Simplification

- Scope: Outlook von Diagnoseblock zu schneller State-Lesehilfe umbauen.
- Ergebnis: TF, Bias, State Strength und kurzer Regimehinweis statt
  Debug-Charakter.
- Hauptartefakt: `SkippALGO.pine`.
- Abhaengigkeiten: T4.1.
- Acceptance Criteria:
  - Ein Nutzer kann pro TF schnell bullish, bearish oder mixed lesen.
  - Die Tabelle ist ohne Guide grob interpretierbar.

### T4.3 Forecast Block Simplification

- Scope: Forecast von Modellansicht zu nutzerseitiger Prognoseoberflaeche
  uebersetzen.
- Ergebnis: `Stable Forecast`, `Early Forecast`, `Evidence`, `Risk Hint`.
- Hauptartefakt: `SkippALGO.pine`.
- Abhaengigkeiten: T4.1, E6.
- Acceptance Criteria:
  - `Pred(N)` und `Pred(1)` sind auf Lite nicht mehr sichtbar.
  - Warmup und geringe Evidenz sind klar markiert.
  - Tabellenlayout priorisiert Nutzbarkeit vor Modellselbsterklaerung.

### T4.4 Label And Alert Parity

- Scope: Chart-Labels, runtime alerts und table states auf dieselbe Sprache
  bringen.
- Ergebnis: ein durchgaengiges Aktionsvokabular.
- Hauptartefakte: `SkippALGO.pine`, Doku.
- Abhaengigkeiten: T4.1 bis T4.3.
- Acceptance Criteria:
  - Alerts und Labels verwenden denselben Product State.
  - `BUY` / `SHORT` ohne Kontext werden in Lite reduziert oder erklaert.
  - `REDUCE RISK`, `AVOID` und `BLOCKED` sind alert-seitig abbildbar.

## E5 - Settings Simplification

### T5.1 Lite Visible Inputs Matrix

- Scope: Pro Skript definieren, welche Inputs im Lite-Modus sichtbar sein
  duerfen.
- Ergebnis: User Preset, Signal Mode, Risk Profile, HTF Mode, Alerts,
  Visual Mode.
- Hauptartefakte: alle drei Pine-Skripte, Doku.
- Abhaengigkeiten: E1.
- Acceptance Criteria:
  - Lite zeigt maximal 10 direkt sichtbare Standard-Inputs.
  - Experteninputs bleiben standardmaessig versteckt.

### T5.2 Advanced Settings Gate

- Scope: Explizite Aktivierung fuer tiefe Tuning- und Diagnoseinputs.
- Ergebnis: kein versehentliches Modelllabor fuer Standardnutzer.
- Hauptartefakte: alle drei Pine-Skripte.
- Abhaengigkeiten: T5.1.
- Acceptance Criteria:
  - Ohne Aktivierung von `Advanced Settings` sind Gate-Engine-Details nicht
    sichtbar.
  - Presets funktionieren ohne manuelles Expertenwissen.

### T5.3 Preset Migration And Safe Defaults

- Scope: Bestehende Nutzer in den neuen Surface-Modus ueberfuehren, ohne
  Signalsystem still zu aendern.
- Ergebnis: sichere Defaults plus klare Upgrade-Kommunikation.
- Hauptartefakte: Pine-Skripte, Guides, Changelog.
- Abhaengigkeiten: T5.1, T5.2.
- Acceptance Criteria:
  - Default-Verhalten bleibt nachvollziehbar.
  - Bestehende Nutzer verlieren keine Pro-Funktionen.
  - Migration ist dokumentiert.

## E6 - Trust And Evidence UX

### T6.1 Confidence Tier Presentation

- Scope: Confidence in Lite als Tier plus Zweitwert zeigen.
- Ergebnis: `Strong`, `Usable`, `Thin`, `Provisional`.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SkippALGO.pine`.
- Abhaengigkeiten: E1.
- Acceptance Criteria:
  - Confidence-Tier ist primaer, Prozentwert sekundar.
  - Hauptscreen transportiert keine falsche Praezision.

### T6.2 Explicit Evidence And Data Quality Signals

- Scope: Warmup, thin evidence, weak volume und degraded mode explizit machen.
- Ergebnis: sichtbare Unsicherheits- und Datenqualitaetslayer.
- Hauptartefakte: alle drei Pine-Skripte.
- Abhaengigkeiten: T6.1.
- Acceptance Criteria:
  - Ein Nutzer erkennt, wann das System nur vorlaeufig spricht.
  - Datenqualitaet ist auf Lite sichtbar, ohne tiefe Diagnose zu benoetigen.

### T6.3 False Precision Reduction

- Scope: Zahlen auf der Lite-Surface vereinfachen und priorisieren.
- Ergebnis: weniger Prozent- und Diagnoseclutter, mehr eindeutige Verdicts.
- Hauptartefakte: `SkippALGO.pine`, `SMC_Dashboard.pine`.
- Abhaengigkeiten: T6.1, T6.2.
- Acceptance Criteria:
  - Prozentwerte sind nicht mehr die Hauptbotschaft.
  - Lite-Oberflaeche kommuniziert zuerst Handlung, dann Genauigkeit.

## E7 - Docs And Validation

### T7.1 User-Facing Documentation Refresh

- Scope: Guides und Nutzertexte auf die neue Surface abstimmen.
- Ergebnis: Guide, PRD, Screen Spec und Changelog sind konsistent.
- Hauptartefakte: Doku.
- Abhaengigkeiten: E2 bis E6.
- Acceptance Criteria:
  - Die relevanten Guides erklaeren Lite und Pro korrekt.
  - Screenshots und Copy stimmen mit dem Code ueberein.

### T7.2 Visual Validation Checklist

- Scope: eine visuelle Validierung fuer Lite, Pro und Mobile-Nahe definieren.
- Ergebnis: wiederholbare Screenshot- und Review-Checkliste.
- Hauptartefakte: Doku, manuelle Validation.
- Abhaengigkeiten: E2 bis E6.
- Acceptance Criteria:
  - Es gibt eine klare Pass/Fail-Liste fuer die neue Surface.
  - Hero-Readability und Action Clarity werden explizit geprueft.

### T7.3 Compile And Behavior Safety Gate

- Scope: UX-Umbau darf Semantik nicht still brechen.
- Ergebnis: Compile-, parity- und behavior-checks als Abschlussbedingung.
- Hauptartefakte: Tests, Validation-Doku.
- Abhaengigkeiten: E2 bis E6.
- Acceptance Criteria:
  - Pine compile checks bleiben gruen.
  - Alert- und state-seitige Verhaltensregressionen sind geprueft.
  - Lite/Pro-Surface-Aenderungen aendern nicht still die aktive Engine-Logik.

## Suggested Phase Order

1. E1 Shared Action Model And Product Language
2. E2 SMC Core Lite Surface
3. E3 SMC Dashboard Split
4. E4 SkippALGO Surface Redesign
5. E5 Settings Simplification
6. E6 Trust And Evidence UX
7. E7 Docs And Validation

## Release Readiness Gate

Der Decision-First-UX-Cut ist erst release-ready, wenn alle folgenden Punkte
erfuellt sind:

1. Lite-Surfaces zeigen nur eine primaere Handlungsaufforderung.
2. Pro Diagnostics ist nicht mehr die Standardansicht.
3. Nutzerrelevante Unsicherheit ist explizit sichtbar.
4. Alerts, Labels, Hero-Surface und Guides sprechen dieselbe Sprache.
5. Compile-, behavior- und visuelle Checks sind gruen.

## Executive Delivery Rule

Wenn ein Ticket nur mehr Technik sichtbar macht, aber keine schnellere und
belastbarere Entscheidung fuer den Nutzer erzeugt, gehoert es nicht in diesen
Backlog.

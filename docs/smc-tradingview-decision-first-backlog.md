# SMC Decision-First UX Implementation Backlog

## Status

Draft

## Zweck

Dieses Dokument uebersetzt das Decision-First-PRD in einen konkreten
Lieferplan fuer die drei SMC-TradingView-Surfaces:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`

Es ist kein Architektur-Fork. Alle Tickets muessen die aktive Produktgrenze
respektieren:

- Core bleibt Producer und primaere Surface.
- Dashboard bleibt Companion und Diagnose-Lage.
- Long Strategy bleibt Wrapper auf dem Core-BUS.

## Companion Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-tradingview-first-release-ticketset.md`
- `docs/smc-tradingview-first-ui-cut-implementation.md`
- `docs/smc-lite-pro-product-cut.md`
- `docs/TRADINGVIEW_STRATEGY_GUIDE.md`

## Delivery Rules

1. Keine neue Logikfamilie fuer Lite.
2. Core, Dashboard und Long Strategy behalten ihre bestehenden Contracts.
3. Dashboard- und Strategy-Bindings bleiben operator-only, solange sie nicht
   explizit produktisiert wurden.
4. Jede UI-Aenderung braucht eine klare Nutzerfunktion.
5. Doku und visuelle Validierung sind Teil des Deliverables.

## Epic Overview

| ID | Epic | Hauptresultat | Hauptartefakte | Prioritaet |
| --- | --- | --- | --- | --- |
| E1 | Shared Product Language | Einheitliche Begriffswelt fuer Core, Dashboard und Strategy Wrapper | `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`, Docs | P1 |
| E2 | SMC Core Lite Surface | Decision-first Hero-Surface fuer aktive Nutzung | `SMC_Core_Engine.pine` | P1 |
| E3 | SMC Decision Board Split | Compact Detail, Pro Diagnostics und operator-only Companion sauber trennen | `SMC_Dashboard.pine` | P1 |
| E4 | SMC Execution Surface | Strategy-Setup, Binding und Chart-Ausgabe produktisieren | `SMC_Long_Strategy.pine` | P1 |
| E5 | Docs And Validation | Guide, Validation und Release-Gates auf dieselben drei Surfaces ausrichten | Docs, Tests, Validation | P2 |

## E1 - Shared Product Language

### T1.1 Core / Dashboard / Strategy Naming Parity

- Scope: sichtbare Begriffe fuer Action, Risk, Quality und Setup angleichen.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`,
  `SMC_Long_Strategy.pine`, Docs.
- Acceptance Criteria:
  - Core und Dashboard sprechen dieselbe Lite-Sprache.
  - Die Long Strategy liest sich wie Wrapper auf dieselbe Produktlogik,
    nicht wie ein separates Teilprodukt.
  - Lite, Pro und operator-only sind sprachlich klar getrennt.

### T1.2 Shared Risk And Plan Copy

- Scope: Trigger, Invalidation, Quality und Plan-Level in allen drei Surfaces
  konsistent beschreiben.
- Hauptartefakte: `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`,
  `SMC_Long_Strategy.pine`.
- Acceptance Criteria:
  - Risk-Plan-Begriffe widersprechen sich nicht.
  - Strategy-Level zeigen dieselbe Plan-Lesart wie der Core.

### T1.3 Operator-Only Boundary Marking

- Scope: Binding-Flaechen im Dashboard und in der Strategy explizit als
  operator-only markieren.
- Hauptartefakte: `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`, Guides.
- Acceptance Criteria:
  - Endnutzer halten Binding-Screens nicht fuer normale Public-UI.
  - Die Bindungsreihenfolge ist dokumentiert und deterministisch.

## E2 - SMC Core Lite Surface

### T2.1 Compact Hero Card

- Scope: Hero-Surface mit `Action`, `Bias`, `Quality`, `Why now`, `Main risk`.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Acceptance Criteria:
  - Der Core ist in <= 5 Sekunden lesbar.
  - Action, Why now und Main risk sind die erste Lesestufe.

### T2.2 Actionable-Only Risk Presentation

- Scope: Trigger, Invalidation und Risk Plan nur zeigen, wenn sie wirklich
  relevant sind.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Acceptance Criteria:
  - `WAIT` und `PREPARE` erzeugen kein volles Risk-Overlay.
  - `READY`, `ENTER` und aktive Positionen zeigen Plan-Level klar.

### T2.3 Default Visual Budget Reduction

- Scope: Debug- und Diagnoseclutter auf der Default-Surface reduzieren.
- Hauptartefakt: `SMC_Core_Engine.pine`.
- Acceptance Criteria:
  - Lite wirkt wie Produkt, nicht wie Labor.
  - Pro-Tiefe bleibt verfuegbar, aber nachrangig.

## E3 - SMC Decision Board Split

### T3.1 Compact Detail Default

- Scope: Default-Dashboard auf kompakte Entscheidungserklaerung reduzieren.
- Hauptartefakt: `SMC_Dashboard.pine`.
- Acceptance Criteria:
  - Default-Detail hat maximal 6 bis 8 Kernzeilen.
  - BUS-Terminologie ist in Compact Detail nicht sichtbar.

### T3.2 Pro Diagnostics Retention

- Scope: die bestehende Tiefe erhalten, aber klar als Pro kennzeichnen.
- Hauptartefakt: `SMC_Dashboard.pine`.
- Acceptance Criteria:
  - Pro Diagnostics bleibt funktional.
  - Compact und Pro sind als zwei verschiedene Lesestufen erkennbar.

### T3.3 Operator Binding Workflow

- Scope: den Companion-Workflow fuer Dashboard-Bindings klar dokumentieren.
- Hauptartefakte: `SMC_Dashboard.pine`, Guides.
- Acceptance Criteria:
  - Binding order ist explizit beschrieben.
  - Endnutzer muessen das Dashboard nicht manuell verdrahten, um den Core zu
    verstehen.

## E4 - SMC Execution Surface

### T4.1 Strategy Setup Surface Simplification

- Scope: sichtbare Wrapper-Steuerung auf `Entry Mode`, `Min Quality Score`,
  `Take Profit R` und `Use Take Profit` fokussieren.
- Hauptartefakt: `SMC_Long_Strategy.pine`.
- Acceptance Criteria:
  - Die Setup-Flaeche liest sich wie Strategy-Konfiguration, nicht wie roher
    Binding-Dump.
  - Sichtbare Controls erklaeren den Wrapper-Zweck.

### T4.2 Strategy Binding Surface Clarity

- Scope: BUS-Bindings klar von den eigentlichen Setup-Controls trennen.
- Hauptartefakt: `SMC_Long_Strategy.pine`.
- Acceptance Criteria:
  - Die top-to-bottom Binding-Reihenfolge ist im Code und in der Doku
    konsistent.
  - Operator-only Bindings sind als solche erkennbar.

### T4.3 Strategy Chart Output Parity

- Scope: Trigger, Invalidation und Take-Profit-Linien als planbare
  Strategy-Ausgabe positionieren.
- Hauptartefakt: `SMC_Long_Strategy.pine`.
- Acceptance Criteria:
  - Die Wrapper-Ausgabe widerspricht dem Core nicht.
  - Entry-Staging und Exit-Plan bleiben deterministisch lesbar.

## E5 - Docs And Validation

### T5.1 Documentation Alignment

- Scope: PRD, Screen Spec, Ticketset, Implementierungsvorbereitung und Guide
  auf dieselben drei SMC-Surfaces ausrichten.
- Hauptartefakte: Doku.
- Acceptance Criteria:
  - Kein SMC-Dokument beschreibt fremde TradingView-Skripte als Teil dieses
    Scopes.
  - Core, Dashboard und Long Strategy sind in allen Decision-First-Dokumenten
    konsistent.

### T5.2 Visual Validation Checklist

- Scope: visuelle Validation fuer Core, Dashboard und Strategy definieren.
- Hauptartefakte: Doku, manuelle Validation.
- Acceptance Criteria:
  - Es gibt eine klare Pass/Fail-Liste fuer alle drei SMC-Surfaces.

### T5.3 Compile And Behavior Safety Gate

- Scope: UI-Umbau darf Semantik und BUS-Contract nicht still brechen.
- Hauptartefakte: Tests, Validation-Doku.
- Acceptance Criteria:
  - Pine compile checks bleiben gruen.
  - Consumer- und BUS-Contracts bleiben intakt.

## Suggested Phase Order

1. E1 Shared Product Language
2. E2 SMC Core Lite Surface
3. E3 SMC Decision Board Split
4. E4 SMC Execution Surface
5. E5 Docs And Validation

## Release Readiness Gate

Der Decision-First-UX-Cut ist erst release-ready, wenn alle folgenden Punkte
erfuellt sind:

1. Core kommuniziert zuerst Action, Why und Main risk.
2. Dashboard Compact Detail ist klarer als Pro Diagnostics.
3. Long Strategy ist als Wrapper und Binding-Surface deterministisch lesbar.
4. Operator-only Bindings sind explizit markiert.
5. Compile-, behavior- und visuelle Checks sind gruen.

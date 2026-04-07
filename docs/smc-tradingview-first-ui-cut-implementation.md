# SMC First UI Cut Implementation Preparation

## Status

Implemented

## Zweck

Dieses Dokument bereitet die erste konkrete UI-Umsetzung fuer die drei
SMC-TradingView-Surfaces vor:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`

Es ist keine Release-Note und kein abstrakter Wunschzettel. Es beschreibt den
ersten umsetzbaren UI-Cut mit realen Code-Ankern, Edit-Reihenfolge und
Validierungsregeln.

## Source Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-tradingview-first-release-ticketset.md`

## Working Rules

1. Keine neue Signal-Engine.
2. Sichtbare UX zuerst, Core-Verhalten nur dort anfassen, wo Sprache und
   Lifecycle gekoppelt sind.
3. Dashboard und Long Strategy bleiben Consumer des Core-BUS.
4. Operator-only Binding-Screens muessen explizit bleiben.

## Shared Implementation Decisions

### Gemeinsames Produktvokabular

- Product States:
  - `WAIT`
  - `PREPARE LONG` / `PREPARE SHORT`
  - `READY LONG` / `READY SHORT`
  - `ENTER LONG` / `ENTER SHORT`
  - `MANAGE LONG` / `MANAGE SHORT`
  - `REDUCE RISK`
  - `AVOID`
  - `BLOCKED`
- Plan-Sprache:
  - `Trigger`
  - `Invalidation`
  - `Risk Plan`
  - `Take Profit`

### Shared Copy Contract

- Zeile 1: `Action`
- Zeile 2: `Why now`
- Zeile 3: `Main risk`
- Sekundaer: `Bias`, `Quality`, `Risk Plan`, Strategy-Setup

## Current Code Anchor Map

| Surface | Aktuelle Anker | Bedeutung fuer den ersten UI-Cut |
| --- | --- | --- |
| `SMC_Core_Engine.pine` | `long_user_preset`, `compact_mode`, `show_dashboard`, `enable_dynamic_alerts` | sichtbare Lite- und Alert-Einstiegslogik |
| `SMC_Core_Engine.pine` | Hero-Card- und Alert-Helper | hier sitzt die neue Lite-Leselogik |
| `SMC_Dashboard.pine` | BUS-Inputs am Dateikopf | operator-only Companion-Bindings |
| `SMC_Dashboard.pine` | Compact-vs-Pro-Renderpfade | eigentlicher Dashboard-Split |
| `SMC_Long_Strategy.pine` | acht `input.source(...)`-Bindings | deterministische Wrapper-Bindung an den Core |
| `SMC_Long_Strategy.pine` | `entry_mode`, `min_quality_score`, `take_profit_r`, `use_take_profit` | sichtbare Strategy-Setup-Flaeche |
| `SMC_Long_Strategy.pine` | Trigger-/Invalidation-/Take-Profit-Plots | planbare Wrapper-Ausgabe auf dem Chart |

## Important Current-State Findings

### SMC Core

- Der Compact-Mode ist die richtige Stelle fuer die Lite-Hero-Leselogik.
- Dynamic Alerts muessen dieselbe Sprache sprechen wie die Hero-Surface.

### SMC Dashboard

- Das Dashboard rendert eine tiefe Tabelle, die fuer Default zu diagnose-lastig
  ist.
- Die BUS-Bindung ist funktional, aber klar operator-only.

### SMC Long Strategy

- Die Strategy ist ein duenner Wrapper auf dem Core-BUS.
- Sichtbare Setup-Controls und rohe BUS-Bindings liegen aktuell zu nah
  beieinander.
- Die Chart-Ausgabe ist funktional, aber noch nicht stark genug als
  produktisierte Wrapper-Surface beschrieben.

## Surface 1 - `SMC_Core_Engine.pine`

### Core First-Cut Zielbild

Eine klare chart-native Lite-Surface, die im Compact-Modus eine produktartige
Hauptbotschaft zeigt.

### Core Erste konkrete UI-Aenderungen

1. Hero-Card mit maximal 5 sichtbaren Kernzeilen stabilisieren.
2. Risk-Level nur dann zeigen, wenn der Zustand mindestens `READY` ist.
3. Dynamic-Alert-Texte an Product States koppeln.

### Core Validation

1. Lite zeigt nur eine primaere Action.
2. `WAIT` zeigt keine vollen Risk-Linien.
3. `READY` und `ENTER` zeigen Trigger und Invalidation klar.

## Surface 2 - `SMC_Dashboard.pine`

### Dashboard First-Cut Zielbild

Ein Default-Dashboard, das die Hero-Entscheidung erklaert, waehrend Pro
Diagnostics als bewusst tiefer Modus verfuegbar bleibt.

### Dashboard Erste konkrete UI-Aenderungen

1. `Compact Detail` versus `Pro Diagnostics` klar trennen.
2. Default auf 6 bis 8 Kernzeilen reduzieren.
3. BUS- und Diag-Terminologie aus dem Compact-Default entfernen.
4. Operator-only Binding im Headertext und Guide explizit markieren.

### Dashboard Validation

1. Default-Detail hat maximal 8 Zeilen.
2. Pro Diagnostics bleibt funktional erhalten.
3. Compact Default enthaelt keine sichtbaren BUS- oder Debug-Begriffe.

## Surface 3 - `SMC_Long_Strategy.pine`

### Long Strategy First-Cut Zielbild

Eine Wrapper-Surface, die Strategy-Setup, BUS-Binding und Plan-Level sauber
trennt und lesbar macht.

### Long Strategy Erste konkrete UI-Aenderungen

1. Sichtbare Setup-Controls als Strategy-Steuerung gruppieren.
2. BUS-Bindings klar als operator-only Vorstufe markieren.
3. Trigger, Invalidation und Take-Profit als planbare Wrapper-Ausgabe
   konsistent halten.

### Long Strategy Konkrete technische Vorbereitung

1. Die acht `input.source(...)`-Kanaele in Dokumentation und Tests exakt in
   derselben Reihenfolge behandeln.
2. `entry_mode`, `min_quality_score`, `take_profit_r` und `use_take_profit`
   als primaere Wrapper-Steuerung beschreiben.
3. Plot-Ausgabe als Execution-Plan und nicht als zweite Diagnoseflaeche lesen.

### Long Strategy Validation

1. Die Setup-Flaeche ist ohne Guide lesbar.
2. Die Binding-Reihenfolge ist deterministisch.
3. Chart-Ausgabe widerspricht dem Core nicht.

## Cross-Surface Edit Order

1. Shared Produkt- und Plan-Sprache festziehen.
2. SMC Core Hero Surface stabilisieren.
3. Dashboard Compact Detail Default absichern.
4. Long Strategy Wrapper-Surface dokumentieren und schaerfen.
5. Doku, Validation und operator-only Workflow angleichen.

## Manual Validation Checklist

1. Lite-Surfaces zeigen maximal eine primaere Action.
2. Kein Default-Screen wirkt wie ein Diagnoseboard.
3. Dashboard- und Strategy-Binding-Screens sind klar operator-only.
4. Core, Dashboard und Long Strategy sprechen dieselbe Plan-Sprache.
5. Guides und Tests decken denselben Dreier-Scope ab.

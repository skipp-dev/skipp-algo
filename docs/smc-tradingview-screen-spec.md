# SMC TradingView Screen Specification

## Status

Released

## Zweck

Dieses Dokument zerlegt das Decision-First-PRD in konkrete Screens fuer:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`

Es ist eine UI-Spezifikation, kein Architektur- oder Feature-Fork.

## Companion Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc-tradingview-first-release-ticketset.md`
- `docs/smc-tradingview-first-ui-cut-implementation.md`
- `docs/smc-lite-pro-product-cut.md`

## Shared Screen Rules

1. Jeder Lite-Screen zeigt genau eine primaere Hauptaktion.
2. Lite kommuniziert zuerst Entscheidung, dann Begruendung, dann Risiko.
3. Pro darf Diagnose zeigen, Lite nicht.
4. Exact numeric precision ist sekundar.
5. Interne Begriffe bleiben aus Lite heraus.

## Shared Visual Semantics

| Farbe | Bedeutung |
| --- | --- |
| Gruen | `READY`, `ENTER`, `MANAGE`, `supports` |
| Gelb / Orange | `PREPARE`, `mixed`, `reduce risk` |
| Grau | `WAIT`, `provisional`, `no evidence yet` |
| Rot | `AVOID`, `BLOCKED`, `hard risk` |
| Aqua | aktive Zone oder vorbereitender Kontext |

## Screen Inventory

| Screen | Artefakt | Rolle |
| --- | --- | --- |
| CE-1 | `SMC_Core_Engine.pine` | Lite chart default |
| CE-2 | `SMC_Core_Engine.pine` | Lite actionable chart |
| CE-3 | `SMC_Core_Engine.pine` | Lite settings |
| DB-1 | `SMC_Dashboard.pine` | Compact detail dashboard |
| DB-2 | `SMC_Dashboard.pine` | Pro diagnostics dashboard |
| DB-3 | `SMC_Dashboard.pine` | Operator binding screen |
| LS-1 | `SMC_Long_Strategy.pine` | Strategy setup surface |
| LS-2 | `SMC_Long_Strategy.pine` | Strategy actionable chart |
| LS-3 | `SMC_Long_Strategy.pine` | Strategy binding screen |

## CE-1 - SMC Core Lite Chart Default

- Goal: Die aktive Long-Dip- oder SMC-Surface in eine schnell lesbare
  Entscheidungssurface uebersetzen.
- Audience: fortgeschrittene Retail- und Solo-Operator-Nutzer.
- Mode: Lite / Compact.
- Entry condition: kein aktiver Trade oder frueher Setup-Zustand.
- Primary action: `WAIT`, `PREPARE LONG`, `PREPARE SHORT`, `AVOID`, `BLOCKED`.
- Visible blocks:
  - Hero Card
  - aktive Zone
  - maximal ein vorbereitender Marker
- Hidden by default:
  - tiefe Diagnosezeilen
  - Debug-Marker
  - historische Marker-Historie
  - Objektezaehlung und tiefe LTF-/DDVI-/SD-Diagnose
- Low-fidelity wireframe:

```text
+----------------------------------+
| ACTION        PREPARE LONG       |
| Bias          Bullish            |
| Why now       Zone + reclaim     |
| Main risk     Event risk mixed   |
| Quality       Usable             |
+----------------------------------+
```

- Field mapping:
  - `Action` <- sichtbarer Product State aus Lifecycle + Gate-Lage
  - `Bias` <- Trend / direction summary
  - `Why now` <- Hauptgrund, kein Diagnose-Dump
  - `Main risk` <- groesster Blocker oder Konflikt
  - `Quality` <- Vertrauens-Tier statt exakter Score als Hauptsignal
- Copy rules:
  - kein `Entry Best`, `Entry Strict`, `BUS`, `LTF Delta` auf Lite
  - kein `n/a`, wenn `No evidence yet` moeglich ist
- Acceptance criteria:
  - Nutzer kann Hauptaktion ohne Guide benennen.
  - Screen wirkt wie Produkt, nicht wie Diagnosepaneel.

## CE-2 - SMC Core Lite Actionable Chart

- Goal: Bei reifem Setup oder aktiver Position die noetigen Aktions- und
  Risikoinformationen zeigen, ohne zur Pro-Surface zu werden.
- Audience: aktiver Nutzer waehrend `READY`, `ENTER`, `MANAGE`.
- Mode: Lite / Compact.
- Entry condition: Setup mindestens `READY` oder Position aktiv.
- Primary action: `READY LONG`, `READY SHORT`, `ENTER LONG`, `ENTER SHORT`,
  `MANAGE`, `REDUCE RISK`.
- Visible blocks:
  - Hero Card
  - Trigger
  - Invalidation
  - kompakter Risk Plan
  - maximal ein primaeres Entry- oder Exit-Label pro Bar
- Hidden by default:
  - tiefe Gate- und Diagnostics-Stacks
  - mehrere konkurrierende Aktionslabels auf derselben Bar
- Low-fidelity wireframe:

```text
+----------------------------------+
| ACTION        ENTER LONG         |
| Bias          Bullish            |
| Why now       Trigger confirmed  |
| Main risk     Thin early volume  |
| Risk          Trg 18.40 / Inv 18.12 |
+----------------------------------+
```

- Behavior rules:
  - Risk-Linien erscheinen erst ab actionable State.
  - `REDUCE RISK` verdrangt `ENTER` als primaere Botschaft, wenn der Kontext
    kippt.
  - Kein zweites hero-relevantes Label auf derselben Bar.
- Acceptance criteria:
  - Nutzer erkennt Trigger und Invalidation ohne Pro-Dashboard.
  - Der Chart bleibt lesbar, auch wenn Risk-Linien aktiv sind.

## CE-3 - SMC Core Lite Settings

- Goal: Eine preset-first Settings Surface fuer normale Nutzer.
- Audience: alle Lite-Nutzer.
- Mode: Lite.
- Visible inputs:
  - Trading Style
  - Signal Mode
  - Risk Profile
  - HTF Mode
  - Alerts
  - Focus View
  - Show Decision Brief
- Hidden inputs:
  - tiefe per-stage gates
  - LTF guardrails
  - DDVI / SD / stretch internals
  - Debug toggles
- Layout rule:

```text
General
- Trading Style
- Signal Mode

Risk
- Risk Profile

Context
- HTF Mode

Output
- Alerts
- Focus View
- Show Decision Brief

Advanced Settings [collapsed by default]
```

- Acceptance criteria:
  - Lite zeigt maximal 10 direkt sichtbare Standard-Inputs.
  - Ein Nutzer kann ohne Expertenwissen den Default-Modus betreiben.

## DB-1 - SMC Decision Board Compact Detail

- Goal: Die Hero-Entscheidung erklaeren, ohne in die volle Diagnose abzurutschen.
- Audience: Nutzer, die mehr Kontext wollen, aber keine Pro-Diagnose brauchen.
- Mode: Decision Brief.
- Primary action: keine neue Hauptaktion; dieser Screen erklaert den Hero State.
- Visible blocks:
  - Structure
  - Session / Market Context
  - Event / Data Quality
  - Pressure / Momentum
  - Risk Plan bei actionable State
- Hidden blocks:
  - Debug Flags
  - Long Debug
  - tiefe row-by-row module diagnostics
  - BUS Naming
- Low-fidelity wireframe:

```text
+--------------------------------------+
| Structure          supports long     |
| Session            mixed             |
| Event Risk         clear             |
| Data Quality       thin              |
| Short-term Pressure against long     |
| Risk Plan          trg / stop / tp   |
+--------------------------------------+
```

- Field mapping suggestion:
  - `Structure` <- Lean structure / zone / reclaim summary
  - `Session` <- lean session + market gate reduction
  - `Event Risk` <- lean event risk summary
  - `Data Quality` <- volume / micro availability summary
  - `Short-term Pressure` <- condensed LTF / momentum verdict
- Acceptance criteria:
  - Maximal 8 Zeilen im Default-Detail.
  - Ein normaler Nutzer muss keine Guide-Abkuerzungen kennen.

## DB-2 - SMC Decision Board Audit View

- Goal: Die bestehende Diagnosetiefe fuer Audit, Tuning und Debug sichtbar
  halten.
- Audience: Power-User und Operatoren.
- Mode: Audit View.
- Visible blocks:
  - Lifecycle
  - Lean Surface
  - Gates
  - Quality Rows
  - Support / Metrics
  - Risk / Plan
  - Debug
- Layout rules:
  - Gruppierung nach Nutzerzweck statt Rohreihenfolge
  - `Decision Detail` immer oben, `Diagnostics` darunter
  - Debug klar als Debug markieren
- Copy rules:
  - interne Begriffe sind erlaubt, wenn sie dokumentiert sind
  - BUS-Praefixe muessen nicht in sichtbarer Zeile auftauchen
- Acceptance criteria:
  - Pro bleibt tief genug fuer Audit-Zwecke.
  - Pro ist nicht mehr die implizite Standardansicht.

## DB-3 - SMC Decision Board Operator Binding Screen

- Goal: Falls `SMC_Dashboard.pine` weiter als Companion-Skript genutzt wird,
  muss die Bindung als Operator-Lage spezifiziert sein.
- Audience: nur Operatoren oder interne Nutzer.
- Mode: Operator only.
- Visible blocks:
  - Binding status
  - Lifecycle bindings
  - diagnostic row bindings
  - detail bindings
- UX rule:
  - dieser Screen ist kein Endnutzer-Screen
  - public documentation muss klar sagen, dass dies kein normales Lite-Setup ist
- Acceptance criteria:
  - Endnutzer muessen diese Surface nicht verstehen, um das Produkt zu nutzen.
  - Die Bindung ist in Doku oder Workflow klar als operator-only markiert.

## LS-1 - SMC Execution Setup Surface

- Goal: Die sichtbare Strategy-Wrapper-Flaeche auf klare Setup-Steuerung
  fokussieren.
- Audience: Operatoren und Nutzer, die den Core-BUS in Orders oder Backtests
  ueberfuehren.
- Mode: Wrapper setup.
- Visible controls:
  - `Entry Stage`
  - `Minimum Setup Quality`
  - `Profit Target (R)`
  - `Enable Profit Target`
- Hidden or visually separated:
  - BUS source inputs
- Acceptance criteria:
  - Die Surface liest sich wie Strategy-Setup.
  - Wrapper-Controls sind von den Bindings klar getrennt.

## LS-2 - SMC Execution Actionable Chart

- Goal: Die aus dem Core abgeleiteten Ausfuehrungslevel klar auf dem Chart
  zeigen.
- Audience: Nutzer waehrend Entry-Staging, aktiver Position und Backtest-Review.
- Mode: Actionable / active position.
- Visible blocks:
  - Entry Price
  - Stop Loss
  - Profit Target line
- Behavior rules:
  - Entries werden auf bestaetigten Bars gestaged.
  - Die Wrapper-Ausgabe widerspricht dem Core-Plan nicht.
- Acceptance criteria:
  - Entry- und Exit-Plan sind visuell nachvollziehbar.
  - Strategy-Level bleiben deterministisch lesbar.

## LS-3 - SMC Execution Binding Screen

- Goal: Die BUS-Bindungsflaeche fuer den Wrapper deterministisch halten.
- Audience: nur Operatoren oder interne Nutzer.
- Mode: Operator only.
- Visible groups:
  - entry state bindings
  - trade plan bindings
- UX rule:
  - dieser Screen ist kein Endnutzer-Screen
  - public documentation muss klar sagen, dass dies kein normales Lite-Setup ist
- Acceptance criteria:
  - Die top-to-bottom Binding-Reihenfolge ist eindeutig.
  - Der Wrapper ist klar als Consumer des Core-BUS erkennbar.

## Global Acceptance Criteria

1. Jede Lite-Surface kommuniziert zuerst `Action`, dann `Why`, dann `Risk`.
2. Kein Lite-Screen zeigt interne BUS-, Pack- oder Debug-Begriffe.
3. Die Default-Visualisierung ist klarer als die heutige Screenshot-Lage.
4. Core, Dashboard, Wrapper und Guide-Texte sprechen dieselbe Sprache.
5. Pro Diagnostics bleibt verfuegbar, aber klar getrennt.

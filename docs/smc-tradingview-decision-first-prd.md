# SMC TradingView UX PRD (Decision-First)

## Status

Draft

## Ziel

Dieses PRD beschreibt den Produkt- und UX-Umbau der TradingView-Surface fuer
`SMC_Core_Engine.pine`, `SMC_Dashboard.pine` und `SMC_Long_Strategy.pine`.

Das Ziel ist nicht eine neue Signal-Engine, sondern eine klarere Produktform:

- weg vom Diagnose-Cockpit als Default
- hin zu einer decision-first Operator-Surface
- ohne Fork der aktiven Signal- und Gate-Logik

Der Referenzmodus fuer die Produktqualitaet bleibt die kompakte Lite-Surface.
Die Pro-Surface bleibt Diagnose-, Audit- und Tuning-Lage.

## Verknuepfte Dokumente

- `docs/smc-lite-pro-product-cut.md`
- `docs/SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md`
- `docs/SMC_Dashboard_Long_Dip_Guide_DE.md`
- `docs/TRADINGVIEW_STRATEGY_GUIDE.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-tradingview-first-release-ticketset.md`
- `docs/smc-tradingview-first-ui-cut-implementation.md`

## Problem Statement

Die aktuelle Surface zeigt fachliche Tiefe, aber nicht konsequent genug
Handlungsfuehrung.

Die Hauptprobleme sind:

1. Zu viele gleich laute Informationen auf der ersten Surface.
2. Zu viele interne Begriffe statt handlungsorientierter Sprache.
3. Zu viel Konfigurationsflaeche fuer Standardnutzer.
4. Zu wenig sichtbare Uebersetzung von Confidence und Forecast in echte Aktion.
5. Zu wenig sofort sichtbare Differenzierung gegenueber generischen
   SMC-/ICT-Skripten.

## Produktziel

Ein anspruchsvoller Nutzer soll innerhalb von 3 bis 5 Sekunden verstehen:

- was die aktuelle Hauptaussage ist,
- ob er handeln, warten, vermeiden oder Risiko reduzieren soll,
- warum das System zu dieser Aussage kommt,
- welches Hauptrisiko oder welcher Hauptblocker aktiv ist.

Die Default-Surface soll deshalb zuerst Entscheidungen kommunizieren und erst
danach Diagnose.

## Zielgruppe

### Kernzielgruppe

- fortgeschrittene Retail-Trader
- solo operierende intraday- und swing-orientierte Nutzer
- Nutzer, die strukturierte Entscheidungshilfe wollen, aber kein Pine-Labor
  bedienen wollen

### Sekundaere Zielgruppe

- Power-User, die Tuning, Diagnose und Audit brauchen
- bestehende Nutzer mit hoher Systemkenntnis

### Nicht-Zielgruppe fuer die Default-Surface

- Nutzer, die jeden internen Gate-Baustein permanent sehen wollen
- Research-Terminal-Nutzer innerhalb des Pine-Charts
- Nutzer, die vollstaendige Black-Box-Automation ohne Kontext wollen

## Erfolgskriterien

| Bereich | Ziel |
| --- | --- |
| Erste Erfassbarkeit | Hauptaktion in <= 5 Sekunden erkennbar |
| Setup-Friction | Default-Setup in <= 60 Sekunden konfigurierbar |
| Input-Oberflaeche | <= 10 direkt sichtbare Standard-Inputs |
| Hero-Surface | <= 6 sichtbare Kernzeilen im Default |
| Action Clarity | Pro Bar maximal 1 primaere Handlungsaufforderung |
| Trust UX | Degraded/Warmup/Thin immer explizit sichtbar |
| Visual Load | Historische Debug-/Marker-Lage im Default klar reduziert |

## Produktprinzipien

1. Decision-first vor Diagnose-first.
2. Lite ist die Referenz-Surface, Pro ist optional.
3. Jede sichtbare Kennzahl muss eine Entscheidungsfunktion haben.
4. Unsicherheit wird explizit gezeigt, nicht versteckt.
5. Gute Defaults sind wichtiger als maximale Schalterfreiheit.
6. Der Nutzer soll nicht zwischen mehreren gleich wichtigen Tafeln waehlen
   muessen.

## Nicht im Scope

- neue Signal-Engine-Familien
- neue Forecast-Targets
- neue Datenprovider
- neue separate Lite-Logik neben der aktiven Engine
- Vollumbau des Research- oder Streamlit-Terminals

## Prioritaeten / Workstreams

### P1 - Hero Surface

Eine kompakte, handlungsorientierte Default-Surface ersetzt den derzeitigen
Diagnose-First-Eindruck.

### P1 - Settings Simplification

Die Konfigurationsflaeche wird auf Presets, Risiko, HTF-Fuehrung und Alerts
reduziert. Expertenoptionen bleiben versteckt.

### P1 - Language Cleanup

Interne Begriffe werden auf der Default-Surface in Nutzer- und
Entscheidungssprache uebersetzt.

### P2 - Trust and Evidence UX

Confidence, Forecast, Warmup und Datenqualitaet werden als belastbare
Vertrauenslage statt als reine Zahlencollage gezeigt.

### P2 - Lite / Pro Separation

Die tiefe Diagnose bleibt verfuegbar, aber nicht als Standardoberflaeche.

## Screens

## Screen 1 - Lite Operator Surface

### Zweck

Die Lite Operator Surface ist die Standardansicht fuer die aktive Nutzung.
Sie beantwortet nur vier Fragen:

1. Was soll ich jetzt tun?
2. In welche Richtung?
3. Warum?
4. Was ist das Hauptrisiko?

### Sichtbare Elemente

- Hero Card oben rechts oder oben links
- aktive Zone auf dem Chart
- Trigger / Invalidation nur wenn Setup mindestens `READY` ist
- maximal ein primaeres Entry-/Exit-Label pro Bar
- optional kompakte Risk-Linie bei aktiver Position oder actionable State

### Versteckte oder reduzierte Elemente im Default

- tiefe Diagnose-Tabellen
- historische Debug-Labels
- volle OB/FVG-Objektzaehlung
- tiefe Forecast-/Calibration-Daten
- technische Gate-Fachbegriffe

### Hero Card Struktur

| Zeile | Inhalt | Pflicht |
| --- | --- | --- |
| 1 | Action | Ja |
| 2 | Bias | Ja |
| 3 | Setup Quality | Ja |
| 4 | Why Now | Ja |
| 5 | Main Risk / Blocker | Ja |
| 6 | Risk Plan | Nur bei `READY`, `ENTER`, `MANAGE` |

### Beispieltexte

- `WAIT` - `Zone active, but reclaim not confirmed`
- `PREPARE LONG` - `Bullish reclaim forming`
- `READY LONG` - `Quality and context aligned`
- `ENTER LONG` - `Trigger active, risk defined`
- `REDUCE RISK` - `Context weakening`
- `AVOID` - `Conflicting context`
- `BLOCKED` - `High event risk`

## Screen 2 - Decision Detail Surface

### Zweck der Detail-Surface

Diese Surface erklaert die Hero-Entscheidung, ohne direkt in Pro-Diagnose zu
kippen.

### Sichtbare Bloecke

- Structure
- Session / Market Context
- Event / Data Quality
- Pressure / Momentum
- Why / Why Not Summary

### Detail-Regeln

- maximal 5 Diagnosezeilen in Lite-Detail
- keine internen Pack- oder BUS-Namen
- jede Zeile endet in einem klaren Verdict: `supports`, `mixed`, `blocks`

### Beispielzeilen

- `Structure: supports long`
- `Session: mixed`
- `Event Risk: clear`
- `Data Quality: thin`
- `Short-term Pressure: against long`

## Screen 3 - Settings Surface

### Zweck der Settings-Surface

Die Settings Surface soll Standardnutzer fuehren statt sie in Tuning-Logik zu
werfen.

### Sichtbare Lite-Inputs

- User Preset
- Signal Mode
- Risk Profile
- HTF Mode
- Alerts On/Off
- Visual Mode (`Lite` / `Pro`)

### Versteckte Advanced-Inputs

- LTF sampling guardrails
- detailed profile tuning
- per-stage accel / SD / DDVI / stretch gates
- fallback and calibration internals
- deep debug switches

### Produktregel

Ohne Aktivierung von `Advanced Settings` darf der Nutzer keine Gate-Engine
sehen, sondern nur Produktentscheidungen.

## Screen 4 - Pro Diagnostics Surface

### Zweck der Pro-Surface

Pro Diagnostics bleibt die Audit- und Tuning-Surface fuer Power-User.

### Pro-Regeln

- nicht Standardansicht
- getrennt von der Hero-Surface
- darf interne Begriffe behalten, wenn sie im Guide dokumentiert sind
- darf bestehende Dashboard-Tiefe nutzen, aber nicht die Lite-Surface
  kontaminieren

### Erwartete Inhalte

- aktuelle SMC-Dashboard-Diagnosezeilen
- Forecast- und Calibration-Details
- LTF- und Microstructure-Diagnose
- tiefe Risk-/Reason-Codes

## Zustandsmodell

Die Produktoberflaeche nutzt ein explizites Aktionsmodell statt nur vieler
Teilzustande.

| Product State | Bedeutung | Nutzeraktion |
| --- | --- | --- |
| `WAIT` | Kein sauberes Setup oder Zone ohne Bestaetigung | beobachten |
| `PREPARE LONG` / `PREPARE SHORT` | Fruehes Setup baut sich auf | aufmerksam werden |
| `READY LONG` / `READY SHORT` | Setup ist reif, Trigger nah | Einstiegsplan vorbereiten |
| `ENTER LONG` / `ENTER SHORT` | Trigger aktiv, Risiko definiert | handeln |
| `MANAGE LONG` / `MANAGE SHORT` | Position aktiv | Plan managen |
| `REDUCE RISK` | Setup oder Position verschlechtert sich | Risiko reduzieren |
| `AVOID` | Kontext widerspricht der Idee | nicht handeln |
| `BLOCKED` | harter Blocker aktiv | komplett fernbleiben |

## Vertrauensstufen

Die reine Confidence-Zahl bleibt optional. Die primare Darstellung nutzt vier
Vertrauensstufen.

| Tier | Bedeutung | Anzeige |
| --- | --- | --- |
| `Strong` | gute Evidenz, saubere Lage | gruen |
| `Usable` | nutzbar, aber nicht top | gelb-gruen |
| `Thin` | zu wenig Evidenz oder Konflikte | orange |
| `Provisional` | Warmup, degraded oder instabil | grau / orange |

## Sprachmodell

### Pflichtregel

Die Lite-Surface nutzt Handlungssprache. Interne Architekturbegriffe bleiben
in Pro oder in Guides.

### Label-Mapping

| Aktuell / technisch | Neu / nutzerseitig |
| --- | --- |
| `MinTrust` | `Trade Threshold` |
| `LastSig` | `Last Action` |
| `Pred(N)` | `Stable Forecast` |
| `Pred(1)` | `Early Forecast` |
| `LTF Delta` | `Short-term Pressure` |
| `Micro Profile` | `Market Profile` |
| `Entry Best` | `High-Quality Entry` |
| `Entry Strict` | `Strict Entry` |
| `Quality Clean` | `Clean Context` |
| `Vola Regime` | `Volatility Regime` |

### Copy-Regeln

- keine Acronym-Ketten auf Lite
- kein `n/a`, wenn stattdessen `No evidence yet` moeglich ist
- keine exakten Prozentzahlen als primaere Hauptaussage
- `Why Now` und `Main Risk` muessen in normalem Englisch lesbar sein

## UI-Textbibliothek

### Hero Action Labels

- `WAIT`
- `PREPARE LONG`
- `PREPARE SHORT`
- `READY LONG`
- `READY SHORT`
- `ENTER LONG`
- `ENTER SHORT`
- `REDUCE RISK`
- `AVOID`
- `BLOCKED`

### Why Now Textbausteine

- `Bullish reclaim inside active zone`
- `Bearish reclaim inside active zone`
- `HTF and trigger aligned`
- `Setup quality improved this bar`
- `Early pressure turned in your favor`

### Main Risk Textbausteine

- `Event risk still elevated`
- `Short-term pressure still against the trade`
- `Data quality is thin`
- `Forecast still in warmup`
- `Volatility too unstable`

### Alert Titles

- `SMC READY LONG`
- `SMC READY SHORT`
- `SMC ENTER LONG`
- `SMC ENTER SHORT`
- `SMC REDUCE RISK`
- `SMC AVOID`
- `SMC BLOCKED`

## Funktionale Anforderungen

### FR-1 Primary Action

Die Lite-Surface zeigt immer genau eine primaere Handlungsaufforderung.

### FR-2 Hero Surface

Die Lite-Hero-Card darf standardmaessig hoechstens 6 Zeilen enthalten.

### FR-3 Risk Visibility

Trigger, Invalidation und Risk Plan erscheinen nur bei actionable States oder
aktiver Position.

### FR-4 Explicit Uncertainty

Warmup, thin evidence, missing volume oder degraded mode muessen explizit
sichtbar sein.

### FR-5 Lite / Pro Separation

Tiefe Diagnose darf nicht als Pflichtteil der Default-Oberflaeche erscheinen.

### FR-6 Settings Simplification

Standardnutzer sehen nur preset-basierte Inputs. Advanced-Gates bleiben
versteckt.

### FR-7 Terminology Cleanup

Alle Top-Surface-Begriffe muessen ohne externe Doku verstehbar sein.

### FR-8 Visual Budget

Historische Labels und tiefe Overlays muessen im Default reduziert oder
gedeckelt sein.

### FR-9 Alert Alignment

Alert-Namen und Alert-Texte muessen dieselbe Sprache und denselben State wie
die Hero-Surface verwenden.

## Engineering Mapping

| Artefakt | Rolle im PRD |
| --- | --- |
| `SMC_Core_Engine.pine` | Referenz fuer Lite-Operator-Surface und State-Ableitung |
| `SMC_Dashboard.pine` | Compact Detail und Pro Diagnostics |
| `SMC_Long_Strategy.pine` | ausfuehrbarer Long-Wrapper auf Basis des Core-BUS |
| `docs/SMC_Dashboard_Long_Dip_Guide_DE.md` | Nutzererklaerung und Terminologie |
| `docs/TRADINGVIEW_STRATEGY_GUIDE.md` | Strategie-Setup, Binding und Backtest-Kontext |

## Delivery Phasen

### Phase 1 - Hero + Copy

- neue Hero-Surface
- neues Zustandsmodell
- neue Lite-Terminologie

### Phase 2 - Settings Cut

- visible Lite-Inputs reduzieren
- Advanced Settings kapseln
- Presets haerten

### Phase 3 - Trust / Evidence UX

- Confidence-Tiers
- Warmup / Thin / Degraded Signale
- Forecast-Sprache vereinfachen

### Phase 4 - Pro Separation

- tiefe Diagnose konsequent in Pro schieben
- Lite-/Pro-Doku angleichen

## Acceptance Criteria

1. Ein neuer Nutzer kann die Default-Surface ohne Guide lesen und die
   Hauptaktion korrekt benennen.
2. Auf der Lite-Surface ist kein interner BUS-, Pack- oder Reason-Code mehr
   sichtbar.
3. `WAIT`, `AVOID` und `BLOCKED` sind klar von `READY` und `ENTER` getrennt.
4. Datenqualitaet und Unsicherheit werden nicht nur numerisch, sondern auch
   verbal kommuniziert.
5. Die Default-Settings wirken wie ein Produkt, nicht wie ein Labor.

## Offene Fragen

1. Welche Surface wird als Flaggschiff priorisiert: `SMC_Core_Engine.pine` oder
   `SMC_Long_Strategy.pine`?
2. Soll `SHORT` in der Lite-Surface von Anfang an voll gleichwertig sein oder
   bleibt Long-Dip-first die erste Produktgrenze?
3. Soll Pro Diagnostics als separates Companion-Skript publiziert werden oder
   als Modus innerhalb derselben Surface bleiben?
4. Welche Begriffe muessen bewusst Englisch bleiben, weil sie im TradingView-
   Marktstandard verankert sind?

## Executive Product Rule

Wenn eine sichtbare Information dem Nutzer nicht hilft, schneller zwischen
`WAIT`, `PREPARE`, `READY`, `ENTER`, `REDUCE RISK`, `AVOID` oder `BLOCKED` zu
unterscheiden, gehoert sie nicht auf die Lite-Default-Surface.

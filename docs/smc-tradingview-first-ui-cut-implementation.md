# SMC / SkippALGO First UI Cut Implementation Preparation

## Status

Implemented

## Zweck

Dieses Dokument bereitet die erste konkrete UI-Umsetzung fuer die drei
TradingView-Surfaces vor:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SkippALGO.pine`

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
2. Sichtbare UX zuerst, Engine-Verhalten nur dort anfassen, wo Sprache und
   Lifecycle gekoppelt sind.
3. Lite muss aus der bestehenden Produktrealitaet heraus gebaut werden.
4. Pro darf bestehen bleiben, aber nicht mehr die Default-Lesart vorgeben.

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
- Trust Tiers:
  - `Strong`
  - `Usable`
  - `Thin`
  - `Provisional`

### Shared Copy Contract

- Zeile 1: `Action`
- Zeile 2: `Why now`
- Zeile 3: `Main risk`
- Sekundaer: `Bias`, `Trade Threshold`, `Position`, `Last Action`, `Evidence`

### Shared Engineering Helpers To Introduce

Wenn moeglich als kleine, klar lokalisierte Helper und nicht als verteilte
Inline-Logik:

- `resolve_product_state(...)`
- `resolve_trust_tier(...)`
- `compose_why_now_text(...)`
- `compose_main_risk_text(...)`
- `compose_trade_threshold_text(...)`

## Current Code Anchor Map

| Surface | Aktuelle Anker | Bedeutung fuer den ersten UI-Cut |
| --- | --- | --- |
| `SMC_Core_Engine.pine` | `User Preset`, `compact_mode`, `show_dashboard`, `enable_dynamic_alerts` | Hier sitzt die sichtbare Lite- und Alert-Einstiegslogik. |
| `SMC_Core_Engine.pine` | Mini Health Badge am letzten Balken | Kann in die neue Hero-Leselogik integriert werden. |
| `SMC_Core_Engine.pine` | Dynamic alert builders und Lifecycle-Alerts | Muss auf Product-State-Sprache umgestellt werden. |
| `SMC_Dashboard.pine` | BUS-Inputs am Dateikopf | Der Default-Screen ist aktuell operator-lastig gebunden. |
| `SMC_Dashboard.pine` | 58-Zeilen-Tabelle mit Hero- und Diagnostic-Blocks | Hier erfolgt der eigentliche Compact-vs-Pro-Split. |
| `SkippALGO.pine` | breite Input-Flaeche ab `Configuration`, `Signal engine`, Forecast, Risk, Labels | Hier sitzt der notwendige Lite-Input-Cut. |
| `SkippALGO.pine` | `confidence`, `pos`, `lastSig` | Kernbausteine fuer den Decision Header. |
| `SkippALGO.pine` | Label- und Alert-Bereich | Muss sprachlich an den neuen Header gekoppelt werden. |

## Important Current-State Findings

### SMC Core

- Es gibt bereits `compact_mode`, aber noch keine vollwertige Hero-Card.
- `show_dashboard` und der Health Badge erzeugen heute eher eine technische als
  produktartige Leseflaeche.
- Die Dynamic-Alert-Pipeline ist reichhaltig genug, um auf die neue
  Product-State-Sprache umgestellt zu werden.

### SMC Dashboard

- Das Dashboard rendert heute standardmaessig eine 58-Zeilen-Tabelle.
- Hero, Hard Gates, Quality, Modules und Engine Diagnostics stehen alle auf
  derselben Default-Ebene.
- Die BUS-Bindung ist funktional, aber fuer normale Public-Nutzer keine
  produktgerechte Default-Erfahrung.

### SkippALGO

- SkippALGO besitzt im aktuellen Stand keine dedizierte Table/HUD-Surface fuer
  einen Decision Header.
- Die Nutzersignale sitzen heute vor allem in Labels, Alerts und Rohvariablen
  wie `confidence` und `lastSig`.
- Die erste UI-Umsetzung fuer SkippALGO bedeutet daher nicht nur Umbau,
  sondern auch Einfuehrung einer neuen sichtbaren HUD-Lage.

## Surface 1 - `SMC_Core_Engine.pine`

### Core First-Cut Zielbild

Eine klare chart-native Lite-Surface, die im Compact-Modus nicht nur Dinge
versteckt, sondern eine produktartige Hauptbotschaft zeigt.

### Core Erste konkrete UI-Aenderungen

1. `compact_mode` inhaltlich zu einem echten Lite-Modus machen.
2. Hero-Card mit maximal 5 sichtbaren Kernzeilen einfuehren.
3. Health Badge in `Quality` oder `Why now` integrieren statt als paralleles
   Zusatzsignal belassen.
4. Risk-Level nur dann zeigen, wenn Zustand mindestens `READY` ist.
5. Dynamic-Alert-Texte an Product States statt an interne Lifecycle-Namen
   koppeln.

### Core Geplante Feldabbildung

| Hero-Zeile | Datenquelle fuer den ersten Cut |
| --- | --- |
| `Action` | bestehende Long-/Lifecycle-Zustaende |
| `Bias` | Trend- und Bias-Ausrichtung |
| `Quality` | Signal-Quality-Tier plus Freshness |
| `Why now` | Lean-Pack / Reclaim / Trigger-Kontext |
| `Main risk` | Event Risk, thin data, blocker oder weak pressure |

### Core Edit-Reihenfolge

1. Helper fuer Product State und Trust Tier einfuehren.
2. Compact-Mode-Renderpfad von reinem Unterdruecken zu Hero-Card-Rendern
   erweitern.
3. Health Badge und Risk-Level daran andocken.
4. Dynamic-Alert-Titel und Message Builder angleichen.

### Core Nicht Im Ersten Cut

- Vollumbau aller Pro- oder Debug-Overlays.
- Neuer Datenbus.
- Neue Forecast- oder Signalstufen.

### Core Validation

1. Lite zeigt nur eine primaere Action.
2. `WAIT` zeigt keine vollen Risk-Linien.
3. `READY` und `ENTER` zeigen Trigger und Invalidation klar.
4. Dynamic Alerts sprechen dieselbe Sprache wie die Hero-Card.

## Surface 2 - `SMC_Dashboard.pine`

### Dashboard First-Cut Zielbild

Ein Default-Dashboard, das die Hero-Entscheidung erklaert, waehrend Pro
Diagnostics als bewusst tiefer Modus verfuegbar bleibt.

### Dashboard Erste konkrete UI-Aenderungen

1. Einen sichtbaren Surface-Mode einfuehren:
   `Compact Detail` versus `Pro Diagnostics`.
2. Die aktuelle 58-Zeilen-Tabelle fuer den Default auf 6 bis 8 Kernzeilen
   reduzieren.
3. Die aktuelle Hero-Zone und die Diagnostic-Sektionen entkoppeln.
4. BUS-/Diag-/Pack-Terminologie aus dem Compact-Default entfernen.
5. `show_risk_lines` an actionable States koppeln oder mindestens visuell
   nachrangig behandeln.

### Dashboard Geplante Default-Zeilen

1. `Structure`
2. `Session`
3. `Event Risk`
4. `Data Quality`
5. `Short-term Pressure`
6. `Risk Plan` nur bei actionable State

### Dashboard Geplante Pro-Zeilen

Die bestehenden Diagnostic-Sektionen bleiben erhalten:

- Hard Gates
- Quality Diagnostic
- Modules Diagnostic
- Engine Diagnostic

### Dashboard Edit-Reihenfolge

1. Mode-Input und Default-Renderzweig einfuehren.
2. Bestehende Row-Decodes wiederverwenden, aber in eine kompakte
   Nutzergruppierung verschieben.
3. Pro-Renderpfad auf den heutigen Volltable-Stand legen.
4. Operator-only BUS-Bindung im Headertext und in der Doku klar markieren.

### Dashboard Nicht Im Ersten Cut

- Vollstaendige interne Umbenennung aller BUS-Felder.
- Automatische BUS-Konfiguration.

### Dashboard Validation

1. Default-Detail hat maximal 8 Zeilen.
2. Pro Diagnostics bleibt funktional erhalten.
3. Compact Default enthaelt keine sichtbaren BUS- oder Debug-Begriffe.

## Surface 3 - `SkippALGO.pine`

### SkippALGO First-Cut Zielbild

SkippALGO bekommt erstmals eine echte Decision-HUD mit Header, Outlook und
Forecast als zusammenhaengende Lite-Surface.

### SkippALGO Erste konkrete UI-Aenderungen

1. Neue Decision Header HUD einfuehren.
2. Outlook als kompakte Regimehilfe bauen.
3. Forecast als nutzerlesbare Prognosehilfe bauen.
4. Labels und Alerts sprachlich an den neuen Product State koppeln.
5. Die sichtbare Input-Flaeche auf Produktsteuerung reduzieren.

### SkippALGO Decision Header Inhalte

- `Action`
- `Trade Threshold`
- `Position`
- `Last Action`
- `Why now`
- `Main risk`
- sekundaer: `Trust`

### SkippALGO Outlook Panel Inhalte

- `TF`
- `Bias`
- `Strength`
- `State note`

### SkippALGO Forecast Panel Inhalte

- `TF`
- `Stable Forecast`
- `Early Forecast`
- `Evidence`
- `Risk Hint`

### SkippALGO Konkrete technische Vorbereitung

1. Aus `confidence`, `lastSig`, `pos`, MTF-Score und Forecast-Arrays einen
   neuen UI-State ableiten.
2. Eine neue Table- oder HUD-Lage einfuehren, weil heute keine dedizierte
   Decision-HUD existiert.
3. Bestehende BUY/SHORT/REV-/PRE-Labels nicht abrupt loeschen, sondern in einen
   klaren Kompatibilitaetspfad ueberfuehren.
4. Neue produktseitige Alerttitel bevorzugen; Legacy-Titel nur mit bewusstem
   Kompatibilitaetspfad weiterfuehren.

### SkippALGO Edit-Reihenfolge

1. Helper fuer Product State, Trust Tier, Why now und Main risk einfuehren.
2. Neue HUD-Struktur mit Header, Outlook und Forecast bauen.
3. Input-Sichtbarkeit auf Lite versus Advanced schneiden.
4. Labels und Alertconditions an die neue Produktsprache anpassen.

### SkippALGO Nicht Im Ersten Cut

- Forecast-Modell oder Kalibration neu bauen.
- Alle Legacy-Alerts sofort entfernen.
- Tiefenumbau der Handelslogik.

### SkippALGO Validation

1. Header ist in 5 Sekunden lesbar.
2. Outlook wirkt wie State-Lesehilfe, nicht wie Debug-Gitter.
3. Forecast zeigt Evidenz und Risiko klarer als rohe Modellbegriffe.
4. Labels, Header und Alerts widersprechen sich nicht.

## Cross-Surface Edit Order

1. Shared Helper und Produktsprache festziehen.
2. SMC Core Hero Surface bauen.
3. Dashboard Compact Detail Default abspalten.
4. SkippALGO HUD einziehen.
5. Label- und Alert-Parity auf Core und SkippALGO herstellen.
6. Input-Cut und Doku-Finalisierung abschliessen.

## Manual Validation Checklist

1. Lite-Surfaces zeigen maximal eine primaere Action.
2. Kein Default-Screen wirkt wie ein Diagnoseboard.
3. `Thin`, `Provisional`, `Event risk`, `No evidence yet` sind explizit lesbar.
4. Pro bleibt tiefer als Lite, aber nicht mehr die Default-Lesart.
5. Alerts, Labels, Header und Guides sprechen dieselbe Sprache.

## Executive Implementation Rule

Die erste UI-Umsetzung ist dann gut vorbereitet, wenn ein Entwickler ohne
Produkt-Raten sofort weiss, welche sichtbaren Teile zuerst gebaut werden,
welche Code-Anker dafuer relevant sind und was bewusst noch nicht in den ersten
Cut gehoert.

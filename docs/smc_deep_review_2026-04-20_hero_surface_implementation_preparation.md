# SMC Deep Review 2026-04-20: Hero Surface Implementation Preparation

Stand: 2026-04-20
Status: aktiv
Fokus: PR-nahe Vorbereitungsdoku fuer die Decision-First-Hero-Surface

## Zweck

Dieses Dokument uebersetzt den Hero-Surface-Plan in einen konkreten,
dateibezogenen Umsetzungsrahmen.

Es ist kein abstrakter Zieltext. Es benennt die aktuellen Code-Anker, die
wahrscheinlichen Edit-Bloecke, die Reihenfolge der Aenderungen und die minimale
Validation fuer einen ersten PR-nahen Hero-Surface-Cut.

## Source Documents

- `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`
- `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`
- `docs/smc-tradingview-first-ui-cut-implementation.md`
- `docs/smc-tradingview-decision-first-prd.md`

## Working Rules

1. Keine neue Schattenlogik zwischen Generator, Engine und Dashboard.
2. Dashboard-Zusammenbau bleibt top-level und nicht als monolithischer Render-
   Wrapper.
3. Mobile spiegelt dieselbe Produktsemantik; Unterschiede liegen nur in Dichte
   und Layout.
4. Operator-only BUS-Bindings bleiben versteckt und werden nicht Teil der
   Hero-Lesestufe.
5. TradingView-Live-Validation bleibt auf compile, add-to-chart und runtime
   fokussiert.

## Shared Implementation Decisions

### Hero Pflichtsignale

Die erste Lesestufe soll nur diese Felder tragen:

- market mode
- primary bias
- trust and freshness
- setup quality
- why now
- main risk
- action

### Generator-vor-Dashboard-Regel

Regime, Trade State, Trust, Freshness, Quality und Action duerfen nicht im
Dashboard fachlich neu erfunden werden. Wo moeglich werden sie generator- oder
export-seitig festgelegt und die Surface konsumiert sie nur.

### Surface Split

- Desktop Default: Hero plus kompakte zweite Lesestufe
- Desktop Audit: bewusst tiefer, aber auf derselben Produktsemantik
- Mobile: derselbe Hero-State in 4 bis 5 kompakten Zellen

## Current Code Anchor Map

| Datei | Aktuelle Anker | Bedeutung fuer den Hero-PR |
| --- | --- | --- |
| `SMC_Dashboard.pine` | `surface_mode`, `compact_dashboard`, versteckte BUS-Inputs am Dateikopf | Default-Surface, Operator-Trennung und Hero-Einstieg leben hier zusammen. |
| `SMC_Dashboard.pine` | `table.new(..., 2, 74, ...)` plus Renderzweige fuer `Focus`, `Explain`, `Decision Brief`, `Audit View` | existierender Renderbaum muss auf hero-first Hierarchie umgebaut werden. |
| `SMC_Dashboard.pine` | aktuelle `Decision Brief`-Zeilen `Market`, `Structure`, `Session / Market`, `Event Risk`, `Zone Priority`, `Trust / Data`, `Short-term Pressure`, `Risk Plan` | hier sitzt der erste realistische Desktop-Cut. |
| `SMC_Mobile_Dashboard.pine` | 2x4-Mobiltabelle mit `Action`, `Levels`, `Market`, `Quality` | Mobile ist schon kompakt, aber noch zu knapp fuer Why now und Trust. |
| `pine_input_surface.py` | `parse_inputs`, `cmd_regroup`, Gruppen- und `display.none`-Injektion | Hero-Inputs koennen nur sauber reduziert werden, wenn Gruppen und Sichtbarkeit bewusst gesetzt werden. |
| `scripts/generate_smc_micro_profiles.py` | Exportblock fuer `MARKET_REGIME`, `TRADE_STATE`, `HIGH_IMPACT_MACRO_TODAY`, `VOLATILITY_REGIME`, `ENSEMBLE_QUALITY_TIER`, `ZONE_PRIORITY_*` | bestehende Hero-nahe Felder werden bereits exportiert; neue Hero-Contract-Felder gehoeren in denselben Bereich. |
| `scripts/generate_smc_micro_base_from_databento.py` | Aufbau von `calendar`, `layering`, `volatility_regime`, `ensemble_quality`, `zone_priority` | hier entstehen die meisten Hero-relevanten Vorstufen. |
| `scripts/run_smc_release_gates.py` | harte Gate-Klassifikation und TV-Drift-Trennung | Hero-Regressionen muessen spaeter als sichtbare Produktfaelle hier andocken. |
| `scripts/run_smc_post_release_validation.py` | normalisierte Post-Release-Validation-Huelle | hier kann spaeter sichtbare Hero-State-Validation berichtbar werden. |

## Important Current-State Findings

### Desktop Dashboard

- `Focus` ist bereits eine 3-Zeilen-Variante, aber noch zu stark als Traffic-
  Light und zu schwach als begruendete Hero-Surface ausgelegt.
- `Decision Brief` ist der beste Einstiegspunkt fuer den ersten Hero-Cut, weil
  dort bereits Market, Structure, Trust und Risk Plan nebeneinander liegen.
- `Audit View` besitzt die notwendige Tiefe und sollte nicht entfernt, sondern
  klarer von der Hero-Lesestufe getrennt werden.

### Mobile Dashboard

- Die mobile Tabelle ist semantisch nah am Ziel, aber es fehlen Why now,
  Main risk und sichtbare Trust/Freshness-Degradierung.
- Mobile darf keine eigene Produktlogik entwickeln; es muss denselben Hero-
  Contract lesen wie Desktop.

### Generator Layer

- `MARKET_REGIME`, `TRADE_STATE`, `VOLATILITY_REGIME`,
  `ENSEMBLE_QUALITY_TIER` und `ZONE_PRIORITY_*` werden bereits exportiert.
- Trust und Freshness sind im sichtbaren Surface noch nicht als klare,
  begrenzte Produktzustandsklasse verdichtet.
- Das spricht fuer einen kleinen Hero-State-Contract im Generator statt fuer
  neue Dashboard-Schattenlogik.

## File-by-File Implementation Plan

## File 1 - `scripts/generate_smc_micro_base_from_databento.py`

### Ziel dieses Edits

Die Vorstufen fuer Trust, Freshness und Action-Degradierung an einer Stelle
verdichten, bevor das Dashboard sie konsumiert.

### Konkrete Aenderungen

1. Die bestehenden `layering`, `volatility_regime`, `calendar`,
   `ensemble_quality` und `zone_priority`-Bloecke um einen expliziten
   Hero-State-Baustein ergaenzen.
2. Trust/Freshness auf wenige sichtbare Produktklassen reduzieren,
   beispielsweise `healthy`, `warmup`, `degraded`, `stale`, `unavailable`.
3. Einen klaren Action-Vorschlag oder Action-Guard vorbereiten, der nicht im
   Dashboard neu errechnet werden muss.

### Aktuelle Code-Anker

- Aufbau von `calendar`-Feldern
- Aufbau von `layering` inklusive `trade_state`
- Aufbau von `volatility_regime`
- Aufbau von `ensemble_quality`
- Aufbau von `zone_priority`

### PR-Regel

Nur Hero-nahe Verdichtung einziehen, aber keine neue zweite Business-Logik
parallel zu bestehenden Enrichment-Bloecken aufbauen.

## File 2 - `scripts/generate_smc_micro_profiles.py`

### Ziel dieses Edits

Den Hero-State ueber denselben Exportpfad nach Pine bringen, ueber den heute
schon `MARKET_REGIME`, `TRADE_STATE`, `VOLATILITY_REGIME` und
`ENSEMBLE_QUALITY_TIER` exportiert werden.

### Konkrete Aenderungen

1. Im Exportblock nach Regime, Calendar, Layering, Volatility und Ensemble die
   zusaetzlichen Hero-Felder aufnehmen.
2. Neue Felder so benennen, dass Desktop und Mobile sie ohne Transformations-
   Schattenlogik lesen koennen.
3. Die Feldliste in der Library-Dokumentation am Dateikopf mit den neuen Hero-
   Konstanten aktualisieren.

### Aktuelle Code-Anker

- Exportblock fuer `MARKET_REGIME`
- Exportblock fuer `HIGH_IMPACT_MACRO_TODAY` und `MACRO_EVENT_*`
- Exportblock fuer `TRADE_STATE`
- Exportblock fuer `VOLATILITY_REGIME*`
- Exportblock fuer `ENSEMBLE_QUALITY_*`
- Exportblock fuer `ZONE_PRIORITY_*`

### PR-Regel

Keine Feldexplosion. Nur die Hero-Pflichtsignale exportieren, die in der
Surface wirklich sichtbar werden sollen.

## File 3 - `SMC_Dashboard.pine`

### Ziel dieses Edits

Die aktuelle `Decision Brief`-Default-Oberflaeche in eine echte Hero-Surface
mit klarer Leserichtung umbauen.

### Konkrete Aenderungen

1. `Decision Brief` als primaeren Hero-Modus behandeln und die Zeilen in drei
   Bloecke umordnen:
   - Market Mode Header
   - Setup Quality Card
   - Action Card
2. `Focus` entweder auf denselben Hero-Contract spiegeln oder als minimalen
   Teaser unter denselben Produktbegriffen halten.
3. `Audit View` in der Tiefe erhalten, aber sprachlich an Hero-Zustaende und
   Hero-Begriffe angleichen.
4. Trust/Freshness und Degradierungsgruende sichtbar in denselben Kopf- und
   Action-Bereich integrieren.

### Aktuelle Code-Anker

- Dateikopf mit `surface_mode`, `show_table`, `compact_dashboard`
- versteckte BUS-Input-Gruppen fuer Lifecycle, Diagnostic Rows und Lean Surface
- `var table smc_dashboard = table.new(position.bottom_right, 2, 74, ...)`
- Renderzweig `if surface_mode == "Focus"`
- Renderzweig `else if surface_mode == "Explain"`
- Renderzweig `else if compact_dashboard`
- Renderzweig `else if surface_mode == "Decision Brief"`
- `Audit View`-Start mit `Action` und `Why now`

### PR-Regel

Keine grosse UDF-Renderklammer bauen. Die existierende top-level Renderstruktur
bleibt erhalten; nur die sichtbare Hierarchie und der Zeilenhaushalt werden
umgebaut.

## File 4 - `SMC_Mobile_Dashboard.pine`

### Ziel dieses Edits

Die mobile Surface auf denselben Hero-State wie Desktop spiegeln.

### Konkrete Aenderungen

1. Die bestehende 2x4-Tabelle in einen kompakten Hero-Block ueberfuehren, der
   mindestens Action, Market Mode, Trust/Freshness und Setup Quality traegt.
2. Falls Why now oder Main risk auf Mobile nicht voll sichtbar sein sollen,
   diese auf einen klaren verdichteten Text oder eine priorisierte Zusatzzeile
   reduzieren.
3. Die Fehlerlage bei fehlendem BUS-Schema unveraendert klar halten.

### Aktuelle Code-Anker

- Dateikopf mit `g_mobile_surface` und Operator-only BUS-Gruppe
- Dekodierung von `state_code` und `actionable`
- `context_text = mp.MARKET_REGIME + " · " + mp.TRADE_STATE`
- 2x4-Tabellenrender mit `Action`, `Levels`, `Market`, `Quality`

### PR-Regel

Mobile bleibt kompakt, aber semantisch nicht aermer als Desktop. Unterschied nur
in Layout und Dichte.

## File 5 - `pine_input_surface.py`

### Ziel dieses Edits

Die Hero-Nutzung konfigurierbar halten, ohne Operator-Komplexitaet in die
erste sichtbare Input-Stufe zu ziehen.

### Konkrete Aenderungen

1. Surface-relevante Inputs fuer Dashboard und Mobile explizit in eine kleine
   Produktgruppe ziehen.
2. Operator-only BUS-Bindings weiterhin ueber `display.none` oder getrennte
   Gruppen isolieren.
3. Eine nachvollziehbare Gruppierungsmap fuer Hero-Surface-relevante Inputs
   vorbereiten.

### Aktuelle Code-Anker

- `parse_inputs`
- `cmd_audit`
- `cmd_regroup`
- `_inject_group`
- `_inject_display_none`

### PR-Regel

Input-Reduktion ist kein Nebenprodukt. Sie gehoert explizit in denselben Cut,
damit die Hero-Surface nicht auf einer alten Labor-Inputflaeche landet.

## File 6 - `scripts/run_smc_release_gates.py`

### Ziel dieses Edits

Hero-relevante sichtbare Produktfaelle in die spaetere Gate- und Report-Sprache
vorbereiten.

### Konkrete Aenderungen

1. Evidence- und Validation-Reports um Hero-nahe Failure-Sprache vorbereiten.
2. Sichtbare Produktzustandsfaelle von externer TradingView-Drift getrennt
   halten.
3. Keine neue harte Validation bauen, bevor der Hero-State-Contract in den
   Exporten stabil ist.

### Aktuelle Code-Anker

- `_DATA_ABSENT_CODES`
- TV-Drift-Klassifikation ueber `_TV_EXTERNAL_DRIFT_CODES`
- `classify_tv_gate_failure`

## File 7 - `scripts/run_smc_post_release_validation.py`

### Ziel dieses Edits

Nach dem ersten Hero-Cut sichtbare Hero-Zustandsvalidierung berichtbar machen.

### Konkrete Aenderungen

1. Den bestehenden Normalisierungsreport um Hero-nahe Ergebnisfelder erweitern,
   sobald die readonly Validation diese liefern kann.
2. Hero-Surface-Fails als Produktzustand statt nur als technisches Target-Fail
   lesbar machen.

### Aktuelle Code-Anker

- `run_post_release_validation`
- Basisreport mit `overall_status`, `validated_target_count` und `failures`

## Cross-File Edit Order

1. `scripts/generate_smc_micro_base_from_databento.py`
2. `scripts/generate_smc_micro_profiles.py`
3. `SMC_Dashboard.pine`
4. `SMC_Mobile_Dashboard.pine`
5. `pine_input_surface.py`
6. `scripts/run_smc_release_gates.py`
7. `scripts/run_smc_post_release_validation.py`

## PR Slice Recommendation

### PR 1 - Hero State Contract

- Generator-Verdichtung in `scripts/generate_smc_micro_base_from_databento.py`
- Exporte in `scripts/generate_smc_micro_profiles.py`
- keine Surface-Umgestaltung ausser minimaler Lesbarkeitstests

### PR 2 - Desktop Hero Surface

- `SMC_Dashboard.pine`
- optional kleine Input-Surface-Anpassungen, wenn fuer Default-Hero zwingend

### PR 3 - Mobile Mirror Plus Input Cleanup

- `SMC_Mobile_Dashboard.pine`
- `pine_input_surface.py`

### PR 4 - Validation Hook-In

- `scripts/run_smc_release_gates.py`
- `scripts/run_smc_post_release_validation.py`

## Manual Validation Checklist

1. Desktop-Default zeigt zuerst Marktmodus, Qualitaet und Aktion.
2. Trust und Freshness sind sichtbar und nicht nur implizit in einem Sammelrow
   versteckt.
3. Eine degradierte Datenlage aendert die sichtbare Aktion nachvollziehbar.
4. Audit View widerspricht dem Hero-State nicht.
5. Mobile und Desktop lesen denselben Hero-State mit unterschiedlicher Dichte.
6. Operator-only BUS-Bindings bleiben aus der ersten sichtbaren Surface
   herausgenommen.

## Abschlussregel

Dieser Implementierungsplan ist erfolgreich umgesetzt, wenn ein erster PR die
Hero-Surface dateiuebergreifend in klarer Reihenfolge umsetzt, ohne neue
Schattenlogik aufzubauen oder die bestehende Release- und Validation-Kette zu
vernebeln.
# SMC Lite + Pro Product Cut

## Ziel

Dieses Dokument zieht die Produktgrenze fuer einen benutzerfreundlicheren
TradingView-Rollout, ohne die aktive Long-Dip-Engine logisch zu forkieren.
Die Kernidee ist einfach:

- Lite ist die normale Operator-Surface.
- Pro ist die Diagnose-, Tuning- und Automations-Surface.
- Beide laufen auf derselben aktiven Engine.

## Aktuelle Repo-Wahrheit

- `SMC_Core_Engine.pine` ist der einzige aktive Producer und bereits die
  eigentliche Single-Script-Operator-Surface.
- `SMC_Dashboard.pine` ist ein reiner BUS-Consumer fuer Diagnose und Erklaerung.
- `SMC_Long_Strategy.pine` ist ein duenner BUS-Consumer fuer ausfuehrbare
  Long-Entries.
- `long_user_preset` und `compact_mode` bleiben die sichtbaren Operator-Anker.

Die Lite/Pro-Trennung darf deshalb keine zweite Logikfamilie erzeugen. Sie ist
eine Produkt- und Surface-Grenze, keine neue Signal-Engine.

## Contract-Layer

### 1. Executable Core

Das ist der kleinste stabile Contract, der echte Orders und Backtests tragen
kann. Er wird heute bereits von `SMC_Long_Strategy.pine` verbraucht.

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS QualityScore`
- `BUS Trigger`
- `BUS Invalidation`

### 2. Lite Surface

Lite ergaenzt den Executable Core nur um die Signale, die eine Hero-Surface
ohne tiefe Diagnose ermoeglichen.

- `BUS ZoneActive`
- `BUS SourceKind`
- `BUS StateCode`
- `BUS TrendPack`
- `BUS LeanPackA`
- `BUS LeanPackB`

Zusammen mit dem Executable Core ergibt das den kanonischen Lite-Contract mit
14 Kanaelen.

### 3. Pro-Only Surface

Alles andere bleibt Pro-only. Das sind die Diagnose-, Audit- und Detailkanaele,
die fuer Endnutzer nicht verpflichtend sein sollten:

- `BUS MetaPack`
- `BUS EventRiskRow`
- `BUS QualityBoundsPack`
- `BUS ModulePackC`
- `BUS LongTriggersRow`
- `BUS RiskPlanRow`
- `BUS DebugFlagsRow`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

Hinzu kommen auf der aktiven Pro-Surface jetzt drei klar getrennte Lagen:

- direkte Diagnostic Rows fuer Gates und Quality:
  `BUS SessionGateRow`, `BUS MarketGateRow`, `BUS VolaGateRow`,
  `BUS MicroSessionGateRow`, `BUS MicroFreshRow`, `BUS VolumeDataRow`,
  `BUS QualityEnvRow`, `BUS QualityStrictRow`, `BUS CloseStrengthRow`,
  `BUS EmaSupportRow`, `BUS AdxRow`, `BUS RelVolRow`, `BUS VwapRow`,
  `BUS ContextQualityRow`, `BUS QualityCleanRow`, `BUS QualityScoreRow`,
  `BUS SdConfluenceRow`, `BUS SdOscRow`, `BUS VolRegimeRow`,
  `BUS VolSqueezeRow`, `BUS VolExpandRow`, `BUS DdviRow`, `BUS SwingRow`,
  `BUS ReadyGateRow`, `BUS StrictGateRow`,
  `BUS MicroModifierMask`
- direkte Detail-Channels fuer wiederhergestellte Monolith-Tiefe:
  `BUS ZoneObTop`, `BUS ZoneObBottom`, `BUS ZoneFvgTop`,
  `BUS ZoneFvgBottom`, `BUS SessionVwap`, `BUS AdxValue`,
  `BUS RelVolValue`, `BUS StretchZ`, `BUS StretchSupportMask`,
  `BUS LtfBullShare`, `BUS LtfBiasHint`, `BUS LtfVolumeDelta`,
  `BUS ObjectsCountPack`

Die frueheren Legacy-Compat-Exports (`BUS HardGatesPackA/B`,
`BUS QualityPackA/B`, `BUS EnginePack`) sind inzwischen aus dem Producer
entfernt und gehoeren nicht mehr zum aktiven Pro-Vertrag.

## Lite-Produktdefinition

Lite ist nicht "weniger Engine". Lite ist "weniger Setup-Friction".

Lite soll deshalb diese Regeln einhalten:

- Standardnutzer arbeiten primaer mit `SMC_Core_Engine.pine`.
- `long_user_preset` bleibt die primaere Bedienebene.
- `compact_mode` ist die normale Freigabe-Surface fuer geteilte oder solo
  genutzte Charts.
- Es gibt keine Pflicht, zusaetzlich Dashboard- oder Strategy-Skripte per
  `input.source()` zu verdrahten.
- Die Hero-Surface zeigt nur das, was man fuer Entscheidungen schnell lesen
  muss: Lifecycle, Direction/Bias, Signal Quality, Event Risk Light,
  Structure Light, OB/FVG Light, Session Light und Risk Levels.

Lite darf ausdruecklich nicht:

- die Score- oder Gate-Semantik von Pro veraendern,
- die UI-gekoppelten Diagnosepacks als Pflicht-Setup behandeln,
- Pro-Debug-Tiefe als normales Nutzerziel verkaufen.

## Pro-Produktdefinition

Pro ist die volle Split-Surface fuer Nutzer, die das System tunen, auditieren,
debuggen oder strategisch ausfuehren wollen.

Pro umfasst:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`
- den vollen 63-Kanal-BUS-Contract

Das aktive Dashboard nutzt derzeit den kompletten 63-Kanal-Producer-Vertrag.

Pro darf bewusst mehr Friction haben, wenn diese Friction echte Diagnose- oder
Automationsfaehigkeit liefert.

## Praktische Produktregel

Wenn ein Feld nur dazu dient, Dashboard-Zeilen oder Debug-Erklaerungen
aufzubauen, gehoert es nicht in Lite.

Wenn ein Feld eine Entscheidung auf der Operator-Surface sichtbar oder
ausfuehrbar macht, darf es in Lite bleiben.

## C9-Schnitt fuer Pro-only Packs

Nach dem Lite/Pro-Cut ist der naechste sinnvolle Cleanup-Schritt kein weiterer
Umbau des Lite-Contracts, sondern ein gezielter Pro-only-Schnitt.

### C9.1 Rebuild-Kandidaten

Diese aktiven UI-Transport-Kanaele sollten als naechste Boundary neu
geschnitten werden:

- `BUS EventRiskRow`
- `BUS VolExpandRow`
- `BUS DdviRow`
- `BUS SwingRow`
- `BUS ModulePackC`
- `BUS LongTriggersRow`
- `BUS RiskPlanRow`
- `BUS DebugFlagsRow`
- `BUS ReadyGateRow`
- `BUS StrictGateRow`
- `BUS MicroModifierMask`

`BUS ModulePackA` wurde bereits in direkte Rows fuer `BUS SdConfluenceRow`,
`BUS SdOscRow`, `BUS VolRegimeRow` und `BUS VolSqueezeRow` ueberfuehrt.
Der fruehere `ModulePackB`-Transport ist inzwischen retired. Vor dem Cut wurden
die sichtbaren `Session VWAP`-, `EMA Fast`- und `EMA Slow`-Overlays aus dem
`plot()`-Budget in line-basierte Overlays verschoben. Danach wurde
`BUS ModulePackB` durch `BUS VolExpandRow`, `BUS DdviRow`,
`BUS StretchSupportMask` und `BUS LtfBiasHint` ersetzt.

Die Engine liegt jetzt bei `63 / 64` Plots mit einem aktiven
`63`-Kanal-Pro-Vertrag. `Swing` und `Objects` wurden ueber `BUS SwingRow` und
`BUS ObjectsCountPack` aus `ModulePackC` herausgezogen; die lokale Ableitung
des `Long Debug`-Zustands hat zusaetzlich `BUS DebugStateRow` retired und damit
wieder genau einen freien Plot-Slot geschaffen. Der verbleibende Pack-Kandidat
ist `ModulePackC`, weil dort weiterhin `LTF Delta` und `Micro Profile` als
UI-Transport gebuendelt bleiben.

### C9.2 Reduce-Kandidaten

Diese direkte Quality-Row-Lage ist die reduzierte Nachfolge der alten
`QualityPackA/B`-Verdichtung und traegt dieselbe fachliche Aussage mit weniger
UI-Kopplung:

- `BUS CloseStrengthRow`
- `BUS EmaSupportRow`
- `BUS AdxRow`
- `BUS RelVolRow`
- `BUS VwapRow`
- `BUS ContextQualityRow`
- `BUS QualityCleanRow`
- `BUS QualityScoreRow`

`BUS QualityPackA` und `BUS QualityPackB` sind retired; die direkten
Quality-Rows sind jetzt der einzige aktive Vertrag fuer diese Diagnoseebene.

### C9.3 Stabile Pro-Support-Channels

Diese Kanaele bleiben auch nach C9 stabile Support- oder Level-Contracts und
sollen nicht leichtfertig neu zugeschnitten werden:

- `BUS MetaPack`
- `BUS QualityBoundsPack`
- `BUS ObjectsCountPack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

### C9 Guardrails

- Der Executable Core bleibt unveraendert.
- Der Lite-Contract bleibt eingefroren.
- `SMC_Long_Strategy.pine` behaelt seinen aktuellen 8-Kanal-Contract.
- C9 darf Pro-Diagnostik entkoppeln, aber keine neue Logikfamilie erzeugen.

## Naechste Umsetzung nach diesem Cut

1. Den Lite-Contract im Manifest als kanonische Teilmenge stabil halten.
2. Eine dedizierte Lite-Consumer-Surface nur dann bauen, wenn sie ohne neue
   Logikforks auskommt.
3. Pro-only Packs spaeter separat entkoppeln oder neu schneiden, ohne den
  Lite-Contract zu verwackeln.

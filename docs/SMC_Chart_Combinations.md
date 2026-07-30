# SMC Pine Skripte — Abhängigkeiten & Chart-Kombinationen

Letzte Wahrheitskorrektur: 2026-07-26

> **Verbindliche Zielarchitektur und Migration:**
> [SMC Extended Pine Architecture and Rollout Plan](SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md).
> Die Kombinationen mit alten Structure-, Imbalance-, Liquidity-, Profile-,
> Session- oder HTF-Snapshot-Companions sind historische Entwürfe und keine
> aktuelle Einsatzempfehlung.

Diese Doku beantwortet zwei wiederkehrende Fragen:

1. **Welche SMC Pine-Skripte müssen auf dem gleichen Chart laufen?**
2. **Welche Kombinationen sind für welchen Use-Case sinnvoll?**

## Kernerkenntnis

Die aktiven SMC-Skripte sind **nicht allgemein standalone**. Dashboard,
Strategy, Exit Signal, Hold Manager, Event Overlay und künftige Context-
Consumer lesen `input.source()`-Kanäle von einem Producer auf demselben Chart.
Sie benötigen den richtigen Producer, die passende Schema-Version und
verifizierte Bindings.

Die Micro-Profile-Library liefert nur langsam veränderliche Snapshot- und
Enrichment-Daten. Sie ersetzt keinen barweisen Producer.

## Dependency-Map

| Consumer-Typ | Erforderliche Quelle |
|---|---|
| Dashboard, Mobile, Strategy, Alerts, Breakout | Engine BUS v2 / Schema 7001 |
| Event Overlay | Micro-Profile-Eventdaten plus Engine BUS v2 |
| Exit Signal | Engine BUS v2 |
| Hold Manager | Engine BUS v2; manueller Plan nur als gekennzeichneter Fallback |
| Context Overlay | Context BUS v3 / Schema 8001; lokal implementiert, Shadow-Rollout noch offen |
| neue HTF Confluence | bestätigte 15m-/1h-/4h-Chartdaten über die Context-Library |
| Volume Profile Overlay | eigenständig aus Chart-OHLCV |

Die alten Snapshot-basierten Context-Skripte werden ersetzt oder archiviert.

## Praktische TradingView-Limits

| Plan | Indikatoren pro Chart |
|---|---|
| Free | 1 |
| Pro / Pro+ | 5 |
| Premium | 25 |

Du kannst nicht alle gleichzeitig auflegen — wähle die Kombination
passend zum Use-Case und Plan.

## Aktueller Rollout

Bis die Phasen im neuen Architektur- und Rollout-Plan abgeschlossen sind,
bleibt der bestehende Acht-Skript-Rollout die operative Basis:

- SMC Long-Dip Suite
- SMC Long-Dip Dashboard
- SMC Long-Dip Mobile
- SMC Long-Dip Strategy
- SMC Long-Dip Alerts
- SMC Setup Check
- SMC Breakout Overlay
- SMC Confluence Hub

Event Overlay, Exit Signal und Hold Manager werden erst nach ihren jeweiligen
Compile-, Binding-, Replay- und Source-Hash-Gates als Standardkombinationen
geführt. Die alten Snapshot-basierten Context-Skripte dürfen nicht als
operative Chartkombination verwendet werden.

Beim Hold Manager beginnt die Time-Stop-Uhr erst mit dem tatsächlichen
auf einer bestätigten Chart-Bar angenommenen Entry (`HM_ENTRY`). Wartezeit im
Zustand `ARMED` zählt nicht als Trade-Zeit. Entry-Epoch, Protected High,
Target-1-Status, aktiver Stop und terminaler Exit werden aus der bestätigten
BUS-/Preishistorie rekonstruiert. Ein neuer BUS-Plan darf einen laufenden
angenommenen Trade nicht überschreiben; Recovery erfolgt über einen
persistenten Zeitstempel.

## Ziel-Presets

Nach dem stufenweisen Rollout gelten diese Presets:

| Preset | Skripte |
|---|---|
| Lite | Suite plus Mobile oder Dashboard plus Event Overlay |
| Simple Management | Lite plus Exit Signal |
| Advanced Management | Lite plus Hold Manager |
| Pro Context | Suite plus Dashboard plus Context BUS plus Context Overlay |
| Pro HTF | Pro Context plus neu gebaute HTF Confluence |
| Research | Pro HTF plus optional Volume Profile oder Breakout Overlay |

Exit Signal und Hold Manager sind alternative Management-Modi. Für denselben
angenommenen Trade darf immer nur ein Satz handlungsrelevanter Exit-Alerts
aktiv sein.

## Nicht mehr verwenden

Bis zur dokumentierten Ablösung beziehungsweise Archivierung nicht in aktive
Layouts aufnehmen:

- alte Structure Context
- alte Imbalance Context
- alte Liquidity Context
- alte Liquidity Structure
- alte Profile Context
- archivierte Session-Context-v1-Snapshot-Quelle
- archivierte HTF-Confluence-v1-Snapshot-Quelle
- Orderflow Overlay als vermeintliche Live-Orderflow-Anzeige

Die neu gebauten Root-Skripte `SMC Session Context` und `SMC HTF Confluence`
bleiben bis zum privaten Compile-, Replay-, Hash- und Rollback-Nachweis
`not_deployed`; sie sind nicht mit den archivierten Snapshot-Quellen
gleichzusetzen.

Die konkreten Ersatz- und Archivierungsbedingungen stehen im
[Architektur- und Rollout-Plan](SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md).

# SMC Unified Target Architecture v5.5

*Deutsche Fassung - schlanke Zielarchitektur für ein solo-betriebenes SMC-System und teilbare TradingView-Skripte.*

## Leitregel / Guiding rule

> `snapshot.structure` bleibt rein kanonisch. Jede zusätzliche Intelligenz ist additiv und muss dem Nutzer helfen, das Signal schneller zu verstehen - nicht das System schwerer zu machen.

## 1. Status und Zielsetzung

Dieses Dokument definiert die **SMC Unified Target Architecture v5.5** für eine solo-betriebene SMC-Plattform und den dazugehörigen TradingView-Stack. Sie ist der direkte Nachfolger von v5.4 und behält die architektonischen Stärken bei, reduziert aber bewusst operative und Governance-Komplexität.

Das primäre Ziel ist, **schnelle, visuell klare und hinreichend zuverlässige Signale** über einen contract-first Generator und eine generierte Pine-Library bereitzustellen, ohne dass das Projekt zu einer schweren Plattform wird, die sich weder sauber betreiben noch gut teilen lässt.

- **Stabile kanonische Struktur** bleibt das Fundament.
- **Additive Kontexte** existieren nur dann, wenn sie Timing, Lesbarkeit oder Vertrauen verbessern.
- **Generator, Manifest, Library und Consumer** müssen synchron bleiben.
- **Einfache operative Sicherheit** ist wichtiger als plattformartige Kontrollmechanik.
- **Menschliche Nutzbarkeit** hat Vorrang vor architektonischer Vollständigkeit.

## 2. Gestaltungsrichtung

v5.5 bevorzugt bewusst **Einfachheit vor Vollständigkeit**, **Scoring vor übermäßigem Blocking** und **Wartbarkeit vor Plattform-Ambition**.

Das System soll nicht jede institutionelle Best Practice vollständig abbilden. Es soll für einen einzelnen Betreiber handelbar, verständlich und veröffentlichbar bleiben - auch dann, wenn die Skripte später mit anderen Nutzern geteilt werden.

> **Design-Folge:** Ein Feature gehört nur dann in v5.5, wenn es Signal-Timing, Signal-Klarheit, Signal-Vertrauen oder praktische Wartbarkeit verbessert. Erzeugt es hauptsächlich interne Komplexität, bleibt es draußen.

## 3. Systemgrenze

### Im Scope

- `smc_core/` als kanonischer Domain-Core
- `smc_adapters/` als Grenze zwischen generiertem Kontext und TradingView-Consumern
- `smc_integration/` als Orchestrierungs-, Generierungs- und Publish-Layer
- Schlanke additive Builder, die Signalqualität oder Lesbarkeit direkt verbessern
- Generierte Pine-Library plus kompaktes Manifest
- TradingView-Kernskript, kompakte Dashboard-Elemente, Alerts und optionale Overlays

### Außerhalb des Scopes

- Eine operationslastige Plattform nach Trading-Firm-Muster
- Tiefe feldbasierte Provenance oder forensische Replay-Systeme
- Große Release-Governance-Frameworks
- Massive Reason-Code-Inventare
- Research-Terminal-artige Pine-Skripte
- Kontextfamilien, die Timing, Lesbarkeit oder Wartbarkeit nicht verbessern

## 4. Architekturprinzipien

### 4.1 Kanonische Struktur bleibt minimal

Kanonisches `snapshot.structure` enthält nur stabile Strukturkategorien: `bos`, `orderblocks`, `fvg` und `liquidity_sweeps`. Die kanonische Struktur beantwortet nur eine Frage: **was ist strukturell passiert**.

### 4.2 Alles andere bleibt additiv

Sessions, Event-Risk, Freshness, Qualität, Warnungen und Nutzer-Erklärungen liegen außerhalb der kanonischen Struktur. Sie dürfen ein Setup qualifizieren und erklären, aber nicht das zugrunde liegende Strukturmodell umschreiben.

### 4.3 Lieber Scoring als Blocking

Das ist die wichtigste Verhaltensänderung in v5.5. Die Architektur bevorzugt **Qualitätsscores, Confidence-Tiers, Warnungen, Richtungs-Alignment und Freshness-Indikatoren** statt vieler harter Blocker.

- Harte Blocker bleiben auf wirklich irreführende Zustände begrenzt.
- Die meisten Kontexte sollen **abwerten** oder **qualifizieren**, nicht das Signal vollständig unterdrücken.
- Die Architektur muss Gate-Kaskaden vermeiden, die nützliche Setups auf null reduzieren.

### 4.4 Der Pine-Core bleibt einfach lesbar

Der Core soll fünf praktische Fragen beantworten: **gibt es ein Setup, in welche Richtung, wie gut ist es, was sind die Hauptgründe und gibt es gerade ein wesentliches Risiko**.

### 4.5 Manifest-Wahrheit bleibt leichtgewichtig

Manifest-Wahrheit bleibt ein Differenzierungsmerkmal des Systems, soll aber kompakt und praktisch bleiben - nicht zu einem vollständigen Audit-System werden.

### 4.6 Jedes Feld muss seinen Platz verdienen

Ein Feld gehört nur dann in die Architektur, wenn es Signal-Timing, Filterqualität, visuelle Interpretation, Nutzervertrauen oder Wartbarkeit klar verbessert.

## 5. Plattform- und Generierungsmodell

### 5.1 Rolle des Generators

1. Quelldaten sammeln.
2. Additive Kontexte berechnen.
3. Die generierte Pine-Library schreiben.
4. Das kompakte Manifest schreiben.
5. Einfache Konsistenzprüfungen ausführen.
6. Nach einfachen Regeln publishen oder zurückhalten.

### 5.2 Laufzeitphilosophie

Die Runtime soll sicher scheitern, aber nicht überreagieren. Wenn optionale Daten degradieren, soll die Basistruktur weiter nutzbar bleiben und additive Kontexte möglichst auf Defaults, Warnungen oder Score-Abzüge zurückfallen.

- Basistruktur verfügbar halten.
- Optionale Kontexte kontrolliert degradieren.
- Kontextqualität klar markieren.
- Hart blockieren nur dann, wenn der Nutzer sonst substanziell irregeführt würde.

### 5.3 Provider-Modell

Provider-Beteiligung soll auf Summary-Ebene sichtbar bleiben. Das System soll verständlich machen, ob Daten frisch sind, ob ein Degraded Mode aktiv ist und ob ein Fallback genutzt wurde - ohne tiefe Feld-Provenance aufzubauen.

## 6. Generierte Artefakte und Manifest

### 6.1 Autoritative Outputs

- Generierte Pine-Library
- Kompaktes Manifest

### 6.2 Aufgaben des Manifests

Das kompakte Manifest soll nur die Informationen transportieren, die innerhalb der Skripte und im Betrieb wirklich nützlich sind.

- `schema_version`
- `generator_version`
- `build_time`
- `as_of_time`
- `included_blocks`
- `provider_status_summary`
- `degraded_mode`
- optionale kurze Release-Notiz

### 6.3 Artifact-Truth-Regel

Generierte Artefakte dürfen nicht manuell gepflegt werden. Commitete Library und Manifest müssen dem echten Generator-Output entsprechen. Diese Regel bleibt nicht verhandelbar, weil sie einen der wichtigsten praktischen Vorteile des Systems darstellt.

## 7. Schlankes Enrichment-Modell

### 7.1 Event Risk light

Event Risk bleibt first-class, aber in vereinfachter Form. Die Familie soll beantworten, ob gerade ein relevantes Event-Risiko besteht und ob ein Setup frei, vorsichtig oder blockiert zu betrachten ist.

- `EVENT_WINDOW_STATE`
- `EVENT_RISK_LEVEL`
- `NEXT_EVENT_NAME`
- `NEXT_EVENT_TIME`
- `MARKET_EVENT_BLOCKED`
- `SYMBOL_EVENT_BLOCKED`
- `EVENT_PROVIDER_STATUS`

### 7.2 Session Context light

- `SESSION_CONTEXT`
- `IN_KILLZONE`
- `SESSION_DIRECTION_BIAS`
- `SESSION_CONTEXT_SCORE`
- optional `SESSION_VOLATILITY_STATE`

Die Familie soll zeigen, welche Session gerade zählt, ob die Bar in einem relevanten Zeitfenster liegt und ob die Session grob mit dem Setup übereinstimmt.

### 7.3 Liquidity-Sweep-Kontext

- `RECENT_BULL_SWEEP`
- `RECENT_BEAR_SWEEP`
- `SWEEP_DIRECTION`
- `SWEEP_RECLAIM_ACTIVE`
- `SWEEP_QUALITY_SCORE`

### 7.4 Order-Block-Kontext light

- `PRIMARY_OB_SIDE`
- `PRIMARY_OB_DISTANCE`
- `OB_FRESH`
- `OB_AGE_BARS`
- `OB_MITIGATION_STATE`

Ziel ist nicht, jeden aktiven Order Block zu modellieren. Ziel ist, den wichtigsten nahegelegenen Order-Block-Kontext Pine-freundlich verfügbar zu machen.

### 7.5 FVG- / Imbalance-Lifecycle light

- `PRIMARY_FVG_SIDE`
- `PRIMARY_FVG_DISTANCE`
- `FVG_FILL_PCT`
- `FVG_AGE_BARS`
- `FVG_FRESH`
- `FVG_INVALIDATED`

Das ist eine der wertvollsten additiven Familien, weil sie Timing und Lesbarkeit verbessert, ohne einen schweren visuellen Stack zu erfordern.

### 7.6 Structure State light

- `STRUCTURE_LAST_EVENT`
- `STRUCTURE_EVENT_AGE_BARS`
- `STRUCTURE_FRESH`
- `STRUCTURE_TREND_STRENGTH`

### 7.7 Signal Quality

Signal Quality ist die wichtigste neue Familie in v5.5. Sie verdichtet mehrere kleine Kontextfragmente zu einer nutzerseitigen Interpretationsschicht.

- `SIGNAL_QUALITY_SCORE`
- `SIGNAL_QUALITY_TIER`
- `SIGNAL_WARNINGS`
- `SIGNAL_BIAS_ALIGNMENT`
- `SIGNAL_FRESHNESS`

Der Score muss verständlich bleiben und darf nicht zur Blackbox werden. Praktisch kann er Struktur-Freshness, Session-Alignment, Sweep-Support, OB/FVG-Support, Event-Risk-Abzug und optional Headroom-/Stretch-Abzug kombinieren.

## 8. Signal- und Ausführungsmodell

| Layer | Verantwortung |
|---|---|
| Kanonische Struktur | Was strukturell passiert ist |
| Additiver Kontext | Unter welchen Bedingungen es passiert ist |
| Signal Quality | Wie gut das Setup aktuell aussieht |
| Lifecycle State | Ob es Watchlist, Ready oder stärker ist |
| Delivery und UX | Wie das Ergebnis dem Nutzer gezeigt wird |

### 8.1 Lifecycle

- `Watchlist`
- `Ready`
- `Entry Best`
- `Entry Strict`

Die Promotion in diese Zustände soll erklärbar bleiben, aber v5.5 bevorzugt schlanke Promotionslogik statt langer Gate-Ketten.

### 8.2 Harte Blocker bleiben selten

- Manifest oder Kontext sind klar ungültig
- Event Risk blockiert eindeutig
- Der Datenzustand ist so stale, dass der Nutzer irregeführt würde

Alles andere soll normalerweise als Warnung, Abzug oder Tier-Abstufung wirken - nicht als kompletter Blocker.

### 8.3 Confirmed-first Pine-Consumption

Actionable States sollen bevorzugt auf stabilen, bestätigten Informationen beruhen. Höherzeitrahmen-Kontexte werden konservativ konsumiert, und optionale Preview-Logik darf das Hauptsignal nicht umdefinieren.

## 9. Dashboard, Alerts und UX

### 9.1 Kompakte nutzerseitige Oberfläche

- Richtung
- Lifecycle State
- Signal-Quality-Tier
- Event-Status
- Context Bias
- Maximal zwei bis drei kurze Warnungen

### 9.2 Mini-Health-Badge statt Operator-Dashboard

Die Architektur benötigt kein vollwertiges Operator-Dashboard. Eine kompakte Statusfläche reicht aus:

- `Data: OK / Degraded / Stale`
- `Events: Clear / Caution / Blocked`
- `Signal: Low / OK / Good / High`
- `Bias: Bull / Bear / Mixed`

### 9.3 Alerts

- Neuer Ready-Zustand
- Upgrade des Quality-Tiers
- Event-Block wurde aktiviert
- Event-Block wurde aufgehoben
- Wesentliche Verschlechterung des Kontexts

Alerts sollen Zustandsänderungen sichtbar machen, nicht ein zweites Monitoring-System erzeugen.

## 10. Optionale Overlays

Optionale Overlays bleiben zulässig, aber sekundär. Es sollen nur Overlays behalten werden, die die menschliche Interpretation klar verbessern.

- Session-Context-Overlay
- Liquidity-Structure-Overlay
- Event-Overlay

Wenn ein Overlay den Chart sichtbar überlädt oder Pine-Last erhöht, ohne Entscheidungen zu verbessern, bleibt es optional oder wird entfernt.

## 11. Testing und Validierung

v5.5 hält Testing bewusst schlank. Ziel ist nicht, schwere Release-Governance aufzubauen. Ziel ist sicherzustellen, dass der aktuelle Build weiterhin stabile, verständliche und Pine-nutzbare Outputs liefert.

- Contract- und Feldpräsenz-Tests
- Generator-zu-Library-Konsistenzchecks
- Einfache Anti-Drift-Prüfungen
- Schlanke Checks für degradierte Datenzustände
- Eine kleine Anzahl Pine-Consumer-Checks für Kernfelder

## 12. Operative Prioritäten

1. Signale nutzbar halten. Kein additiver Kontext darf die Signalverfügbarkeit kollabieren lassen oder Signale über ihre Nützlichkeit hinaus verzögern.
2. Signalqualität durch kompakten additiven Kontext verbessern.
3. Generator- und Library-Wahrheit als praktisches Differenzierungsmerkmal erhalten.
4. Pine modular, schnell und visuell sauber halten.
5. Nur dort wachsen, wo ein klarer Payoff besteht.

## 13. Implementierungs-Workstreams

| Workstream | Primärer Output |
|---|---|
| A - Signal-Quality-Layer | Kompakter Score, Tier, Freshness und Warnings |
| B - Event Risk light | Einfache Event-States, Caution-/Block-Logik, Alert-Hooks |
| C - FVG- und OB-Lifecycle light | Freshness, Alter, Fill/Mitigation, Distanz, Primary Side |
| D - Manifest- und Library-Vereinfachung | Kompakte Build-Wahrheit in den Skripten |
| E - Pine-UX-Cleanup | Mini-Health-Badge, kompakte Quality-Anzeige, klarere Signaloberfläche |

### Empfohlene Reihenfolge

1. Signal-Quality-Layer
2. Event Risk light
3. FVG / OB lifecycle light
4. Manifest-Vereinfachung
5. Pine-UX-Cleanup

## 14. Explizite Non-Goals

- Eine operationslastige Plattform nach Trading-Firm-Muster
- Große Release-Governance-Systeme
- Tiefe forensische Provenance
- Schwere Alert-State-Maschinerie
- Gigantische Pine-Dashboards
- Mehrstufige Gate-Ketten, die die meisten Signale eliminieren
- Feature-Wachstum, das Vollständigkeit stärker verbessert als Nutzbarkeit

## 15. Entscheidungszusammenfassung

v5.5 definiert ein schlankeres und praktischeres Zielsystem. Es bewahrt stabile kanonische Struktur, additive Kontexte, Generator-Manifest-Library-Synchronität und modulare Pine-Consumption, entfernt aber bewusst plattformartigen Overhead.

Die Architektur erwartet **stabile kanonische Struktur**, **kompakte High-Value-Kontexte**, **ein leichtgewichtiges Manifest**, **einen nutzerseitigen Signal-Quality-Layer** und **einen Pine-Core, der visuell klar und handelbar bleibt**.

> **Abschließende Regel:** `snapshot.structure` bleibt rein kanonisch. Jede zusätzliche Intelligenz ist additiv und muss dem Nutzer helfen, das Signal schneller zu verstehen.

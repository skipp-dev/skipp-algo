# TradingView Manual Validation Runbook

English companion: [tradingview-manual-validation-runbook_EN.md](tradingview-manual-validation-runbook_EN.md)

## Ziel

Dieses Runbook dient der externen manuellen TradingView-Laufzeitvalidierung des aktuellen Split-Stands.

Geprüft werden:

1. Producer: [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
2. Dashboard-Consumer: [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
3. Strategy-Consumer: [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)

Ziel ist ein klarer Pass/Fail-Entscheid für den aktuellen Vertragsstand in TradingView, ohne Änderungen an Produktionslogik.

`SMC++.pine` gehoert nicht mehr zu diesem aktiven Validierungspfad. Der Legacy-
Monolith bleibt ein eingefrorener Kompatibilitaetsanker und wird separat ueber
Repo-Regressionen abgesichert.

## Benötigte Dateien

1. [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
2. [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
3. [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)
4. [tradingview-validation-checklist.md](tradingview-validation-checklist.md)
5. [tradingview-manual-validation-report-template.md](tradingview-manual-validation-report-template.md)

## Begleitende Release-Layer-Referenzen

1. [../scripts/tv_publish_micro_library.ts](../scripts/tv_publish_micro_library.ts)
2. [../scripts/tv_preflight.ts](../scripts/tv_preflight.ts)
3. [../automation/tradingview/lib/tv_shared.ts](../automation/tradingview/lib/tv_shared.ts)

## Empfohlene Reihenfolge In TradingView

1. Core öffnen und kompilieren.
2. Dashboard hinzufügen und alle 29 `source`-Bindings auf den Core legen.
3. Strategy hinzufügen und alle 8 `source`-Bindings auf den Core legen.
4. Die fünf Prüfszenarien auf demselben Symbol und Timeframe durchlaufen.
5. Alle Beobachtungen direkt in die Report-Vorlage eintragen.

### Binding-Konvention

1. Dashboard bindet in vier Gruppen: Lifecycle, Diagnostic Packs, Trade Plan, Lean Surface.
2. Strategy bindet in zwei Gruppen: Entry States, Trade Plan.
3. Beide Consumer werden in TradingView immer top-to-bottom an die gleichnamigen BUS-Serien des Cores gebunden.

## Producer-Prüfung

### Producer Schrittfolge

1. [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) in TradingView öffnen.
2. Das Skript auf dem Zielchart kompilieren.
3. Im Chart prüfen, ob das Skript ohne Compile- oder Runtime-Fehler geladen bleibt.
4. Im `source`-Picker eines nachgelagerten Consumers prüfen, ob die Hidden-Bus-Serien auswählbar sind.

### Producer Erwartete Beobachtungen

1. Das Skript kompiliert ohne Fehler.
2. Es bleiben keine sichtbaren Laufzeitfehler im Chart-Overlay zurück.
3. Die folgenden 29 Serien sind als Source auswählbar:

- `BUS ZoneActive`
- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`
- `BUS SourceKind`
- `BUS StateCode`
- `BUS TrendPack`
- `BUS MetaPack`
- `BUS HardGatesPackA`
- `BUS HardGatesPackB`
- `BUS EventRiskRow`
- `BUS QualityPackA`
- `BUS QualityPackB`
- `BUS QualityBoundsPack`
- `BUS ModulePackA`
- `BUS ModulePackB`
- `BUS ModulePackC`
- `BUS ModulePackD`
- `BUS EnginePack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`
- `BUS LeanPackA`
- `BUS LeanPackB`

### Producer Pass/Fail-Kriterien

Pass:

1. Core kompiliert.
2. Keine Laufzeitfehlermeldung.
3. Alle 29 Serien sind auswählbar.

Fail:

1. Compile-Fehler.
2. Laufzeitfehler.
3. Fehlende oder falsch benannte Bus-Serien.

## Dashboard-Prüfung

### Dashboard Schrittfolge

1. [../SMC_Dashboard.pine](../SMC_Dashboard.pine) auf denselben Chart legen.
2. Alle 29 `input.source()`-Felder exakt mit den Core-Serien belegen.
3. Sichtbarkeit und Reaktion der Sektionen prüfen:

- Lifecycle
- Hard Gates
- Quality
- Modules
- Engine

1. Die fünf Szenarien aus [tradingview-validation-checklist.md](tradingview-validation-checklist.md) nacheinander prüfen.

### Dashboard Erwartete Beobachtungen

1. Dashboard kompiliert ohne Fehler.
2. Alle 29 Bindings sind vollständig auswählbar.
3. Das Dashboard bleibt sichtbar.
4. Die Sektionen reagieren plausibel auf den Core-Zustand.

### Dashboard Szenario-Prüfung

- Neutral / keine Zone

Erwartung:

`Pullback Zone = No Long Zone`
`Long Setup = No Setup`
`Exec Tier = n/a`
`Long Visual = Neutral`

- Armed

Erwartung:

`Long Setup = Armed | <source>`
`Exec Tier = Armed`
`Setup Age = armed fresh` oder `armed stale`

- Confirmed

Erwartung:

`Long Setup = Confirmed | <source>`
`Exec Tier = Confirmed`
`Setup Age = confirm fresh` oder `confirm stale`

- Ready

Erwartung:

`Long Visual = Ready`
`Exec Tier = Ready`, `Best` oder `Strict`
`Ready Gate = Ready`
Risk-Plan-Level sind plausibel, falls aktiv

- Invalidated

Erwartung:

`Long Setup = Invalidated`
`Long Visual = Fail`
`Strict Gate` wird nicht als bestanden angezeigt

### Dashboard Pass/Fail-Kriterien

Pass:

1. Dashboard kompiliert.
2. Alle 26 Bindings sind belegbar.
3. Alle fünf Szenarien zeigen die erwartete Reaktion.
4. Keine internen Widersprüche zwischen Lifecycle, Exec Tier, Setup Age und Risk-Linien.

Fail:

1. Binding fehlt.
2. Binding zeigt falsche Serie.
3. Sektion fehlt oder reagiert nicht.
4. Szenario-Reaktion ist inkonsistent zur Checkliste.

## Strategy-Prüfung

### Strategy Schrittfolge

1. [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine) auf denselben Chart legen.
2. Die 8 `input.source()`-Felder exakt mit den Core-Serien belegen.
3. `Entry Mode`, `Trigger`, `Invalidation`, `Stop` und `Targets` gegen den dokumentierten Vertrag prüfen.

### Strategy Erwartete Beobachtungen

1. Strategy kompiliert ohne Fehler.
2. Die folgenden 8 Bindings sind vollständig auswählbar:

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

1. Die Strategy hängt nur von diesen 8 Kanälen ab.
2. Trigger und Invalidation sind konsistent.
3. Stop und Take-Profit verhalten sich konsistent zur Risk-Struktur.

### Strategy Pass/Fail-Kriterien

Pass:

1. Strategy kompiliert.
2. Alle 8 Bindings sind belegbar.
3. Entry-Mode-Reaktion ist konsistent zum jeweiligen Lifecycle-Kanal.
4. Trigger, Invalidation, Stop und Target-Logik sind plausibel und widerspruchsfrei.

Fail:

1. Strategy kompiliert nicht.
2. Ein erwartetes Binding fehlt.
3. Entry-Mode reagiert nicht konsistent zum Core.
4. Risk-Level sind widersprüchlich.

## Operator-Hinweise

1. Alle drei Skripte auf demselben Symbol und Timeframe prüfen.
2. Abweichungen nur als Beobachtung festhalten, keine Ad-hoc-Logikänderungen vornehmen.
3. Nach jedem Fail möglichst einen Screenshot sichern.
4. Den Lauf mit [tradingview-manual-validation-report-template.md](tradingview-manual-validation-report-template.md) abschließen.

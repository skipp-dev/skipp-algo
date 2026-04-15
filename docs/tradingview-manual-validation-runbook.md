# TradingView Manual Validation Runbook

English companion: [tradingview-manual-validation-runbook_EN.md](tradingview-manual-validation-runbook_EN.md)

> **Ersteinrichtung:** Fuer den kanonischen Setup-Pfad (Core + Dashboard +
> Strategy zum ersten Mal auf einen Chart legen und binden) siehe
> [smc-mainline-setup-runbook.md](smc-mainline-setup-runbook.md). Dieses
> Runbook ist fuer die manuelle Laufzeitvalidierung nach bereits erfolgtem
> Setup.

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
3. [../scripts/create_tradingview_storage_state.ts](../scripts/create_tradingview_storage_state.ts)
4. [tradingview-auth-modes.md](tradingview-auth-modes.md)
5. [../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py)

## Lokaler Prereq-Check

Workspace-Refresh: 2026-04-07

1. Die Entry-Skripte `scripts/tv_preflight.ts`, `scripts/tv_publish_micro_library.ts` und `scripts/create_tradingview_storage_state.ts` sind lokal vorhanden.
2. Die gemeinsame TradingView-Automationsschicht unter `automation/tradingview/lib/...` ist in diesem Checkout vorhanden.
3. `automation/tradingview/reports` sowie wiederverwendbare Auth-Artefakte unter `automation/tradingview/auth/...` sind in diesem Workspace vorhanden.
4. Folge: Der kanonische Repo-Live-Check ist aus diesem Arbeitsbaum wieder reproduzierbar, und zwar ueber `npm run tv:preflight:smc-mainline`.
5. Dieses Runbook bleibt der manuelle Gegencheck fuer externe Review-Laeufe, symbol-/timeframe-spezifische Beobachtungen und unabhaengige Reproduktion.

## Empfohlene Gate-Reihenfolge

1. Zuerst `npm run tv:preflight:smc-mainline` als kanonischen Mainline-Gate-Lauf ausfuehren.
2. Danach dieses Runbook nutzen, wenn ein manueller Gegencheck oder ein extern dokumentierter Review-Lauf gebraucht wird.
3. Fuer die kanonische Rollen-, Scope-, Binding- und Product-Surface-Evidence-Quelle immer `scripts/smc_bus_manifest.py` plus `artifacts/tradingview/smc_product_cut_manifest.json` heranziehen.

## Empfohlene Reihenfolge In TradingView

1. Core öffnen und kompilieren.
2. Dashboard hinzufügen und alle 59 `source`-Bindings auf den Core legen.
3. Strategy hinzufügen und alle 8 `source`-Bindings auf den Core legen.
4. Die fünf Prüfszenarien auf demselben Symbol und Timeframe durchlaufen.
5. Alle Beobachtungen direkt in die Report-Vorlage eintragen.

### Binding-Konvention

1. Dashboard startet mit `1. Product Surface` und bindet danach in sechs operator-only BUS-Gruppen: `2. Operator Only - Lifecycle BUS`, `3. Operator Only - Diagnostic Rows`, `4. Operator Only - Diagnostic Support`, `5. Operator Only - Trade Plan`, `6. Operator Only - Detail Surface`, `7. Operator Only - Lean Surface`.
2. Strategy startet mit `1. Execution Setup` und `2. Trade Plan`; die `source`-Bindings bleiben in `3. Expert Mapping - Entry States` und `4. Expert Mapping - Trade Plan`.
3. Die Core-Settings priorisieren jetzt `1. Core Setup`, `2. Output`, `3. Trade Plan`, `4. Session Gate` und `5. Runtime Budget` vor den Advanced-Gruppen.
4. Beide Consumer werden in TradingView immer top-to-bottom an die gleichnamigen BUS-Serien des Cores gebunden.
5. Die kanonische Quelle fuer Namen, Reihenfolge und Gruppen ist [../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py).
6. Zusaetzlich gibt es im Dashboard die lokale Gruppe `8. Operator Only - Local Debug Mirrors` ohne `source`-Bindings. Diese drei Bool-Inputs werden nur manuell gespiegelt, wenn `Debug Flags` oder `Long Debug` gegen die effektive Core-Debug-Konfiguration geprueft werden sollen.

### Kanonische BUS-Reihenfolge

Die aktive Engine publiziert die Hidden-BUS-Serien in genau dieser Manifest-
Reihenfolge:

- `BUS SchemaVersion`
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
- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`
- `BUS SessionGateRow`
- `BUS MarketGateRow`
- `BUS VolaGateRow`
- `BUS MicroSessionGateRow`
- `BUS MicroFreshRow`
- `BUS VolumeDataRow`
- `BUS QualityEnvRow`
- `BUS QualityStrictRow`
- `BUS CloseStrengthRow`
- `BUS EmaSupportRow`
- `BUS AdxRow`
- `BUS RelVolRow`
- `BUS VwapRow`
- `BUS ContextQualityRow`
- `BUS QualityCleanRow`
- `BUS QualityScoreRow`
- `BUS SdConfluenceRow`
- `BUS SdOscRow`
- `BUS VolRegimeRow`
- `BUS VolSqueezeRow`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`
- `BUS ZoneObTop`
- `BUS ZoneObBottom`
- `BUS ZoneFvgTop`
- `BUS ZoneFvgBottom`
- `BUS SessionVwap`
- `BUS AdxValue`
- `BUS RelVolValue`
- `BUS StretchZ`
- `BUS StretchSupportMask`
- `BUS LtfBullShare`
- `BUS LtfBiasHint`
- `BUS LtfVolumeDelta`
- `BUS ObjectsCountPack`
- `BUS LeanPackA`
- `BUS LeanPackB`

`BUS LtfDeltaState`, `BUS SafeTrendState`, `BUS MicroProfileCode`,
`BUS ReadyBlockerCode`, `BUS StrictBlockerCode`, `BUS VolExpansionState` und
`BUS DdviContextState` bilden jetzt die explizite Support-Code-Oberflaeche,
aus der das Dashboard die frueher gepackten Modul- und Engine-Zeilen lokal
rekonstruiert.

## Producer-Prüfung

### Producer Schrittfolge

1. [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) in TradingView öffnen.
2. Das Skript auf dem Zielchart kompilieren.
3. Im Chart prüfen, ob das Skript ohne Compile- oder Runtime-Fehler geladen bleibt.
4. Im `source`-Picker eines nachgelagerten Consumers prüfen, ob die Hidden-Bus-Serien auswählbar sind.

### Producer Erwartete Beobachtungen

1. Das Skript kompiliert ohne Fehler.
2. Es bleiben keine sichtbaren Laufzeitfehler im Chart-Overlay zurück.
3. Alle 59 Dashboard-Bindings aus [tradingview-validation-checklist.md](tradingview-validation-checklist.md) sind auswählbar.
4. Mit aktiviertem `Focus View` bleibt genau eine Hero-Card sichtbar, separate Warning-Labels sowie Strong/Weak-Swing-Level verschwinden, und `Core Trigger` / `Core Invalidation` erscheinen erst ab mindestens `Ready`.

### Producer Pass/Fail-Kriterien

Pass:

1. Core kompiliert.
2. Keine Laufzeitfehlermeldung.
3. Alle 59 Serien sind auswählbar.
4. `Focus View` entspricht dem kompakten First-Run-Vertrag.

Fail:

1. Compile-Fehler.
2. Laufzeitfehler.
3. Fehlende oder falsch benannte Bus-Serien.
4. Focus View zeigt doppelte Warning-Labels, Default-Swing-Level oder Trade-Linien vor `Ready`.

## Dashboard-Prüfung

### Dashboard Schrittfolge

1. [../SMC_Dashboard.pine](../SMC_Dashboard.pine) auf denselben Chart legen.
2. Alle 59 `input.source()`-Felder exakt mit den Core-Serien belegen.
3. Sicherstellen, dass `View = Decision Brief` aktiv ist und die
   Toggles `Show Brief Panel` sowie `Show Trade Plan` den erwarteten
   Companion-Zuschnitt zeigen.
4. Falls `Debug Flags` oder `Long Debug` validiert werden sollen, die drei lokalen Debug-Mirror-Toggles im Dashboard passend zur effektiven Core-Konfiguration setzen.
5. Sichtbarkeit und Reaktion der Sektionen prüfen:

- Lifecycle
- Hard Gates
- Quality
- Modules
- Engine

1. Die fünf Szenarien aus [tradingview-validation-checklist.md](tradingview-validation-checklist.md) nacheinander prüfen.
2. Zusätzlich die geforderte Product-Surface-Evidence sichern:

Die kanonische Product-Surface-Evidence liegt im `validationEvidence`-Block des Artifacts `artifacts/tradingview/smc_product_cut_manifest.json`.
Nur gerenderte Chart-Screenshots erfassen, keine Pine-Editor-Screenshots.

- gerenderter Core-First-Run-Screen
- gerenderter Dashboard-Screen in `Decision Brief`
- gerenderter Dashboard-Screen in `Audit View`
- gerenderter Strategy-Screen mit `Execution Trigger`, `Execution Invalidation` und `Execution Take Profit`, wenn ein Plan aktiv ist

### Dashboard Erwartete Beobachtungen

1. Dashboard kompiliert ohne Fehler.
2. Alle 59 Bindings sind vollständig auswählbar.
3. Das Dashboard bleibt sichtbar.
4. Die Default-Companion-Flaeche zeigt `SMC Decision Board` mit der Reihenfolge
   `Structure`, `Session / Market`, `Event Risk`, `Data Quality`,
   `Short-term Pressure`, `Risk Plan`.
5. Die Sektionen reagieren plausibel auf den Core-Zustand.
6. Fuer den Expert-View ist `Audit View | Expert review only` sichtbar, mit getrennten Review-Bloecken fuer `Decision Detail`, `Lean Surface`, `Gates`, `Quality Rows`, `Support / Metrics`, `Risk / Plan` und `Debug`.

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
2. Alle 59 Bindings sind belegbar.
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
3. `Execution Stage`, `Execution Trigger`, `Execution Invalidation` und `Execution Take Profit` gegen den dokumentierten Vertrag prüfen.

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
2. Execution Trigger und Execution Invalidation sind konsistent.
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
4. Editor-Screenshots gelten nicht als Produkt-Evidence.
5. Den Lauf mit [tradingview-manual-validation-report-template.md](tradingview-manual-validation-report-template.md) abschließen.

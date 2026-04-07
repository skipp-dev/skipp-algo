# SMC R1.1 Migration and Operator Guide

## Status

Released

## Zweck

Dieses Dokument haertet die erste Decision-First-Auslieferung fuer R1.1.

Es deckt drei operative Themen ab:

1. sichere Preset- und Default-Migration fuer bestehende Nutzer,
2. den operator-only Workflow fuer `SMC_Dashboard.pine` als Companion-Surface.
3. den Wrapper- und Binding-Workflow fuer `SMC_Long_Strategy.pine`.

## R1.1 Scope

- FR-09 Dashboard Pro Row Regrouping
- FR-10 Preset Migration Hardening
- FR-11 Operator Binding Workflow Cleanup

## Preset Migration And Safe Defaults

Die Decision-First-Umstellung darf keine stillen Engine-Forks einfuehren.

Deshalb gelten fuer die erste Migration diese Regeln:

1. `compact_mode` bleibt die bestehende Kernvariable in `SMC_Core_Engine.pine`.
   Die sichtbare Bezeichnung lautet jetzt `Focus View`, aber der
   Schalter bleibt visual-only und ist fuer den First-Run jetzt standardmaessig aktiv.
2. `surface_mode` in `SMC_Dashboard.pine` bleibt ein Visualisierungsmodus.
   `Decision Brief` ist die Default-Surface, `Audit View` ist opt-in.
3. `entry_mode`, `min_quality_score`, `take_profit_r` und `use_take_profit` in
   `SMC_Long_Strategy.pine` bleiben Wrapper-Controls. Sichtbar heissen sie
   `Entry Stage`, `Minimum Setup Quality`, `Profit Target (R)` und
   `Enable Profit Target`. Sie aendern den Strategy-Wrapper, aber nicht den
   Core-BUS-Contract.
4. Bestehende BUS-Bindings fuer Dashboard und Strategy werden durch die neuen
   Default-Surfaces nicht neu verdrahtet. Die Visual-Umstellung darf keine
   zusaetzlichen Core-Gates aktivieren.
5. Dashboard und Strategy bleiben Consumer des Core-BUS. R1.1 fuehrt keine
   neue Producer-Logik ausserhalb des Core ein.

## Safe-Default Summary

| Surface | Default | Hard Rule |
| --- | --- | --- |
| `SMC_Core_Engine.pine` | `compact_mode = true` mit `Focus View` als First-Run-Default | Visual-only, keine neue Engine-Semantik |
| `SMC_Dashboard.pine` | `surface_mode = "Decision Brief"` | BUS binding order bleibt unveraendert |
| `SMC_Long_Strategy.pine` | `entry_mode = "Strict"`, `use_take_profit = true` | Wrapper-Control, kein neuer Producer |

## Operator-Only Companion Workflow

`SMC_Dashboard.pine` und `SMC_Long_Strategy.pine` bleiben operator-only
Consumer-Skripte.

Das bedeutet:

1. Endnutzer sollen die `input.source(...)`-Oberflaeche nicht als normale
   Public-Setup-Strecke verstehen.
2. Die BUS binding order wird weiterhin strikt top-to-bottom anhand des
   Manifests gebunden.
3. Die neue Decision Brief Surface erscheint erst nach korrekter Bindung als
   nutzbare Entscheidungserklaerung.
4. `Audit View` ist fuer Operatoren und Audit gedacht, nicht als
   Default-Startpunkt fuer neue Nutzer.
5. `SMC_Long_Strategy.pine` ist die Execution-Surface fuer Orders und
   Backtests, nicht
   die Quelle neuer Signallogik.

## Binding Workflow

1. `SMC_Core_Engine.pine` auf den Chart legen und die BUS-Exports aktiv lassen.
2. `SMC_Dashboard.pine` als Companion hinzufuegen.
3. Die `input.source(...)`-Kanaele exakt in der manifest-konformen BUS binding
   order von oben nach unten verbinden.
4. `SMC_Long_Strategy.pine` hinzufuegen.
5. Die acht Strategy-`input.source(...)`-Kanaele exakt top-to-bottom an dieselben
   Core-BUS-Serien binden.
6. Danach zuerst `Decision Brief` fuer die schnelle Companion-Leseflaeche nutzen.
7. `Entry Stage`, `Minimum Setup Quality`, `Profit Target (R)` und `Enable Profit Target`
   nur als Wrapper-Steuerung verstehen.

## Validation Hooks

Der Workflow wird bewusst ueber bestehende Contracts abgesichert:

- `tests/test_smc_bus_manifest_contract.py`
- `tests/test_smc_bus_v2_semantics.py`
- `tests/test_tradingview_decision_first_ui.py`

Diese Tests sichern insbesondere:

- versteckte, aber exakte BUS binding order,
- lokale Debug-Mirror-Kontrakte,
- die neue Lite-vs-Pro Gliederung im Dashboard,
- die Wrapper-Controls und Plot-Ausgaben der Long Strategy,
- die Migrationserwartung, dass die neuen Surface-Modi visual-only bleiben.

## Operator Notes

- `Decision Brief` ist fuer schnelle Entscheidungserklaerung gedacht.
- `Audit View` ist eine operator-only Diagnoseflaeche.
- `SMC_Long_Strategy.pine` ist die Execution-Surface fuer Backtest und
   Ausfuehrungsplanung auf dem Core-BUS.
- Wenn Binding-Drift vermutet wird, immer zuerst die Contract-Tests laufen
  lassen statt Bindings manuell umzubenennen.

## Migration Rule

Wenn eine neue Surface-Einstellung mehr Diagnose sichtbar macht, darf sie das
Produktverhalten des Core nicht veraendern. Wenn eine Strategy-Einstellung das
Wrapper-Verhalten aendert, darf sie trotzdem keinen neuen Core-Contract
einfuehren.

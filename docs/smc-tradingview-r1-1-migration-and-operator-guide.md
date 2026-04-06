# SMC / SkippALGO R1.1 Migration and Operator Guide

## Status

Draft

## Zweck

Dieses Dokument haertet die erste Decision-First-Auslieferung fuer R1.1.

Es deckt zwei operative Themen ab:

1. sichere Preset- und Default-Migration fuer bestehende Nutzer,
2. den operator-only Workflow fuer `SMC_Dashboard.pine` als Companion-Surface.

## R1.1 Scope

- FR-09 Dashboard Pro Row Regrouping
- FR-10 Preset Migration Hardening
- FR-11 Operator Binding Workflow Cleanup

## Preset Migration And Safe Defaults

Die Decision-First-Umstellung darf keine stillen Engine-Forks einfuehren.

Deshalb gelten fuer die erste Migration diese Regeln:

1. `compact_mode` bleibt die bestehende Kernvariable in `SMC_Core_Engine.pine`.
   Die sichtbare Bezeichnung wurde in Richtung Lite-Hero umformuliert, aber der
   Schalter bleibt visual-only.
2. `surface_mode` in `SMC_Dashboard.pine` bleibt ein Visualisierungsmodus.
   `Compact Detail` ist die Default-Surface, `Pro Diagnostics` ist opt-in.
3. `surfaceMode` in `SkippALGO.pine` bleibt ebenfalls visual-only.
   `Lite` ist die Default-Surface, `Pro Diagnostics` bleibt optional.
4. Bestehende Risk-, Forecast- und Gate-Inputs werden durch die neuen
   Default-Surfaces nicht neu verdrahtet. Die Lite/Pro-Auswahl darf keine
   zusaetzlichen Handelsgates aktivieren.

## Safe-Default Summary

| Surface | Default | Hard Rule |
| --- | --- | --- |
| `SMC_Core_Engine.pine` | `compact_mode = false` mit Decision-First-Lite als klare Visual-Option | Visual-only, keine neue Engine-Semantik |
| `SMC_Dashboard.pine` | `surface_mode = "Compact Detail"` | BUS binding order bleibt unveraendert |
| `SkippALGO.pine` | `surfaceMode = "Lite"` | HUD und Alert-Sprache aendern die Signallogik nicht |

## Operator-Only Companion Workflow

`SMC_Dashboard.pine` bleibt ein operator-only Companion-Skript.

Das bedeutet:

1. Endnutzer sollen die `input.source(...)`-Oberflaeche nicht als normale
   Public-Setup-Strecke verstehen.
2. Die BUS binding order wird weiterhin strikt top-to-bottom anhand des
   Manifests gebunden.
3. Die neue Compact Detail Surface erscheint erst nach korrekter Bindung als
   nutzbare Entscheidungserklaerung.
4. `Pro Diagnostics` ist fuer Operatoren und Audit gedacht, nicht als
   Default-Startpunkt fuer neue Nutzer.

## Binding Workflow

1. `SMC_Core_Engine.pine` auf den Chart legen und die BUS-Exports aktiv lassen.
2. `SMC_Dashboard.pine` als Companion hinzufuegen.
3. Die `input.source(...)`-Kanaele exakt in der manifest-konformen BUS binding
   order von oben nach unten verbinden.
4. Danach zuerst `Compact Detail` fuer die schnelle Leseflaeche nutzen.
5. Nur bei Diagnosebedarf auf `Pro Diagnostics` wechseln.

## Validation Hooks

Der Workflow wird bewusst ueber bestehende Contracts abgesichert:

- `tests/test_smc_bus_manifest_contract.py`
- `tests/test_smc_bus_v2_semantics.py`
- `tests/test_tradingview_decision_first_ui.py`

Diese Tests sichern insbesondere:

- versteckte, aber exakte BUS binding order,
- lokale Debug-Mirror-Kontrakte,
- die neue Lite-vs-Pro Gliederung im Dashboard,
- die Migrationserwartung, dass die neuen Surface-Modi visual-only bleiben.

## Operator Notes

- `Compact Detail` ist fuer schnelle Entscheidungserklaerung gedacht.
- `Pro Diagnostics` ist eine operator-only Diagnoseflaeche.
- Wenn Binding-Drift vermutet wird, immer zuerst die Contract-Tests laufen
  lassen statt Bindings manuell umzubenennen.

## Migration Rule

Wenn eine neue Surface-Einstellung mehr Diagnose sichtbar macht, darf sie das
Produktverhalten nicht veraendern. Visual-only bleibt visual-only.

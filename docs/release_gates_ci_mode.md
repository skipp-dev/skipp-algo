# Release-Gates CI-Modus — Entscheidung und Dokumentation

Stand: 2026-04-17 (WP-D)

## Problem

Der `smc-release-gates`-Workflow scheitert in Clean-CI-Umgebungen, weil
Produktions-Quelldateien (Databento-Workbook, FMP-Watchlist, Benzinga-News)
nicht vorhanden sind.  Die Failures sind infrastrukturbedingt, nicht logisch.

## Entscheidung

**Konditionalisierung via `--ci-mode` Flag.**

Statt Fixture-Daten bereitzustellen oder den Workflow komplett zu deaktivieren,
erkennt das Script jetzt automatisch, ob Gate-Failures rein durch abwesente
Quelldateien verursacht werden:

- Codes: `source_file_not_found`, `NONCANONICAL_MANIFEST_WORKBOOK_PATH`, `MISSING_SMOKE_RESULT`
- Betroffene Gates werden auf `blocking: false` herabgestuft
- Der Exit-Code wird dadurch 0 (statt 1)
- Im Report bleibt der tatsächliche Status (`fail`) erhalten — es gibt keine
  stille Unterdrückung

## Technische Änderungen

| Datei | Änderung |
|-------|----------|
| `scripts/run_smc_release_gates.py` | Neues `--ci-mode`-Flag + `_gate_failure_is_data_absent()` Erkennung |
| `.github/workflows/smc-release-gates.yml` | `--ci-mode` an den Release-Gates-Step übergeben |

## Verhalten

| Szenario | Exit-Code | Gates im Report |
|----------|-----------|-----------------|
| Lokale Ausführung mit Produktionsdaten | 0 | Alle `ok` |
| CI ohne Produktionsdaten, `--ci-mode` | 0 | Data-absent Gates: `fail` + `blocking: false` + `ci_mode_downgraded: true` |
| CI ohne Produktionsdaten, ohne `--ci-mode` | 1 | Data-absent Gates: `fail` + `blocking: true` |
| Echtes Release (Workflow-Dispatch, manuelle Daten) | Ohne `--ci-mode` weglassen → 1 bei echtem Fehler |

## Empfehlung für Releases

Für echte Releases den Workflow ohne `--ci-mode` per `workflow_dispatch`
auslösen, nachdem die Produktionsdaten auf dem Runner bereitgestellt sind.

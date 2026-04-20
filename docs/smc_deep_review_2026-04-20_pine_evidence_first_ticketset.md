# SMC Deep Review 2026-04-20: Pine Evidence First Ticketset

Stand: 2026-04-20
Status: aktiv
Workstream: WS1 Pine Evidence Lane

## Zweck

Dieses Dokument schneidet aus dem Deep-Review-Programm den ersten direkt
umsetzbaren Ticketblock fuer WS1 heraus.

Es ist bewusst kein kompletter Workstream-Plan, sondern das kleinste
belastbare Lieferpaket, das die Pine Evidence Lane in die bestehende
Release- und Validation-Kette einhaengt.

## Source Documents

- `docs/smc_deep_review_2026-04-20_improvement_plan.md`
- `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`
- `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`
- `docs/smc-tradingview-first-release-ticketset.md`

## First-Ticketset Definition

Das erste WS1-Ticketset ist erreicht, wenn das Repo fuer einen kleinen,
kanonischen Satz von Pine-Kernfaellen nicht mehr nur Build- und Runtime-
Erfolg kennt, sondern explizite semantische Evidence.

Im Minimalzustand bedeutet das:

1. es gibt einen formalisierten Szenario-Katalog,
2. aus diesem Katalog lassen sich deterministische Soll-Artefakte ableiten,
3. Release-Gates pruefen diese Artefakte,
4. TradingView-Validierung bleibt auf compile, add-to-chart und runtime
   fokussiert,
5. Fehlerbilder benennen das betroffene Szenario statt nur einen generischen
   Gate-Fail.

## Arbeitsannahmen

1. Es wird keine zweite Pine-Engine gebaut.
2. Evidence liegt generator- und gate-seitig, nicht in einer Live-Python-
   Bridge.
3. Dashboard und Mobile Surface bleiben Consumer und nicht Quelle der
   Evidence-Definition.
4. TradingView-Validierung prueft Nutzerpfade; Input-Surface-Vertraege bleiben
   lokal und testseitig abgesichert.
5. Manifest-backed Artefakte bleiben bevorzugte Quelle gegen stale oder lokale
   Schattenartefakte.

## Must-Ship Ticket Overview

| ID | Prioritaet | Ticket | Primaere Dateien | Warum dieses Ticket im ersten Slice sein muss |
| --- | --- | --- | --- | --- |
| WS1-FT-01 | P0 | Scenario Catalog Contract | `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`, `scripts/run_smc_release_gates.py`, `scripts/run_smc_post_release_validation.py` | Ohne kanonische Faelle bleibt Evidence unscharf und nicht gate-faehig. |
| WS1-FT-02 | P0 | Deterministic Evidence Fixtures | `scripts/generate_smc_micro_base_from_databento.py`, `scripts/generate_smc_micro_profiles.py`, `reports/smc_structure_artifacts/` | Ohne Soll-Artefakte kann kein semantischer Drift reproduzierbar erkannt werden. |
| WS1-FT-03 | P0 | Release Gate Evidence Hook | `scripts/run_smc_release_gates.py`, `.github/workflows/smc-release-gates.yml` | Erst hier wird Evidence release-wirksam statt nur dokumentiert. |
| WS1-FT-04 | P0 | Runtime-Only TV Validation Normalization | `scripts/run_smc_post_release_validation.py`, `scripts/verify_tradingview_post_release.py`, `.github/workflows/smc-release-gates.yml` | Ohne klare Compile/Add/Runtime-Fokussierung bleibt TV-Validation an instabilen UI-Annahmen haengen. |
| WS1-FT-05 | P1 | Evidence Failure Reporting | `scripts/run_smc_release_gates.py`, `scripts/run_smc_post_release_validation.py` | Ein Gate ohne szenariobezogene Fehlerausgabe ist operativ zu teuer und zu langsam im Debug. |

## WS1-FT-01 - Scenario Catalog Contract

- Ziel: die kleinste kanonische Liste von Pine-Kernfaellen als wiederverwendbare
  Gate-Eingabe definieren.
- Liefert gegen den Backlog:
  - konkretisiert `ENG-WS1-01`
- Scope:
  - BOS bullish continuation
  - CHoCH reclaim into long bias
  - OB reclaim with valid trigger
  - FVG fill with actionable follow-through
  - stale or degraded context leading to watch or avoid
  - blocked or no-trade state
- Primaere Dateien:
  - `scripts/run_smc_release_gates.py`
  - `scripts/run_smc_post_release_validation.py`
  - begleitende WS1-Doku
- Definition of Done:
  - pro Szenario existieren Name, Eingangsannahmen, erwarteter Produktzustand,
    erwartete Aktion und sichtbarer Degradierungsgrund,
  - die Szenarien koennen in Release- und Post-Release-Validation referenziert
    werden,
  - die Szenarien verwenden Produktsprache statt interner Debug-Bezeichner.

## WS1-FT-02 - Deterministic Evidence Fixtures

- Ziel: aus dem Szenario-Katalog feste Soll-Artefakte erzeugen, die im Repo und
  in CI vergleichbar sind.
- Liefert gegen den Backlog:
  - konkretisiert `ENG-WS1-02`
- Scope:
  - deterministische Fixture-Inputs
  - manifest-backed Soll-Artefakte
  - klarer Pfad von Generator zu Gate-Artefakt
- Primaere Dateien:
  - `scripts/generate_smc_micro_base_from_databento.py`
  - `scripts/generate_smc_micro_profiles.py`
  - `scripts/run_smc_pre_release_artifact_refresh.py`
  - `reports/smc_structure_artifacts/`
- Definition of Done:
  - pro Kernszenario existiert ein reproduzierbares Soll-Artefakt,
  - Artefakte werden ueber manifest-backed Pfade aufgeloest,
  - lokale Scratch- oder stale Schattenartefakte koennen die Evidence-Lage
    nicht still ueberlagern.

## WS1-FT-03 - Release Gate Evidence Hook

- Ziel: semantische Drift im Release-Pfad blockieren.
- Liefert gegen den Backlog:
  - konkretisiert `ENG-WS1-03`
- Scope:
  - Evidence-Vergleich in den harten Release-Gates
  - Trennung zwischen Code/Data-Fehlern und externer TV-Drift bleibt erhalten
  - Gate-Report enthaelt expliziten Evidence-Abschnitt
- Primaere Dateien:
  - `scripts/run_smc_release_gates.py`
  - `.github/workflows/smc-release-gates.yml`
- Definition of Done:
  - Release-Gates pruefen kanonische Szenarien gegen Soll-Artefakte,
  - semantische Abweichungen blockieren den strukturellen Pass,
  - der Report benennt Szenario, erwarteten Zustand und beobachtete
    Abweichung.

## WS1-FT-04 - Runtime-Only TV Validation Normalization

- Ziel: die TradingView-Live-Validation auf belastbare Nutzerpfade reduzieren.
- Liefert gegen den Backlog:
  - konkretisiert `ENG-WS1-04`
- Scope:
  - compile
  - add to chart
  - readonly runtime validation
  - keine sichtbare Input-Tab-Pruefung als harte Release-Vorbedingung
- Primaere Dateien:
  - `scripts/run_smc_post_release_validation.py`
  - `scripts/verify_tradingview_post_release.py`
  - `.github/workflows/smc-release-gates.yml`
- Definition of Done:
  - Post-Release-Validation prueft compile, add und runtime,
  - fehlende sichtbare Input-Tabs fuer Dashboard oder SkippALGO sind kein
    Blocker im Live-Gate,
  - externe TradingView-Drift und interne Code/Data-Fails bleiben sauber
    klassifiziert.

## WS1-FT-05 - Evidence Failure Reporting

- Ziel: die neue Evidence-Lane operativ nutzbar machen.
- Liefert gegen den Backlog:
  - vertieft `ENG-WS1-03` und `ENG-WS1-04`
- Scope:
  - Gate-Fehler auf Szenarioebene
  - klare Diagnosepfade fuer missing evidence vs semantic drift
  - Follow-up-freundliche Report-Felder
- Primaere Dateien:
  - `scripts/run_smc_release_gates.py`
  - `scripts/run_smc_post_release_validation.py`
- Definition of Done:
  - Failure-Reports nennen Szenario-ID, Drift-Typ und primaeren Blocker,
  - missing-artifact, stale-manifest und semantic-drift sind getrennt lesbar,
  - Operator muessen nicht erst rohe CI-Logs lesen, um den Fehlerpfad zu
    verstehen.

## Suggested Delivery Order

1. WS1-FT-01 Scenario Catalog Contract
2. WS1-FT-02 Deterministic Evidence Fixtures
3. WS1-FT-03 Release Gate Evidence Hook
4. WS1-FT-04 Runtime-Only TV Validation Normalization
5. WS1-FT-05 Evidence Failure Reporting

## Executive Release Rule

Wenn ein WS1-Ticket zwar neue Artefakte oder Diagnosen erzeugt, aber keine
reproduzierbare Aussage ueber einen konkreten Pine-Kernfall in Release oder
Post-Release-Validation ermoeglicht, dann ist es kein First-Ticketset-Element
dieser Evidence-Lane.
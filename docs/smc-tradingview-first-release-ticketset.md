# SMC First-Release Ticketset

## Status

Released

## Zweck

Dieses Dokument schneidet aus PRD, Backlog und Screen Spec das kleinste
wirklich auslieferbare Ticketset fuer das erste Decision-First-Release der
drei SMC-TradingView-Surfaces heraus.

## Source Documents

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc-tradingview-screen-spec.md`
- `docs/smc-lite-pro-product-cut.md`

## First-Release Definition

Das First Release ist erreicht, wenn ein normaler Nutzer auf den drei
betroffenen SMC-Surfaces in wenigen Sekunden lesen kann:

1. was die aktuelle Hauptaktion ist,
2. warum diese Aktion jetzt plausibel ist,
3. welches Hauptrisiko aktiv ist,
4. wie Core, Dashboard und Long Strategy zusammenhaengen.

## Arbeitsannahmen

1. Es wird keine neue Signal-Engine gebaut.
2. Bestehende Core-Logik bleibt funktional intakt.
3. Dashboard und Long Strategy bleiben Consumer des Core-BUS.
4. Die erste Release-Welle deckt genau diese drei SMC-Surfaces ab.

## Must-Ship Ticket Overview

| ID | Prioritaet | Ticket | Surfaces | Warum es im First Release sein muss |
| --- | --- | --- | --- | --- |
| FR-01 | P0 | Shared Action And Plan Contract | Core, Dashboard, Long Strategy, Docs | Ohne gemeinsame Produktsprache zerfaellt die UX in drei Teilprodukte. |
| FR-02 | P0 | Lite Input Gate | Core, Dashboard, Long Strategy | Ohne Input-Cut bleibt der Produkt-Eindruck laborhaft. |
| FR-03 | P0 | SMC Core Hero Surface Cut | `SMC_Core_Engine.pine` | Der Core braucht eine echte Lite-Hauptflaeche. |
| FR-04 | P0 | Dashboard Compact Detail Default | `SMC_Dashboard.pine` | Das Dashboard muss Entscheidung erklaeren statt Diagnose dominieren. |
| FR-05 | P0 | Long Strategy Wrapper Surface | `SMC_Long_Strategy.pine` | Der Strategy-Wrapper braucht eine klare Setup- und Execution-Lesart. |
| FR-06 | P0 | Strategy Binding And Plan Clarity | `SMC_Long_Strategy.pine`, Docs | BUS-Bindung und Trade-Plan duerfen keine implizite Wissensfalle sein. |
| FR-07 | P0 | Core / Dashboard / Strategy Parity | Core, Dashboard, Long Strategy | Plan-Level und Begriffe duerfen sich zwischen den drei SMC-Surfaces nicht widersprechen. |
| FR-08 | P0 | Release Validation And Documentation | alle drei, Docs | Ohne Guide-, Contract- und Visual-QA ist der UX-Cut nicht release-faehig. |

## Delivered In R1.1

| ID | Prioritaet | Ticket | Repo-Status |
| --- | --- | --- | --- |
| FR-09 | P1 | Dashboard Pro Row Regrouping | Ausgeliefert ueber die R1.1-Pro-Sektionsgliederung in `SMC_Dashboard.pine`. |
| FR-10 | P1 | Preset Migration Hardening | Ausgeliefert ueber die Safe-Default- und Decision-First-Migrationshaertung fuer Core, Dashboard und Strategy-Wrapper. |
| FR-11 | P1 | Operator Binding Workflow Cleanup | Ausgeliefert ueber Guide-, BUS-Binding- und Companion-Workflow-Dokumentation. |

## FR-01 - Shared Action And Plan Contract

- Ziel: Ein gemeinsames Action-, Risk- und Plan-Vokabular fuer die drei
  SMC-Surfaces festziehen.
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SMC_Dashboard.pine`
  - `SMC_Long_Strategy.pine`
  - Doku
- Definition of Done:
  - Core und Dashboard zeigen denselben Product State.
  - Die Long Strategy liest sich wie Wrapper auf denselben Plan-Leveln.

## FR-02 - Lite Input Gate

- Ziel: Den sichtbaren Standard-Input-Surface pro Skript auf echte
  Produktsteuerung reduzieren.
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SMC_Dashboard.pine`
  - `SMC_Long_Strategy.pine`
- Definition of Done:
  - Lite zeigt pro Surface maximal 10 direkt sichtbare Standard-Inputs.
  - Operator-Bindings sind klar getrennt von Produktsteuerung.

## FR-03 - SMC Core Hero Surface Cut

- Ziel: Den bestehenden Compact-Mode in eine echte Hero-Surface ueberfuehren.
- Hauptartefakt:
  - `SMC_Core_Engine.pine`
- Definition of Done:
  - Core-Lite ist in <= 5 Sekunden lesbar.
  - Risk-Linien erscheinen nur bei reifem Setup oder aktiver Position.

## FR-04 - Dashboard Compact Detail Default

- Ziel: Das Dashboard standardmaessig in einen Compact Detail Screen drehen.
- Hauptartefakt:
  - `SMC_Dashboard.pine`
- Definition of Done:
  - Default-Detail hat maximal 8 Kernzeilen.
  - Pro bleibt verfuegbar.
  - BUS-Terminologie taucht in der Lite-Default-Surface nicht mehr sichtbar auf.

## FR-05 - Long Strategy Wrapper Surface

- Ziel: Die sichtbare Strategy-Wrapper-Surface auf klare Setup- und
  Execution-Steuerung fokussieren.
- Hauptartefakt:
  - `SMC_Long_Strategy.pine`
- Scope:
  - `Entry Mode`
  - `Min Quality Score`
  - `Take Profit R`
  - `Use Take Profit`
- Definition of Done:
  - Die Wrapper-Flaeche ist ohne Guide lesbar.
  - Strategy-Setup und Binding-Flaeche sind getrennt erkennbar.

## FR-06 - Strategy Binding And Plan Clarity

- Ziel: Die BUS-Bindung und Plan-Level des Wrappers operator-tauglich und
  deterministisch dokumentieren.
- Hauptartefakte:
  - `SMC_Long_Strategy.pine`
  - Doku
- Definition of Done:
  - Die top-to-bottom Binding-Reihenfolge ist explizit.
  - Trigger, Invalidation und Take-Profit widersprechen dem Core nicht.

## FR-07 - Core / Dashboard / Strategy Parity

- Ziel: Dieselben Plan-Level und Begriffe in allen drei Surfaces.
- Hauptartefakte:
  - `SMC_Core_Engine.pine`
  - `SMC_Dashboard.pine`
  - `SMC_Long_Strategy.pine`
- Definition of Done:
  - Core, Dashboard und Strategy widersprechen sich nicht.
  - Pro Bar gibt es keine konkurrierenden Nutzerbotschaften zwischen Core und
    den Companion-Surfaces.

## FR-08 - Release Validation And Documentation

- Ziel: Den UX-Cut als release-faehiges SMC-Paket absichern.
- Hauptartefakte:
  - Doku
  - manuelle Validation
- Definition of Done:
  - Die drei Surfaces sind dokumentiert.
  - Screenshots, Guides und Contract-Tests sind abgeglichen.

## Suggested Delivery Order

1. FR-01 Shared Action And Plan Contract
2. FR-02 Lite Input Gate
3. FR-03 SMC Core Hero Surface Cut
4. FR-04 Dashboard Compact Detail Default
5. FR-05 Long Strategy Wrapper Surface
6. FR-06 Strategy Binding And Plan Clarity
7. FR-07 Core / Dashboard / Strategy Parity
8. FR-08 Release Validation And Documentation

## Executive Release Rule

Wenn ein Ticket die Diagnose verbessert, aber nicht die schnellere,
vertrauenswuerdigere Nutzerentscheidung oder das deterministische
Strategy-Setup auf einer der drei SMC-Surfaces, dann ist es kein
First-Release-Ticket.

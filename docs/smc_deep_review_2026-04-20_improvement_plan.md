# SMC Deep Review 2026-04-20: Improvement Plan

Stand: 2026-04-20
Quelle: externer Review `smc-deep-review-2026-04-20.md`
Status: aktiv, ohne Zeitvorgaben

## Zweck

Dieses Dokument uebersetzt die Findings aus dem Deep Review in einen
repo-kompatiblen Improvement Plan.

Es ist bewusst kein neues PRD und kein Ersatz fuer die bestehende Q3-Strategie.
Es dient als Bruecke zwischen:

- dem externen Review,
- dem aktuellen `main`-Stand,
- der bereits laufenden Q3-Umsetzung,
- und den naechsten konkreten Engineering-Schritten.

Das Dokument trennt deshalb klar zwischen:

- bereits geschlossenen oder teilweise geschlossenen Review-Findings,
- weiterhin offenen Produkt- und Technikluecken,
- und der empfohlenen Umsetzungsreihenfolge ohne Kalenderbindung.

## Verknuepfte Dokumente

- `docs/STRATEGY_2026_Q3.md`
- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc-tradingview-decision-first-backlog.md`
- `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`
- `docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md`
- `docs/smc_deep_review_2026-04-20_hero_surface_implementation_preparation.md`
- `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`

## Re-Baselining gegen den aktuellen Repo-Stand

Der Review ist in seiner strategischen Hauptrichtung korrekt, aber ein Teil der
kritisierten Luecken ist auf dem heutigen `main`-Stand nicht mehr gruenfeldig.

Der aktuelle Stand ist:

- Phase F zur kontextuellen Kalibrierung ist im Repo vorhanden.
- Phase G fuer den Feature-Importance-zu-Scorer-Tuning-Pfad ist als
  Infrastruktur vorhanden.
- Phase H fuer Pine Consumer Maturity ist teilweise umgesetzt und dokumentiert.

Offen bleiben aber weiterhin die fuer den Nutzer wichtigsten Luecken:

- fehlende reproduzierbare Evidenz fuer die Pine-Kernentscheidungslogik,
- unzureichend sichtbare Freshness- und Trust-Kommunikation am Chart,
- fehlende Produktverdichtung auf eine klar lesbare Decision-First-Surface,
- noch nicht aktivierte Outcome-, Feature-Importance- und OV7-Experiment-Loops,
- sowie operative Fragilitaet in Refresh-, Validation- und Publish-Pfaden.

## Leitprinzipien

1. Kein grosser Pine-zu-Python-Live-Bridge-Umbau als kurzfristige Prioritaet.
2. Keine neue Schattenlogik zwischen Engine, Dashboard und generierten
   Profilen.
3. Decision-first vor Diagnose-first.
4. Freshness und Trust sind Produktsignale, nicht nur Audit-Metadaten.
5. Operator-only- und Endnutzer-Surfaces bleiben klar getrennt.
6. Evidence vor Scope-Expansion.
7. Operative Stabilitaet vor neuer Komplexitaet.

## Workstream-Ueberblick

| Workstream | Zielbild | Hauptergebnis | Primaere Repo-Anker |
| --- | --- | --- | --- |
| WS1 Pine Evidence Lane | Pine-Kernlogik wird reproduzierbar belegbar | kanonische Szenarien plus Evidence-Gates | `scripts/run_smc_release_gates.py`, `scripts/run_smc_post_release_validation.py`, `SMC_Dashboard.pine` |
| WS2 Trust And Freshness UX | Frische und Vertrauenslage werden am Setup sichtbar und handlungsrelevant | einheitlicher Trust-State plus degradierte Handlung | `smc_integration/provider_health.py`, `smc_tv_bridge/provider_status.py`, `scripts/generate_smc_micro_profiles.py`, `SMC_Dashboard.pine` |
| WS3 Hero Surface | Marktmodus, Setup-Qualitaet und Handlung werden in einem Blick lesbar | decision-first Default-Surface | `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`, `pine_input_surface.py` |
| WS4 Scorer Tuning Activation | Phase G wird von Infrastruktur zu echtem Verbesserungsloop | Backfill, FI-Report, Candidate Weights, OV7-Vergleich | `open_prep/outcome_backfill.py`, `open_prep/outcomes.py`, `open_prep/scorer.py`, `scripts/smc_ab_experiment.py`, `scripts/run_ab_comparison.py` |
| WS5 Release And Refresh Hardening | produktive Pfade werden robuster und weniger stale-anfaellig | manifestbasierte Refresh- und Validation-Haertung | `.github/workflows/smc-library-refresh.yml`, `.github/workflows/smc-release-gates.yml`, `scripts/run_smc_pre_release_artifact_refresh.py`, `smc_integration/provider_health.py` |
| WS6 Product Consolidation | Systemtiefe wird als klares Produkt statt als Feature-Sammlung praesentiert | reduzierte Surface, klare Produktgrenzen, Legacy-Konsolidierung | `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`, `pine_input_surface.py`, relevante SMC-Doku |

## Workstream 1 - Pine Evidence Lane

### Ziel

Die groesste offene Schwaeche aus dem Review ist nicht fehlende Governance,
sondern fehlende reproduzierbare Evidenz fuer die Pine-Kernentscheidungen.

### Fokus

- kanonische Entscheidungsszenarien definieren,
- deterministische Soll-Artefakte ableiten,
- Evidence-Gates in Release- und Post-Release-Validierung einhaengen,
- TradingView-Preflight auf reale compile/add/runtime-Pfade normalisieren.

### Ergebnisdefinition

Der Workstream ist abgeschlossen, wenn definierte Kernfaelle wie BOS,
Sweep-Reclaim, FVG-Fill, HTF-aligned Setup und stale-context-Degradierung als
reproduzierbare Evidence-Lage im Repo und in den Gates verankert sind.

## Workstream 2 - Trust And Freshness UX

### Ziel

Freshness und Provider-Vertrauen muessen vom Audit-Detail in die sichtbare
Entscheidungsoberflaeche wandern.

### Fokus

- ein einheitliches Trust-State-Modell,
- Export dieser Zustandslage in den Pine-Pfad,
- sichtbare Badges und Handlungsauswirkungen,
- SLA- und Freshness-Gates in Refresh und Release.

### Ergebnisdefinition

Der Nutzer sieht jederzeit, ob der aktuelle Kontext voll belastbar,
eingeschraenkt oder nur watch-only ist, und das System degradiert die
Handlungsempfehlung entsprechend.

## Workstream 3 - Hero Surface

### Ziel

Das Produkt soll seine Ueberlegenheit nicht nur technisch besitzen, sondern in
wenigen Sekunden sichtbar machen.

### Fokus

- Marktmodus,
- Setup-Qualitaet,
- Handlung,
- Why now,
- Main risk,
- klare Trennung zwischen Compact Detail, Pro Diagnostics und operator-only.

### Ergebnisdefinition

Die Standardansicht ist in wenigen Sekunden lesbar und kommuniziert zuerst die
Entscheidung und erst danach Diagnose.

Siehe hierzu auch:

- `docs/smc-tradingview-decision-first-prd.md`
- `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`

## Workstream 4 - Scorer Tuning Activation

### Ziel

Phase G ist infrastrukturell angelegt, aber noch nicht als echter
Produktionsloop aktiviert.

### Fokus

- Outcome-Backfill automatisieren,
- Feature-Importance-Artefakte laufend erzeugen,
- Candidate Weight Sets erzeugen und drift-pruefen,
- statisch vs. auto-tuned per OV7 vergleichen,
- Promotion-Entscheid nicht implizit, sondern explizit machen.

### Ergebnisdefinition

Es existiert ein reproduzierbarer Loop von gelabelten Outcomes ueber FI-Report
und Candidate Weights bis zum OV7-Vergleich und einer klaren Promote/Hold/
Rollback-Entscheidung.

## Workstream 5 - Release And Refresh Hardening

### Ziel

Die operative Kette zwischen Refresh, Release-Gates, Validation und Publish
muss weniger fragile Einzelpfade und weniger stale batch artifacts enthalten.

### Fokus

- manifestbasierte Artefaktaufloesung,
- stale-batch-Schutz,
- idempotente Retry-Pfade fuer TradingView,
- produktwirksame Provider-Health,
- Post-Release-Validierung entlang echter Nutzerpfade.

### Ergebnisdefinition

Produktive Runs sind robuster, besser nachvollziehbar und konsistenter gegen
lokale oder veraltete Artefaktlagen abgesichert.

## Workstream 6 - Product Consolidation

### Ziel

Das System soll sich als Entscheidungsmaschine praesentieren, nicht als lose
Feature- und Surface-Sammlung.

### Fokus

- klare Definition unterstuetzter Produktflaechen,
- Input- und Surface-Reduktion,
- gemeinsame Produktsprache,
- Legacy-Klassifikation und spaetere Konsolidierung.

### Ergebnisdefinition

Die aktive Produktoberflaeche ist klar erkennbar, die Default-Surface ist
verdichtet und historische oder experimentelle Varianten verwischen den
Produktkern nicht mehr.

## Empfohlene Reihenfolge ohne Zeitvorgaben

### Prioritaet A

- WS1 Pine Evidence Lane
- WS2 Trust And Freshness UX
- WS5 Release And Refresh Hardening

Begruendung:

Ohne Evidenz, sichtbare Trust-Lage und robuste operative Pfade bleibt jede
weitere Produktverdichtung kosmetisch oder fragil.

### Prioritaet B

- WS3 Hero Surface
- WS4 Scorer Tuning Activation

Begruendung:

Sobald Trust, Evidence und operative Baseline belastbar sind, lohnt sich die
starke Entscheidungssurface und der echte Vergleich zwischen statischem und
auto-tuned Scorer.

### Prioritaet C

- WS6 Product Consolidation

Begruendung:

Konsolidierung sollte auf stabilen Kernflaechen und belegbarer Produktlogik
aufbauen, nicht vorher.

## Programmweite Gates

| Gate | Bedeutung | Eintrittskriterium |
| --- | --- | --- |
| G-A Evidence Ready | Pine-Kernfaelle sind belegbar | WS1 liefert kanonische Szenarien plus Release-Gate-Hook |
| G-B Trust Visible | Trust und Freshness sind produktsichtbar | WS2 liefert sichtbare Zustandslage plus Action-Degradierung |
| G-C Hero Ready | Hero Surface ist belastbar | WS3 ist ohne Schattenlogik und mit lesbarer Default-Surface umgesetzt |
| G-D Experiment Ready | Phase G ist operativ aktivierbar | WS4 liefert laufenden Backfill-, FI- und OV7-Pfad |
| G-E Consolidation Ready | Portfolio-Klarheit lohnt sich | WS1 bis WS5 sind hinreichend stabil und sichtbar |

## Definition of Done auf Programmebene

Das Deep-Review-Programm gilt als erfolgreich, wenn gleichzeitig gilt:

- Pine-Kernentscheidungen sind fuer definierte Kernfaelle reproduzierbar
  evidenzbasiert abgesichert.
- Trust und Freshness sind in der Oberflaeche sichtbar und degradieren die
  Handlung explizit.
- Die Standardoberflaeche kommuniziert Marktmodus, Setup-Qualitaet und Aktion
  in einem Blick.
- Der FI-zu-Scorer-zu-OV7-Loop laeuft mit echten gelabelten Daten.
- Refresh, Release-Gates und Post-Release-Validation sind robuster als heute.
- Das Produkt liest sich als Entscheidungsmaschine und nicht als lose Feature-
  Sammlung.

## Weiterfuehrende Umsetzungsdokumente

- Detaillierter Ticket-Backlog:
  `docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md`
- Fokusdokument fuer Pine- und Dashboard-Umsetzung:
  `docs/smc_deep_review_2026-04-20_hero_surface_plan.md`
- MTF-Scope-Entscheidung (2.8, 2026-04-21 Accepted):
  `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md` —
  dokumentiert warum der 3-Ebenen-HTF-Stack (4H / 1D / 1W) + adaptiver IPDA
  bleibt und ausschliesslich die Chart-TF-Benchmark-Abdeckung (5m + 4H)
  erweitert wird. Eine Flux-style 7-TF-Kopie wird explizit abgelehnt.
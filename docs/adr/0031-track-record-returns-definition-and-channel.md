# ADR-0031: Returns-Definition und Publish-Kanal für Track-Record-Gate (C6/C7) und Regime-Stratifikation (C5)

- **Status:** accepted (2026-07-29)
- **Owner-Entscheidung:** delegiert 2026-07-29 („mach weiter: … die bekannte Owner-Entscheidung (Returns-/Trade-Definition + Cache-Kanal, D1/C5)")
- **Kontext:** Dead-Dataflow-Sweeps 2026-07-28/29; Blocker dokumentiert in
  `scripts/build_track_record_gate.py` (D1) und `scripts/regime_stratified_inference.py` (C5)

## Problem

Das C6/C7-Track-Record-Gate und die C5-Regime-Stratifikation waren end-to-end
unverdrahtet, blockiert auf zwei als Owner-Entscheidung reservierten Fragen:

1. **Returns-/Trade-Definition** — es existierte keine persistierte
   Per-Trade-Returns-Serie; die Wahl der Definition ist Methodik, nicht Plumbing.
2. **Persist-Kanal** — der ursprünglich geplante Konsument
   (`streamlit_dashboard.py`, `Dockerfile.dashboard`) liest `cache/` aus einem
   Out-of-band-Mount, den kein In-Repo-Manifest befüllt; der Datums-Anker
   `walk_forward_<date>.json` wurde nie produziert.

## Entscheidung 1: Returns-Definition = Variante A über den akkumulierten FamilyEvent-Pool

Die Serie ist `governance.family_returns.extract_family_returns` (Variante A,
`touch_then_horizon_close`): Entry Zonen-Mittelpunkt beim ersten Touch (Level-
Familien: immediate), Exit am Close nach `family_outcome_horizon(family)` Bars,
minus fixe Round-Turn-Kosten (`DEFAULT_COST_BPS = 5.0`); ungetriggerte Setups
sind keine Trades. Input ist der akkumulierte FamilyEvent-Pool
(`accumulated_family_events.json`), plane-gefiltert auf die governete 1D-Ebene —
exakt wie im täglichen Promotion-Gate.

**Warum:**

- Es ist die **einzige** Definition im Repo mit echter Entry/Exit/Kosten-Semantik,
  und sie ist seit 2026-07-06 de-facto produktiv: `promotion-gate-daily`
  bewertet damit täglich Direction-Edge (PSR/MinTRL/BH-FDR). Eine repo-weit
  einheitliche Definition — das Gate misst dieselbe Population, die das
  Promotion-Gate misst; keine zweite Skala, die driften kann.
- Konservativ mit minimalen Freiheitsgraden („hard to flatter"); Wechsel der
  Regel bleibt lt. `family_returns.py` ein expliziter, reviewter Code-Change.
- Der Status „chosen autonomously, pending review" in `family_returns.py` wird
  durch dieses ADR zu „reviewed & blessed for gate use" aufgelöst; die
  Formulierung dort bleibt als Historie stehen.

**Verworfene Alternativen:**

- `artifacts/open_prep/outcomes/` (540 Records, committed): laut eigener Doku
  **kostenfreies Mark-to-Market ohne Exit** („read these numbers as an upper
  bound"), 300/540 ohne `direction` (Legacy-long-only-Bias). Als „Track Record"
  in einem öffentlichen Report wäre das eine methodische Falschauszeichnung.
  Bleibt Signal-Qualitäts-Korpus (Hit-Rates, FI, Kalibrierung).
- `cache/live/incubation_*.jsonl` (C8 Paper-Trades): die langfristig **richtige**
  Quelle (echte Fills/Exits), aber aktuell n=2 geschlossene Trades.
  **Upgrade-Pfad:** sobald die Phase-A-Inkubation genug geschlossene Trades hat,
  soll eine `returns_by_variant`-Serie aus den Inkubations-Outcomes die
  Variante-A-Serie im Gate ERGÄNZEN (separate Variante, nie stiller Ersatz).
- `walk_forward_runner`-OOS-Returns: reine In-Memory-Library ohne
  Input-Definition; kein eigenständiger Korpus.

**Disclosure-Pflicht:** Die Serie misst „net returns *given a triggered setup*"
— kein Portfolio-P&L, kein Sizing, kein Slippage-Modell über die 5 bps hinaus.
Jedes Artefakt trägt einen `measurement`-Block mit Regel, Kosten und dieser
Einordnung; `emit_public_calibration_report` reicht ihn durch.

## Entscheidung 2: Regime-Tag = point-in-time Event-Regime (TRENDING/RANGING/NEUTRAL)

C5 stratifiziert über `extract_family_regime_samples`: nur Events, die
getriggert haben UND ein point-in-time `regime`-Label tragen (EV#7,
`governance.family_event_score.point_in_time_regime`) — Regimes werden nie
erfunden. Die Makro-Taxonomie (RISK_ON/OFF/ROTATION/NEUTRAL aus open_prep)
bleibt außen vor, bis eine reviewte Join-Definition (Event-Anchor → Makro-Regime
des Tages) existiert; der `unknown_share`-Anteil (getriggerte Trades ohne Tag)
wird im Aggregat ausgewiesen.

## Entscheidung 3: Kanal = committete `docs/calibration/gates/` + Public-Report

`promotion-gate-daily` (14:00 UTC) schreibt drei Artefakte nach
`docs/calibration/gates/` und committet sie per Bot-Branch + Auto-Merge-PR
(Muster: `run-open-prep-daily`): `returns_series_<date>.json`,
`track_record_gate_<date>.json`, `regime_stratified_<date>.json`
(Retention: neueste 90 pro Familie). Der 04:30-UTC-Lauf von
`public-calibration-dashboard` lädt die jeweils neuesten davon fail-soft und
bettet sie als additive Keys (`track_record_gate` 1.1.0, `regime_stratified`
1.2.0) in den Public-Report ein — der bereits verdrahtete, SHA-verifizierbare
Kanal (committed + GH Pages).

**Verworfen:** Der `cache/calibration/`-Docker-Mount-Kanal
(`streamlit_dashboard.py`) bleibt **unverdrahtet**; ob dieses separate Image
überhaupt weiterleben soll, ist eine eigene Ops-Entscheidung. Der Datums-Anker
`walk_forward_<date>.json` wird weiterhin nicht produziert —
`build_dashboard_payload` bleibt dadurch inert (unverändert ehrlich).

## Ehrlichkeits-Semantik (bewusst)

- Gate-Verdicts starten **red** (aktuell ~100 Trades, Checks teils `None`);
  Regime-Report startet **insufficient_data** (39 regime-getaggte Trades,
  Floor 30 pro Regime). Das ist der korrekte Zustand, kein Fehler —
  „not measured" statt fabriziertem Grün.
- Leerer/expiriter Pool ⇒ leere Serie, **kein** Gate-File (das Gate weigert
  sich by design bei n=0/Zero-Varianz); der Public-Report lässt die Keys weg.

## Konsequenzen

- `scripts/build_returns_series.py` + `scripts/build_regime_stratified_report.py`
  sind die Producer; `scripts/build_track_record_gate.py` ist erstmals
  scheduled; `scripts/regime_stratified_inference.py` +
  `scripts/regime_stratification.py` haben erste Produktions-Caller.
- Docstring-Wiring-Status in den betroffenen Modulen und die C5-/C9-Plan-Notes
  sind auf diesen Stand aktualisiert.
- Schema-Pin `v1.3.0_public_schema_pin.json` re-pinned (Docstring-Update in
  `build_public_report`; additive Felder, kein Version-Bump).

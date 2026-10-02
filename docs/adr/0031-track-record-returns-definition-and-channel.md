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
(Retention: neueste 90 pro Familie). Der 22:00-UTC-Lauf von
`c13-daily-cron` (Step 5b) lädt die jeweils neuesten davon fail-soft und
bettet sie als additive Keys (`track_record_gate` 1.1.0, `regime_stratified`
1.2.0) in den Public-Report ein — der bereits verdrahtete, SHA-verifizierbare
Kanal (committed + GH Pages).

> **2026-07-31 (issue #298):** Dieser Einbettungs- UND Commit-Schritt lag bis
> dahin bei `public-calibration-dashboard` (04:30 UTC), das inzwischen entfernt
> ist. Grund: nur `c13-daily-cron` ruft den Emitter mit `--include-families`
> auf, und der Dashboard-Lauf committete danach eine Fassung **ohne**
> `families[]` — womit `check_c12_trigger` dauerhaft
> `families inspected: 0` sah. Die Gate-Artefakte werden jetzt am selben Tag
> eingebettet (14:00 → 22:00 UTC) statt am Folgemorgen.

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

## Nachtrag 2026-10-01: 15m-Beobachtungsebene und wachsendes Trade-Ledger

- **Status:** accepted (Owner-Entscheidung 2026-10-01)
- **Ändert nicht:** Entscheidung 1–3. Die governte 1D-Serie, ihr Gate, ihr
  Regime-Report und ihr Weg in den Public-Report bleiben, wie sie sind.

### Anlass (gemessen 2026-10-01)

Die Frage „welche Familie trägt einen Edge" ließ sich aus den Artefakten dieses
ADR nicht beantworten, und zwar aus zwei Gründen, die nichts mit den Familien
zu tun haben:

1. **Die Serie ist ein Fenster.** Der Pool ist ein rollendes 30-Tage-Fenster
   (`accumulate_family_events.py --max-age-days 30`), die Tagesserie damit
   auch. Über die zwölf committeten Berichte vom 14.–28.8. trug sie 29–34
   Trades, am 21.9. 27, im Pool vom 30.9. 19. Vorregistriert sind 120–200 je
   Familie (`governance/edge_hypotheses.json`), der Floor des Track-Record-Gates
   liegt bei 100, der von §5 bei 40. Ein Fenster dieser Größe erreicht keine
   davon, gleich wie lange es läuft.
2. **Der 1D-Filter lässt fast nichts durch.** Am 21.9. lagen 28 von 8 065
   Pool-Events auf 1D. Der Pool trägt seit #2667 täglich alle Ebenen; die
   Messung sah davon ein Drittelprozent.

Eine dritte Ursache liegt im Pool selbst (Deduplizierung auf
`(family, anchor_ts)`, #5585) und ist nicht Gegenstand dieses ADR.

### Entscheidung 4: 15m ist eine zweite, getrennt ausgewiesene Beobachtungsebene

`promotion-gate-daily` rechnet dieselbe Variante-A-Regel zusätzlich auf den
15m-Events desselben Pools und committet die beiden Fenster-Urteile nach
`docs/calibration/gates/15m/` (`track_record_gate_<date>.json`,
`regime_stratified_<date>.json`, Retention 90). Die Fenster-Serie selbst bleibt
Lauf-Artefakt: gemessen 94 KB bei 551 Trades, und sie wiederholt täglich
dieselben rund 30 Tage, die das Ledger (Entscheidung 5) je Trade einmal hält.

**Was die 15m-Ebene nicht ist.** Die Rollen aus
`docs/governance/adr0023_plane_and_gate_clarification.md` gelten unverändert:

- Sie ist **kein Gate.** §5 (E[PnL] nach Kosten) bleibt das bindende Gate und
  bleibt auf 1D; auf 15m wird kein §5-Urteil gerechnet.
- Sie hat **keine Wirkung** auf Arming, Stage oder `armed_plane`, und sie
  belebt den eingefrorenen 15m-Magnitude-Proof nicht wieder (dessen AUC-Messung
  bleibt eingefroren).
- Sie geht **nicht** in den Claim-Tier (`docs/commercial/family_claim_status.json`)
  und **nicht** in den Public-Report ein.

Das Unterverzeichnis ist Teil der Entscheidung: alle 1D-Konsumenten lesen
`docs/calibration/gates/` nicht-rekursiv (c13 Step 5a
`returns_series_*.json`, der Emitter `<prefix>_*.json`, die 1D-Retention) und
sehen die 15m-Dateien nicht.

**Warum 15m.** Es ist die Ebene des einzigen echten Edge-Laufs (EV-20,
2026-07-06) und des Magnitude-Proofs — also die Ebene, auf der die bisherigen
positiven Aussagen überhaupt entstanden sind. Die Kosten sind ein Filter: der
Pool trägt die 15m-Events ohnehin, eine Pipeline wird nicht wiederbelebt.

**Offenlegung zur Wahl.** Vor der Festlegung wurde am 2026-10-01 ein
Schnappschuss über **alle** Ebenen gesehen (Pool vom 30.9., Anker 31.8.–23.9.,
dieselbe Regel). Auf 15m schloss dabei für keine Familie das 95-%-Intervall die
Null aus (n = 551); auf 5m und 10m für mehrere. 15m wurde nicht wegen dieses
Bildes gewählt, sondern trotz ihm — aber gewählt wurde danach. Deshalb trägt
das 15m-Ledger einen Evidenz-Start (Entscheidung 5).

### Entscheidung 5: ein wachsendes Ledger je Ebene

`scripts/accumulate_returns_ledger.py` hängt jeden abgeschlossenen Trade genau
einmal an eine committete JSONL an:
`docs/calibration/gates/ledger/returns_ledger_<Ebene>.jsonl` für `1D` und `15m`.

- **Schlüssel ist die `event_id`.** Trades ohne ID werden gezählt und nicht
  aufgenommen.
- **Nur anhängen.** Der Ertrag eines Trades ist endgültig, sobald er existiert
  (Entry beim ersten Touch, Exit einen festen Horizont später). Sieht ein
  späterer Lauf für dieselbe ID einen anderen Ertrag, bleibt der aufgezeichnete
  stehen, und der Lauf meldet den Widerspruch.
- **Eine Regel je Ledger.** Jede Zeile trägt `return_rule` und `cost_bps`. Ein
  Lauf mit anderer Regel oder anderen Kosten verweigert das Anhängen (rc 2,
  roter Schritt). Ein Regelwechsel bleibt ein expliziter, reviewter
  Code-Change — und beginnt eine neue Ledger-Datei.
- **Kumulatives Urteil.** Auf dem Ledger läuft dasselbe Track-Record-Gate
  noch einmal und schreibt `ledger/track_record_gate_<Ebene>.json`
  (überschrieben; die Historie ist das Ledger). Parität zur Fensterserie ist
  gemessen: für denselben Pool liefern beide je Familie dieselben Erträge
  (1D 19 = 19, 15m 551 = 551).
- **Evidenz-Start 15m = 2026-10-01.** 15m-Trades mit Anker davor bleiben im
  Ledger (es sind Tatsachen), zählen aber nicht ins kumulative Urteil. Als
  unberührte Vorwärts-Evidenz gilt auf 15m nur, was nach der Festlegung
  anfiel. 1D trägt keinen Evidenz-Start: die Ebene ist seit 2026-07-06
  festgelegt.

Eine fehlgeschlagene Beobachtungs- oder Ledger-Stufe reißt die 1D-Artefakte
des Tages nicht mit: der Commit-Schritt läuft mit `!cancelled()` weiter, der
Lauf bleibt rot.

### Was dieser Nachtrag nicht entscheidet

- Ob ein kumulatives Urteil je in den Public-Report oder den Claim-Tier
  eingeht. Das ist eine Entscheidung über Aussagen nach außen, keine über
  Verdrahtung.
- Ob §5 auf einer kumulativen Basis rechnen soll. §5 liest Events (Score und
  Ertrag), das Ledger hält Trades.
- Wie gleichzeitige Trades mehrerer Symbole zu gewichten sind. Sie sind
  querschnittlich korreliert; `n` im Ledger überschätzt die effektive
  Stichprobe.

### Größe

Gemessen: 290 Bytes je Ledger-Zeile (551 Zeilen = 157 KB). Der heutige Pool
liefert auf 15m rund 37 neue Trades je Handelstag, also etwa 11 KB täglich.
Mit dem korrigierten Pool-Schlüssel (#5585) ist auf 15m mit dem Zwölffachen zu
rechnen (2 133 statt 177 Trades aus denselben zwei Tagesdateien), also grob
130 KB täglich und rund 30 MB im Jahr.


## Nachtrag 2026-10-02: der Handelstag ist die Einheit, nicht der Trade

- **Status:** accepted (Owner-Entscheidung 2026-10-02)
- **Löst auf:** den dritten Punkt unter „Was dieser Nachtrag nicht
  entscheidet" des Nachtrags vom 2026-10-01 (Gewichtung gleichzeitiger Trades).
- **Ändert nicht:** Entscheidung 1–5. Trade-Definition, Ebenen, Ledger und
  Kanäle bleiben.

### Anlass (gemessen 2026-10-02)

Am ersten Tag nach #5585 las das 15m-Fenster-Urteil für alle vier Familien
`green` (n = 2 469, PSR ≈ 1,0); am Vortag war mit n = 634 keine Familie von
null unterscheidbar. Dazwischen lag keine neue Evidenz, sondern der neue
Pool-Schlüssel: er hält jedes Symbol als eigenen Trade.

- Die 2 490 Trades des 15m-Ledgers stammen aus 19 Handelstagen; auf einer
  einzigen Kerze liegen bis zu 56 (Median 2).
- Das kumulative 15m-Urteil las für SWEEP `green` auf 210 Trades, die alle
  am 2026-10-01 verankert sind.
- Die 170 Trades des 1D-Ledgers stammen aus 13 Handelstagen, bis zu 27 je Tag.

Das Gate zieht Trades in ihrer Reihenfolge (stationäre Blöcke der Länge 5) und
annualisiert mit Trades pro Jahr. Trades desselben Tages bewegen sich aber
gemeinsam. Tageweise gezogen bleibt auf 15m ein mäßig positiver Mittelwert für
BOS, OB und SWEEP (rund 9–12 bps je Trade, Untergrenzen 1–6 bps) und für FVG
ein Intervall durch die Null; auf 1D schließt kein Intervall die Null aus.

### Entscheidung 6: zwei Tages-Prüfungen im Track-Record-Gate

Die Serien tragen zu jedem Ertrag seinen Anker (`anchor_ts_by_variant`,
parallel zu `returns_by_variant`). `scripts/track_record_gate.py` rechnet
daraus zwei zusätzliche Prüfungen, je Familie und gepoolt:

| Prüfung | Wert | Schwelle |
|---|---|---|
| `trading_days` | Zahl verschiedener UTC-Kalendertage der Anker | ≥ 30 |
| `day_clustered_mean_ci_low` | untere 95-%-Grenze des mittleren Ertrags je Trade, wenn ganze Tage mit Zurücklegen gezogen werden (2 000 Züge) | > 0 |

Beide gehen in das Aggregat ein wie jede andere Prüfung (rot dominiert), und
beide sind Pflicht-Evidenz für `claimable`. Liefert ein Aufrufer keine Anker,
sind beide `skipped`; ein grünes Urteil ist dann nicht claimable und sagt in
`claim_note`, was fehlt. Eine Serie, die Anker nur für einen Teil der Familien
trägt, wird verweigert.

**Warum 30.** Ein über Tage gezogenes Intervall ist bei wenigen Tagen selbst
unzuverlässig; unter rund 30 Ziehungseinheiten unterschätzt es die Streuung.
Die Zahl ist eine Setzung, keine Messung.

**Offenlegung zur Wahl.** Schwelle und Verfahren wurden gewählt, nachdem die
Tageszahlen bekannt waren (13 auf 1D, 18–19 auf 15m). Die Wahl kann keine
Familie begünstigen: beide Prüfungen können ein Urteil nur strenger machen,
und keine Reihe erreicht die Schwelle.

### Folgen

- **Kein Fenster-Urteil kann mehr `green` werden.** Der Pool hält 30
  Kalendertage, also höchstens 22 Handelstage. `green` kann nur noch ein
  kumulatives Urteil über dem Ledger werden. Der Public-Report bettet das
  1D-Fenster-Urteil ein; ob er stattdessen das kumulative Urteil zeigen soll,
  bleibt offen wie im Nachtrag vom 2026-10-01.
- **Die 15m-Vorwärts-Reihe** (Evidenz-Start 2026-10-01) erreicht 30
  Handelstage frühestens nach 30 Börsentagen mit mindestens einem Trade je
  Familie.
- **Die übrigen Prüfungen bleiben, wie sie sind.** `sharpe`,
  `bootstrap_sharpe_ci_low`, `psr_sr_star_zero` und `min_trl_within_n` rechnen
  weiter über Trades und überzeichnen auf Ebenen mit vielen Trades je Tag. Sie
  sind dort Diagnose; bindend gegen die Überzeichnung sind die beiden
  Tages-Prüfungen.
- **Verdict-Schema 1.0.0 → 1.1.0** (additive Prüfungen,
  `summary.day_clustered`). Die beiden Namen stehen am Ende von
  `KNOWN_GATE_CHECK_NAMES`; die Positionen der bisherigen bleiben.

### Was dieser Nachtrag nicht korrigiert

- **Überlappung über Tagesgrenzen.** Ein Trade hält 3 bis 8 Kerzen (SWEEP 3,
  FVG 4, OB 6, BOS 8). Auf 15m endet das innerhalb des Tages. Auf 1D sind es
  3 bis 8 Handelstage: benachbarte Tage teilen sich Haltefenster und sind
  nicht unabhängig. Das Tages-Intervall ist auf 1D deshalb weiterhin zu eng,
  nur weniger als zuvor.
- **Marktrichtung.** Die Prüfungen sagen, ob der Ertrag von null verschieden
  ist, nicht, ob er über dem liegt, was ein beliebiger Einstieg zur selben
  Zeit im selben Symbol gebracht hätte.

# Variante A: der Einstiegspreis trägt den gemeldeten Ertrag (Messung 2026-10-02)

- **Status:** Messung. Die Ertragsregel wurde daraufhin am selben Tag geändert
  (ADR-0031, Nachtrag 2026-10-02 II); dieses Memo ist ihr Beleg.
- **Betrifft:** jede Zahl, die bis 2026-10-02 aus `governance/family_returns.py`
  kam — Track-Record-Gate, §5, das Trade-Ledger, den Public-Report-Schlüssel
  `track_record_gate`. Sie liegen eingefroren unter
  `docs/calibration/gates/variant_a_frozen/`.
- **Ebene der Messung:** 15m. Für die Zonen-Familien zusätzlich 5m bis 1D.

> **Korrektur vom 2026-10-02.** Die erste Fassung dieses Memos (#5622) rechnete
> den Kerzen-Teil auf einem um eine Kerze verschobenen Raster: das
> Auswertungsskript beschriftete die 15m-Kerzen am Anfang statt am Ende. Davon
> betroffen waren die Zahlen der Level-Familien und des Placebos, nicht die der
> Zonen-Familien. Falsch war insbesondere die Aussage, das Level habe bei rund
> der Hälfte der Level-Trades außerhalb der Spanne der Signalkerze gelegen —
> richtig sind 28 % bei BOS und 0 % bei SWEEP. Das Gesamtbild ist unverändert.
> Alle Zahlen unten stammen vom korrigierten Raster; es ist an 38 274
> Vorwärtskerzen der Events geprüft, ohne eine Abweichung im Schlusskurs.

## Befund

Variante A (`touch_then_horizon_close`) setzte den Einstieg zu einem Preis an,
der nicht erreichbar war, nachdem die Entscheidung feststand. Mit einem
Einstieg zum Schlusskurs der Entscheidungskerze ist auf 15m keine der vier
Familien positiv, und BOS und OB liegen unter zufälligen Einstiegen im selben
Symbol am selben Tag.

| Familie | n | gemeldet | handelbar | Placebo | Mehrertrag über Placebo |
|---|---|---|---|---|---|
| BOS | 554 | +12,6 [4,1; 19,5] | −7,4 [−14,8; −1,7] | +1,8 [−2,8; 5,0] | −9,2 [−13,8; −4,3] |
| OB | 269 | +9,2 [1,1; 14,6] | −9,5 [−19,1; −4,0] | +0,4 [−3,1; 2,8] | −9,9 [−18,3; −5,4] |
| FVG | 533 | +12,1 [0,4; 23,6] | −5,0 [−14,5; 5,6] | −2,7 [−5,0; −0,7] | −2,3 [−11,7; 8,2] |
| SWEEP | 1 096 | +12,4 [6,3; 17,1] | −5,9 [−9,1; −3,6] | −5,8 [−6,9; −4,7] | −0,1 [−3,0; 2,0] |
| alle | 2 452 | +12,0 [5,3; 17,0] | −6,5 [−11,1; −2,9] | −2,7 [−3,9; −1,8] | −3,7 [−8,1; 0,0] |

Basispunkte je Trade nach 5 bps Kosten; in Klammern das 95-%-Intervall, wenn
ganze Handelstage gezogen werden (17 Tage, 5 000 Züge).

- **gemeldet:** Variante A, wie das Gate sie bis 2026-10-02 rechnete.
- **handelbar:** derselbe Trade, derselbe Ausstieg, gekauft zum Schlusskurs der
  Entscheidungskerze (Signalkerze bei BOS und SWEEP, Touch-Kerze bei OB und FVG).
- **Placebo:** Mittel über alle Kerzen desselben Symbols am selben UTC-Tag,
  Einstieg zum Schlusskurs in dieselbe Richtung, dieselbe Haltedauer.

Mit einem engeren Placebo (nur Kerzen bis eine Stunde vor oder nach dem
Einstieg) liegt der Mehrertrag bei −4,4 [−8,0; −2,3] über alle Familien; BOS
−14,7, OB −4,2, FVG +1,9 [−5,7; 7,5], SWEEP −2,5.

## Woher der Unterschied kommt

**Zonen-Familien (OB, FVG).** Variante A nahm als Einstieg die Zonenmitte,
sobald das Tief (Long) oder das Hoch (Short) einer Kerze in der Zone lag. Die
Mitte musste dafür nicht erreicht sein.

- Bei 66 % der OB-Trades und 63 % der FVG-Trades wurde die Zonenmitte auf der
  Touch-Kerze nicht gehandelt. Der angenommene Einstieg war dort im Mittel
  rund 10 bps besser als der beste gehandelte Preis der Kerze.
- Eine Kerze, die die Zone durchschlug, zählte nicht als Touch. Die Auswahl
  hing damit vom Verlauf nach dem Einstieg ab.
- Eine Limit-Order an der Zonenmitte, die füllt, sobald der Kurs sie erreicht,
  bringt OB −7,3 [−14,0; −1,2] und FVG −14,1 [−20,8; −7,1]. Eine Limit-Order am
  Zonenrand bringt OB −10,1 [−16,6; −4,2] und FVG −13,3 [−21,2; −5,2].

Der Anteil nicht erreichter Zonenmitten ist auf allen Ebenen ähnlich:

| Ebene | OB | FVG |
|---|---|---|
| 5m | 66 % | 61 % |
| 10m | 70 % | 62 % |
| 15m | 66 % | 63 % |
| 30m | 63 % | 67 % |
| 1H | 60 % | 71 % |
| 1D | 80 % (n = 20) | – |

**Level-Familien (BOS, SWEEP).** Variante A nahm das gebrochene oder
abgefischte Level als Einstieg. Das Ereignis steht aber erst mit dem Schluss
der Signalkerze fest: ein Bruch ist ein Schlusskurs jenseits des Levels, ein
Sweep ein Schlusskurs zurück diesseits davon.

- Die Signalkerze schließt im Mittel 20,1 bps (BOS; Intervall 17,7 bis 22,1)
  und 18,3 bps (SWEEP; 15,0 bis 21,2) weiter in Trade-Richtung als das Level.
  Der Median liegt bei 10,6 und 11,4 bps.
- Das Level lag bei 72 % der BOS-Trades und bei allen SWEEP-Trades in der
  Spanne der Signalkerze. Gehandelt wurde es also meist — aber bevor feststand,
  dass die Kerze jenseits (BOS) oder diesseits (SWEEP) schließt. Wer zum Level
  einsteigt, steigt auch bei den Kerzen ein, die anders schließen; die sind in
  der Serie nicht enthalten.

## Zur Long/Short-Lücke

Gemeldet lagen Shorts bei +18,7 bps und Longs bei +4,9 bps. Zufällige Shorts
brachten −0,3 bps, zufällige Longs −5,3 bps: rund 5 bps der Lücke sind die
Marktrichtung im Messzeitraum. Handelbar bleiben Shorts bei −0,2 und Longs bei
−13,1 bps.

## Dieselben Events unter der neuen Regel

Die neue Regel (`next_open_then_horizon_close`) steigt zur Eröffnung der Kerze
nach der Entscheidungskerze ein. Die Pool-Events tragen keine
Eröffnungskurse; für diese Nachrechnung sind sie aus den 1m-Kerzen ergänzt
(3 081 von 3 108 Events), gerechnet hat der Code des Repos
(`realized_return`).

| Familie | n | Mittel | 95 % über Tage | Gewinn-Anteil |
|---|---|---|---|---|
| BOS | 553 | −7,8 | [−16,0; −2,0] | 46 % |
| OB | 288 | −7,4 | [−15,8; −2,3] | 41 % |
| FVG | 764 | −6,9 | [−15,1; 2,2] | 44 % |
| SWEEP | 1 096 | −5,6 | [−8,6; −3,8] | 44 % |
| alle | 2 701 | −6,6 | [−11,7; −3,2] | 44 % |

Über alle Familien waren 3 von 18 Tagen positiv. Es sind mehr Trades als unter
Variante A (2 469), weil eine Kerze, die die Zone durchschlägt, jetzt als
Entscheidungskerze zählt. Diese Zahlen sind eine Rückschau auf Daten, die bei
der Wahl der Regel bekannt waren; sie gehen nicht in das neue Ledger ein.

## Erste Ablesung aus der Pipeline (2026-10-02, nach der Regeländerung)

Nach dem Merge der Regel (#5624) lief der Benchmark auf dem neuen Stand (Lauf
37044450503): 13 880 der 19 893 Pool-Events tragen Eröffnungskurse, auf 1D
alle. Das Gate (Lauf 37048499180) rechnete daraus die ersten Fenster-Urteile
unter der neuen Regel; sie liegen auf `main`
(`docs/calibration/gates/track_record_gate_2026-10-02.json`,
`docs/calibration/gates/15m/track_record_gate_2026-10-02.json`). Mittel je
Trade in bps, Intervall über gezogene Tage, aus `summary.day_clustered`:

| Ebene | Familie | n | Tage | neue Regel | Variante A, dieselben Events |
|---|---|---|---|---|---|
| 1D | BOS | 44 | 11 | −103,0 [−269,9; 68,1] | +21,0 [−187,8; 213,2] |
| 1D | OB | 21 | 7 | −57,0 [−174,5; 109,0] | +76,3 [−64,3; 233,9] |
| 1D | SWEEP | 103 | 12 | −59,0 [−122,7; −5,9] | +33,1 [−41,7; 93,9] |
| 1D | alle | 168 | 12 | −70,3 [−142,8; 1,3] | – |
| 15m | BOS | 388 | 4 | −4,5 [−11,5; 0,6] | – |
| 15m | OB | 201 | 4 | −3,8 [−10,2; 1,3] | – |
| 15m | FVG | 608 | 4 | −6,0 [−15,0; 5,4] | – |
| 15m | SWEEP | 935 | 4 | −4,7 [−6,5; −3,0] | – |
| 15m | alle | 2 132 | 4 | −5,0 [−9,0; −0,4] | – |

Die Variante-A-Spalte stammt aus dem eingefrorenen Urteil desselben Tages
(`variant_a_frozen/track_record_gate_2026-10-02.json`); OB hatte dort 20
Trades. Auf 15m tragen nur die Events der letzten vier Tage Eröffnungskurse.

Damit ist auch 1D gemessen: der Einstiegsvorteil war dort rund 90 bis 130 bps
je Trade. Alle diese Trades liegen vor dem Evidenz-Start (2026-10-05) und
zählen nicht für die kumulativen Urteile; es ist eine Rückschau.

## Daten und Abdeckung

- Events: Pool aus `smc-measurement-benchmark-rolling`, Lauf 37007024689
  (2026-10-02), 3 108 Events auf 15m, davon 2 469 unter Variante A ausgelöst.
- Kerzen: `benchmark_universe_ohlcv_1m` aus den Producer-Artefakten, 24
  Symbole, 10.8. bis 2.10.2026. Das 15m-Raster der Events entsteht daraus mit
  `label=right, closed=right`.
- Verglichen sind 2 452 der 2 469 Trades; bei 17 liegt die Einstiegskerze nicht
  auf dem rekonstruierten Raster oder der Tag trägt zu wenige Kerzen.

## Was die Messung nicht trägt

- **Wenige Tage, ungleich besetzt.** 17 Handelstage; 79 % der Trades stammen
  aus den vier Tagen 28.9. bis 1.10., weil der Pool-Schlüssel erst seit #5585
  jedes Symbol hält. Die Intervalle ziehen über Tage und sind bei 17 Tagen
  selbst unsicher.
- **Eine handelbare Variante, nicht alle.** Geprüft sind der Kauf zum
  Schlusskurs, die Eröffnung der Folgekerze und, für die Zonen, zwei
  Limit-Orders. Für BOS und SWEEP ist eine vorab liegende Stop- oder
  Limit-Order am Level nicht prüfbar: der Pool hält nur bestätigte Ereignisse,
  nicht die Berührungen ohne Bestätigung.
- **1D ist nur unter der neuen Regel gemessen** (Abschnitt „Erste Ablesung
  aus der Pipeline"). Der Kerzen-Vergleich mit Placebo lief nur auf 15m;
  Tageskerzen waren nicht Teil der geladenen Artefakte.

## Nachrechnen

Der Zonen-Teil braucht nur den Pool
(`gh run download <lauf> -n scored-family-events-accumulated`). Er rechnet
Variante A nach und läuft deshalb nur auf einem Stand vor der Regeländerung,
zuletzt Commit `8b31e8365`:

```bash
python - accumulated_family_events.json <<'PY'
import json, sys
from governance.family_returns import _direction_sign, _first_touch_index, realized_return
from governance.family_walkforward import family_outcome_horizon
from scripts.run_magnitude_shadow_ledger import event_measurement_plane

events = [e for e in json.load(open(sys.argv[1])) if event_measurement_plane(e) == "15m"]
for family in ("OB", "FVG"):
    horizon = family_outcome_horizon(family)
    reported, at_close, unreached = [], [], 0
    for event in events:
        if event["family"] != family or realized_return(event) is None:
            continue
        sign = _direction_sign(event["direction"])
        low, high = float(event["zone_low"]), float(event["zone_high"])
        highs, lows, closes = event["forward_highs"], event["forward_lows"], event["forward_closes"]
        touch = _first_touch_index(sign, low, high, highs, lows)
        extreme = lows[touch] if sign > 0 else highs[touch]
        unreached += sign * (extreme - (low + high) / 2) > 0
        reported.append(realized_return(event))
        at_close.append(sign * (closes[touch + horizon] - closes[touch]) / closes[touch] - 5e-4)
    n = len(reported)
    print(f"{family}: n={n} midpoint not traded on the touch bar={unreached / n:.0%} "
          f"reported={sum(reported) / n * 1e4:.1f} bps bought at the close={sum(at_close) / n * 1e4:.1f} bps")
PY
```

Der Kerzen-Teil (Level-Familien, Placebo, Rückschau unter der neuen Regel)
braucht die 1m-Kerzen. Die Export-Artefakte halten 14 Tage,
`a9b-2b-merged-manifest` 30 Tage; danach kostet derselbe Zeitraum einen
Databento-Abruf.

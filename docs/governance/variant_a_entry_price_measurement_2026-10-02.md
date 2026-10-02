# Variante A: der Einstiegspreis trägt den gemeldeten Ertrag (Messung 2026-10-02)

- **Status:** Messung, keine Entscheidung. Die Ertragsregel ist ADR-0031,
  Entscheidung 1; sie zu ändern ist Owner-Sache.
- **Betrifft:** jede Zahl aus `governance/family_returns.py` — Track-Record-Gate,
  §5, das Trade-Ledger, den Public-Report-Schlüssel `track_record_gate`.
- **Ebene der Messung:** 15m. Für die Zonen-Familien zusätzlich 5m bis 1D.

## Befund

Die Regel `touch_then_horizon_close` setzt den Einstieg zu einem Preis an, der
auf der Einstiegskerze großteils nicht gehandelt wurde. Mit einem Einstieg zum
Schlusskurs derselben Kerze ist auf 15m keine der vier Familien positiv, und
BOS und OB liegen unter zufälligen Einstiegen im selben Symbol am selben Tag.

| Familie | n | gemeldet | handelbar | Placebo | Mehrertrag über Placebo |
|---|---|---|---|---|---|
| BOS | 479 | +11,9 [1,9; 18,2] | −6,2 [−16,0; 0,7] | +3,1 [−2,9; 6,7] | −9,3 [−14,8; −4,9] |
| OB | 252 | +10,6 [2,5; 16,3] | −8,6 [−18,2; −2,7] | +0,8 [−3,4; 3,8] | −9,3 [−18,1; −4,6] |
| FVG | 432 | +14,6 [0,7; 26,9] | −4,4 [−15,9; 6,5] | −2,6 [−6,1; −0,2] | −1,8 [−12,9; 8,5] |
| SWEEP | 1 058 | +12,3 [6,3; 17,0] | −6,8 [−9,5; −4,3] | −5,8 [−6,9; −4,8] | −1,0 [−3,7; 0,8] |
| alle | 2 221 | +12,5 [5,3; 16,9] | −6,4 [−11,5; −3,9] | −2,5 [−4,1; −1,5] | −3,9 [−8,3; −1,1] |

Basispunkte je Trade nach 5 bps Kosten; in Klammern das 95-%-Intervall, wenn
ganze Handelstage gezogen werden (17 Tage, 5 000 Züge).

- **gemeldet:** Variante A, wie das Gate sie rechnet.
- **handelbar:** derselbe Trade, derselbe Ausstieg, gekauft zum Schlusskurs der
  Einstiegskerze (Signalkerze bei BOS und SWEEP, Touch-Kerze bei OB und FVG).
- **Placebo:** Mittel über alle Kerzen desselben Symbols am selben UTC-Tag,
  Einstieg zum Schlusskurs in dieselbe Richtung, dieselbe Haltedauer.

Mit einem engeren Placebo (nur Kerzen bis eine Stunde vor oder nach dem
Einstieg) liegt der Mehrertrag bei −4,1 [−7,2; −2,6] über alle Familien; BOS
−10,0, OB −4,2, FVG +3,0 [−5,5; 9,5], SWEEP −4,2.

## Woher der Unterschied kommt

**Zonen-Familien (OB, FVG).** `realized_return` nimmt als Einstieg die
Zonenmitte, sobald das Tief (Long) oder das Hoch (Short) einer Kerze in der Zone
liegt (`_first_touch_index`). Die Mitte muss dafür nicht erreicht sein.

- Bei 66 % der OB-Trades und 63 % der FVG-Trades wurde die Zonenmitte auf der
  Touch-Kerze nicht gehandelt. Der angenommene Einstieg ist dort im Mittel
  rund 10 bps besser als der beste gehandelte Preis der Kerze.
- Eine Kerze, die die Zone durchschlägt, zählt nicht als Touch. Die Auswahl
  hängt damit vom Verlauf nach dem Einstieg ab.
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

**Level-Familien (BOS, SWEEP).** `_level_event_to_family` reicht den Preis des
Strukturereignisses als `entry_price` durch, also das gebrochene oder
abgefischte Level. Das Ereignis steht aber erst mit dem Schluss der Signalkerze
fest.

- Die Signalkerze schließt im Mittel 18,2 bps (BOS) und 19,2 bps (SWEEP)
  weiter in Trade-Richtung als das Level.
- In 49 % (BOS) und 57 % (SWEEP) der Fälle lag das Level in der Spanne der
  Signalkerze; in den übrigen wurde es auf dieser Kerze nicht gehandelt.

## Zur Long/Short-Lücke

Gemeldet lagen Shorts bei +18,1 bps und Longs bei +6,4 bps. Zufällige Shorts
brachten −0,1 bps, zufällige Longs −5,2 bps: rund 5 bps der Lücke sind die
Marktrichtung im Messzeitraum. Handelbar bleiben Shorts bei −2,1 und Longs bei
−11,1 bps.

## Daten und Abdeckung

- Events: Pool aus `smc-measurement-benchmark-rolling`, Lauf 37007024689
  (2026-10-02), 3 108 Events auf 15m, davon 2 469 ausgelöst.
- Kerzen: `benchmark_universe_ohlcv_1m` aus den Producer-Artefakten, 24
  Symbole, 10.8. bis 2.10.2026. Aus den 1m-Kerzen entsteht das 15m-Raster der
  Events mit `label=right, closed=right`; an 7 119 Vorwärtskerzen der Events
  geprüft, alle Schlusskurse identisch.
- Verglichen sind 2 221 der 2 469 Trades. Bei 248 liegt die Einstiegskerze
  nicht auf dem rekonstruierten Raster, bei einem davon fehlt der Tag ganz.

## Was die Messung nicht trägt

- **Wenige Tage, ungleich besetzt.** 17 Handelstage; 79 % der Trades stammen
  aus den vier Tagen 28.9. bis 1.10., weil der Pool-Schlüssel erst seit #5585
  jedes Symbol hält. Die Intervalle ziehen über Tage und sind bei 17 Tagen
  selbst unsicher.
- **Eine handelbare Variante, nicht alle.** Geprüft sind der Kauf zum
  Schlusskurs und, für die Zonen, zwei Limit-Orders. Für BOS und SWEEP ist eine
  vorab liegende Stop- oder Limit-Order am Level nicht prüfbar: der Pool hält
  nur bestätigte Ereignisse, nicht die Berührungen ohne Bestätigung.
- **1D für BOS und SWEEP ungemessen.** Tageskerzen waren nicht Teil der
  geladenen Artefakte.
- **Ob das Ereignis zum Schluss der Signalkerze schon feststeht,** ist nicht
  geprüft. Braucht die Erkennung spätere Kerzen, ist der handelbare Einstieg
  noch später.

## Nachrechnen

Der Zonen-Teil braucht nur den Pool
(`gh run download <lauf> -n scored-family-events-accumulated`):

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

Der Kerzen-Teil (Level-Familien, Placebo) braucht die 1m-Kerzen. Die
Export-Artefakte halten 14 Tage, `a9b-2b-merged-manifest` 30 Tage; danach
kostet derselbe Zeitraum einen Databento-Abruf.

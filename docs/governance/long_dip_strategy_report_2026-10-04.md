# Long-Dip-Strategy im TradingView-Strategy-Report

Stand 2026-10-04. Gelesen mit `scripts/tv_strategy_report_readout.ts` vom
Hauptchart des Betreiberkontos (`vWgAWyfC`): die veröffentlichte
`SMC Long-Dip Suite` und die daran gebundene `SMC Long-Dip Strategy`, wie sie
dort liegen. Eine Rückschau im Tester, kein Track Record.

## Frage

Die Rückschau der Engine-Bausteine
(`structure_grain_history_2026-10-03.md`, Nachtrag) fand keinen Baustein mit
Richtungsinformation. Offen blieb, ob die Zustandsmaschine der Suite
(Armed → Confirmed → Ready → Entry Best / Entry Strict) daraus handelbare
Signale macht. Die Strategy ist die dafür gebaute Ausführungsfläche: Stop-Kauf
am Trigger, Stop an der Invalidation, Take-Profit bei 2 R.

## Weg

- 5 Symbole (AAPL, NVDA, JPM, XOM, UNH), 15 Minuten, je Stufe ein Report;
  einmal mit der Sitzung des Layouts (erweiterte Handelszeiten, Historie je
  Symbol ab März bis Juli 2025) und einmal mit regulären Handelszeiten
  (Historie ab 2023-09-01), jeweils bis 2026-10-02/03.
- Eingaben der Strategy wie gespeichert: alle acht BUS-Eingänge an der Suite,
  Provision 0, Slippage 0, 1 Kontrakt, Take-Profit 2 R, „Backtest Mode" aus.
  Die Bibliotheks-Gates der Strategy wirken laut Quelltext nur auf
  Echtzeit-Kerzen, in der Historie also nicht.
- Auswertung (`~/.claude/scripts/family-fill-analysis/tv_longdip_eval.py`):
  TradingViews Ein- und Ausstiegskurse, 5 bps je Trade, Intervall über gezogene
  Einstiegstage. Placebo: je Trade 200 Zufallseinstiege im selben Symbol zur
  selben Tageszeit an anderen Tagen des Zeitraums, gleiche Haltedauer.
- Jede Export-Datei ist gegen die Ablesung geprüft: Stufe, acht Bindungen,
  Provision, Slippage, Trade-Zahl.

## Ergebnis

Trades je Stufe über die fünf Symbole:

| Stufe | erweiterte Handelszeiten (15–19 Monate) | reguläre Handelszeiten (37 Monate) |
|---|---|---|
| Strict (Standard der Strategy) | 0 | 0 |
| Best | 0 | 0 |
| Ready | 0 | 0 |
| Confirmed | 36 (an 10 Tagen) | 1 |
| Armed | 269 | 177 |

bps je Trade, 95 %-Intervall über Tage:

| Stufe, Sitzung | Trades | netto | Placebo | Mehrertrag über Placebo |
|---|---|---|---|---|
| Armed, erweitert | 269 | +1,2 [−12,0; +16,0] | +5,2 | +0,1 [−13,8; +14,4] |
| Armed, regulär | 177 | +13,2 [−7,6; +38,0] | +9,5 | +8,7 [−12,5; +33,4] |
| Confirmed, erweitert | 36 | +3,1 [−8,3; +20,9] | +2,7 | +4,3 [−7,1; +17,7] |

## Ablesung

- **Die Stufen Ready, Entry Best und Entry Strict lösen in der Historie nie
  aus** — in keinem der fünf Symbole, in keiner der beiden Sitzungen, über bis
  zu drei Jahre. Die Strategy handelt in ihrer Standardeinstellung (Strict)
  nichts. Warum, ist hier nicht gemessen; die Suite gibt Blocker-Codes aus
  (`BUS ReadyBlocker…`), die das beantworten können.
- **Armed zeigt keinen belegbaren Vorteil.** Beide Intervalle schließen die
  Null ein, auch gegen den Zufallseinstieg. Im erweiterten Layout liegen 32 %
  der Einstiege außerhalb 09:30–16:00 New York (der Stop-Kauf bleibt über die
  Sitzungsgrenze stehen).
- **Confirmed** hat zu wenige Trades für eine Aussage; im erweiterten Layout
  öffnen und schließen die meisten in derselben Kerze.

## Was die Ablesung nicht trägt

- Fünf Symbole, eine Zeitebene. Andere Zeitebenen und kleinere Werte sind
  nicht gelesen.
- Der Tester rechnet mit den heute veröffentlichten Bibliotheksständen; die
  Tageswerte der generierten Bibliothek (`mp.*`) liegen in der Historie als
  Konstante auf allen Kerzen.
- Dass eine Stufe in der Historie nie auslöst, sagt nichts darüber, ob sie
  live auslöst: Echtzeit-Kerzen laufen durch Zweige (Lower-Timeframe-Daten,
  Live-Gates), die die Historie nicht hat.
- Füllungen sind die des TradingView-Emulators (4 Ticks je Kerze, Stop zum
  angeforderten Preis).

## Fallen beim Lesen

- Der Report zeigt nach einer Eingabe-Änderung zunächst das VORIGE Ergebnis.
  Ein Warten auf „Text zweimal gleich" las für Confirmed/Ready/Best die 27
  Trades von Armed. Das Skript verlangt deshalb die Lade-Flanke der Strategy
  in der Legende (`data-status="loading"`) und bricht ohne sie ab.
- Eine wiederholte Stufe kommt aus TradingViews Zwischenspeicher ohne
  Lade-Flanke; das Skript lehnt doppelte Stufen ab.

Verwandt: ADR-0034 (Nachtrag 2026-10-04),
`docs/governance/structure_grain_history_2026-10-03.md`.

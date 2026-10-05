# Trailing Stop mit Wiedereinstieg über dem Ausstiegskurs oder nach fester Zeit

Stand 2026-10-05. Auftrag des Operators vom selben Tag. Eine Rückschau, kein
Track Record. Anschluss an `trailing_reentry_after_drop_2026-10-05.md`.

## Regel (vorregistriert in `opaw_reentry2_prereg_2026-10-05.md`)

- Kauf zur Eröffnung des ersten Montags im Datenzeitraum.
- Trailing Stop T = 5, 6, 7 oder 8 % unter dem Höchstkurs seit dem Kauf;
  Ausstiegskurs S = Ausführungskurs des Stops.
- Wiedereinstieg, was zuerst eintritt: der Kurs handelt mindestens einen Cent
  über S (Stop-Kauforder bei S), **oder** die Zeitgrenze W läuft ab
  (W = 1, 2, 4, 8, 13 Wochen; zum Vergleich ohne Zeitgrenze). Danach derselbe
  Trailing Stop.
- 24 Kombinationen je ETF; 20 Themen-ETFs (17 auswertbar) und TQQQ, QQQ, UPRO,
  SOXL, TNA; Mai 2018 bzw. ab Fondsstart bis 2026-10-02.
- Drei Ausführungsfassungen: **Basis** (Ausführung zum Auslösekurs, 2 bps je
  Order), **10 bps**, **pessimistisch** (schlechterer aus Auslösekurs und
  Schlusskurs der auslösenden Minute, plus 2 bps).

## Ergebnis je ETF (Endkonto, Start 1,00)

| ETF | Halten | Montag-Wiederkauf (T 5–8 %) | Neue Regel, Basis | Neue Regel, pessimistisch | Zeit im Markt | Handelsrunden je Jahr |
|---|---|---|---|---|---|---|
| AIQ | 4,40 | 2,77 – 4,33 | 3,01 – 4,13 | 2,78 – 3,98 | 99 % | 11 |
| CHAT | 3,73 | 2,52 – 3,06 | 3,04 – 4,07 | 2,88 – 3,47 | 99 % | 15 |
| AGIX | 1,92 | 1,31 – 1,96 | 1,68 – 2,34 | 1,65 – 2,22 | 97 % | 12 |
| QTUM | 6,27 | 4,43 – 6,01 | 4,78 – 7,03 | 4,42 – 6,41 | 98 % | 12 |
| SMH | 13,02 | 8,62 – 11,39 | 9,70 – 13,21 | 7,00 – 9,79 | 100 % | 20 |
| SOXX | 10,50 | 5,90 – 7,34 | 6,42 – 9,82 | 4,91 – 7,62 | 99 % | 21 |
| ITA | 2,17 | 2,12 – 2,58 | 1,92 – 3,28 | 1,73 – 2,86 | 99 % | 9 |
| XAR | 2,74 | 2,76 – 4,64 | 2,18 – 4,67 | 1,96 – 4,61 | 98 % | 12 |
| PPA | 2,80 | 2,68 – 4,12 | 2,30 – 4,09 | 2,16 – 3,91 | 99 % | 7 |
| SHLD | 2,43 | 1,92 – 2,86 | 2,33 – 2,43 | 2,30 – 2,43 | 99 % | 7 |
| EUAD | 1,60 | 2,02 – 2,14 | 1,59 – 1,69 | 1,53 – 1,59 | 98 % | 12 |
| NATO | 1,45 | 1,24 – 1,69 | 1,25 – 1,50 | 1,24 – 1,49 | 98 % | 10 |
| REMX | 0,77 | 1,74 – 3,57 | 0,77 – 1,70 | 0,32 – 0,90 | 88 % | 19 |
| URA | 3,01 | 3,30 – 5,15 | 1,66 – 4,72 | 1,07 – 2,60 | 94 % | 25 |
| URNM | 3,77 | 4,60 – 13,55 | 2,23 – 5,98 | 1,41 – 3,42 | 91 % | 30 |
| DMAT | 1,51 | 1,33 – 1,47 | 1,00 – 2,02 | 0,96 – 1,83 | 87 % | 14 |
| SETM | 1,40 | 1,31 – 1,54 | 0,94 – 2,03 | 0,89 – 1,83 | 89 % | 19 |
| TQQQ | 13,68 | 7,44 – 20,90 | 2,05 – 16,38 | 0,26 – 4,39 | 95 % | 68 |
| QQQ | 4,67 | 3,80 – 4,62 | 3,91 – 4,28 | 3,60 – 3,98 | 100 % | 10 |
| UPRO | 6,98 | 4,60 – 10,06 | 2,16 – 5,73 | 0,70 – 1,84 | 98 % | 45 |
| SOXL | 20,27 | 4,66 – 51,79 | 0,88 – 90,44 | 0,02 – 0,51 | 89 % | 118 |
| TNA | 0,88 | 1,85 – 2,88 | 0,25 – 5,30 | 0,01 – 0,18 | 96 % | 77 |

Spannen über die 24 Kombinationen; Zeit im Markt und Handelsrunden sind
Mediane (Basis). WQTM, EUV und DRAM stehen in der Ergebnisdatei.

## Themen-ETFs: Endkonto als Vielfaches des Haltens (Median über 17 ETFs)

| Zeitgrenze | Basis T 5 % | 6 % | 7 % | 8 % | Pessimistisch T 5 % | 6 % | 7 % | 8 % |
|---|---|---|---|---|---|---|---|---|
| 1 Woche | 1,05 | 0,97 | 0,97 | 0,98 | 0,82 | 0,86 | 0,86 | 0,86 |
| 2 Wochen | 0,96 | 0,88 | 0,93 | 0,92 | 0,84 | 0,78 | 0,85 | 0,86 |
| 4 Wochen | 0,96 | 0,88 | 0,93 | 0,92 | 0,80 | 0,75 | 0,84 | 0,81 |
| 8 Wochen | 0,96 | 0,82 | 0,89 | 0,91 | 0,81 | 0,75 | 0,80 | 0,80 |
| 13 Wochen | 0,96 | 0,82 | 0,87 | 0,91 | 0,84 | 0,77 | 0,80 | 0,83 |
| ohne | 0,87 | 0,82 | 0,87 | 0,90 | 0,71 | 0,77 | 0,77 | 0,83 |

## Die vorab festgelegten Urteile

| Fassung | Gruppe | Fälle | Konto > Halten | Sharpe sicher > Halten | Konto > Montag-Wiederkauf | sicher > Montag-Wiederkauf | Rückgang kleiner als Halten |
|---|---|---|---|---|---|---|---|
| Basis | Themen | 408 | 115 | 3 | 143 | 2 | 191 |
| Basis | gehebelt/Index | 120 | 16 | 0 | 28 | 1 | 36 |
| Pessimistisch | Themen | 408 | 25 | 1 | 118 | 1 | 104 |
| Pessimistisch | gehebelt/Index | 120 | 0 | 0 | 12 | 0 | 0 |
| 10 bps | Themen | 408 | 58 | 0 | 131 | 2 | 162 |
| 10 bps | gehebelt/Index | 120 | 2 | 0 | 18 | 0 | 19 |

**Für keine Kombination belegt** — weder besser als Halten noch besser als der
Montag-Wiederkauf, in keiner Fassung.

## Warum

Der Rückkauf folgt dem Verkauf fast immer sofort. Bei T = 5 % und Zeitgrenze
4 Wochen fallen bei den Themen-ETFs 87 % der Rückkäufe auf den Tag des Verkaufs (91 %
bis zum nächsten Tag), bei TQQQ, QQQ, UPRO, SOXL, TNA 95 % (97 %). Direkt nach
dem Stop pendelt der Kurs um den Ausstiegskurs; ein Cent darüber genügt, und
die Regel kauft zum selben Kurs zurück. Je nach Zeitgrenze laufen 97,6 bis
99,6 % der Rückkäufe über „Kurs über S", nur 0,4 bis 2,4 % über die Zeit.

Folgen:
- Die Regel ist 87 bis 100 % der Zeit investiert und verhält sich wie Halten
  abzüglich Handelskosten.
- Jeder Verkauf mit sofortigem Rückkauf setzt den Trailing Stop um T tiefer;
  der Schutz vor Abstürzen entfällt. Der größte Rückgang ist in der Basis nur
  in 191 von 408 Fällen kleiner als beim Halten.
- Bei den gehebelten ETFs (im Median 45 bis 118 Handelsrunden je Jahr)
  fressen Spanne und Schlupf das Konto auf: in der Gruppe mit QQQ
  pessimistisch im Median das 0,13-Fache des Haltens.

## Was das nicht trägt

- Basis-Ausführung genau zum Auslösekurs ist zu günstig; die pessimistische
  Fassung ist eine Obergrenze der Kosten innerhalb der Auslöseminute.
- Start nur am ersten Montag des Datenzeitraums; Gleichlauf der Themen-ETFs;
  dünner Handel bei DMAT und NATO.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_reentry2_prereg_2026-10-05.md`, `opaw_reentry2.py`,
`results_opaw_reentry2_{base,cost10,pess}_2026-10-05.{txt,csv}`); nicht im
Repo.

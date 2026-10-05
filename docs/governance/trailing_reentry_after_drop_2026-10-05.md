# Trailing Stop mit Wiedereinstieg erst nach weiterem Rückgang

Stand 2026-10-05. Auftrag des Operators vom selben Tag. Eine Rückschau, kein
Track Record. Anschluss an `theme_etfs_trailing_stop_2026-10-05.md`.

## Regel (vorregistriert in `opaw_reentry_prereg_2026-10-05.md`)

- Kauf zur Eröffnung des ersten Montags im Datenzeitraum.
- Trailing Stop T = 5, 6, 7 oder 8 % unter dem Höchstkurs seit dem Kauf.
- Nach jedem Stop-Verkauf **kein Montagskauf**, sondern eine Kauforder D = 5,
  10, 15 oder 20 % unter dem Ausstiegskurs, gültig jeden Handelstag ohne
  Ablauf; danach wieder Trailing Stop T. 16 Kombinationen je ETF.
- Werte: die 20 Themen-ETFs (17 mit mindestens 100 Wochen) und TQQQ, QQQ,
  UPRO, SOXL, TNA. Minutenkerzen von Databento, Mai 2018 bzw. ab Fondsstart
  bis 2026-10-02. Kosten 2 bps je Market-Order (Kontrolle 10 bps).
- Vergleich: Halten; „Montag-Wiederkauf" (vorige Regel: nach einem Stop Kauf
  zur nächsten Montagseröffnung).

## Ergebnis

| ETF | Halten | Montag-Wiederkauf (T 5–8 %) | Neue Regel (16 Kombinationen) | Zeit im Markt (Median) | Am Ende draußen seit (Median) |
|---|---|---|---|---|---|
| AIQ | 4,40 | 2,77 – 4,33 | 0,95 – 1,38 | 5 % | 7,8 Jahren |
| CHAT | 3,73 | 2,52 – 3,07 | 1,07 – 1,71 | 3 % | 3,1 Jahren |
| AGIX | 1,92 | 1,32 – 1,96 | 0,92 – 1,00 | 1 % | 2,2 Jahren |
| QTUM | 6,27 | 4,43 – 6,01 | 0,91 – 1,17 | 3 % | 7,7 Jahren |
| SMH | 13,02 | 8,62 – 11,40 | 0,94 – 1,39 | 2 % | 7,8 Jahren |
| SOXX | 10,50 | 5,91 – 7,34 | 0,96 – 1,69 | 2 % | 7,8 Jahren |
| ITA | 2,17 | 2,13 – 2,58 | 0,87 – 1,50 | 4 % | 6,5 Jahren |
| XAR | 2,74 | 2,76 – 4,64 | 0,91 – 1,41 | 5 % | 6,5 Jahren |
| PPA | 2,80 | 2,68 – 4,13 | 0,94 – 1,61 | 5 % | 6,5 Jahren |
| SHLD | 2,43 | 1,92 – 2,86 | 0,95 – 3,36 | 31 % | 2,1 Jahren |
| EUAD | 1,60 | 2,02 – 2,14 | 0,98 – 1,84 | 5 % | 1,8 Jahren |
| NATO | 1,45 | 1,24 – 1,69 | 0,95 – 0,98 | 5 % | 1,9 Jahren |
| REMX | 0,77 | 1,74 – 3,57 | 0,60 – 0,99 | 3 % | 6,5 Jahren |
| URA | 3,01 | 3,31 – 5,16 | 0,82 – 1,02 | 6 % | 6,5 Jahren |
| URNM | 3,77 | 4,62 – 13,59 | 0,77 – 1,43 | 2 % | 6,6 Jahren |
| DMAT | 1,51 | 1,33 – 1,47 | 0,91 – 1,50 | 8 % | 2,1 Jahren |
| SETM | 1,40 | 1,31 – 1,55 | 0,82 – 1,09 | 4 % | 1,5 Jahren |
| TQQQ | 13,68 | 7,45 – 20,90 | 0,90 – 1,45 | 2 % | 7,8 Jahren |
| QQQ | 4,67 | 3,80 – 4,62 | 0,96 – 1,34 | 6 % | 7,8 Jahren |
| UPRO | 6,98 | 4,60 – 10,07 | 0,85 – 1,59 | 2 % | 6,5 Jahren |
| SOXL | 20,27 | 4,68 – 51,93 | 0,90 – 1,38 | 1 % | 6,5 Jahren |
| TNA | 0,88 | 1,73 – 2,88 | 0,48 – 1,24 | 2 % | 6,5 Jahren |

Endkonto bei Start 1,00. Bei allen ETFs der Tabelle und in allen 16
Kombinationen ist die Regel am Datenende draußen. WQTM, EUV und DRAM (unter
100 Wochen) stehen in der Ergebnisdatei.

- Themen-ETFs: Endkonto im Median das **0,44-Fache** des Haltens; besser als
  Halten in 10 von 272 Fällen (8 davon bei REMX, wo Halten verlor), besser
  als Montag-Wiederkauf in 4 von 272. Sharpe sicher besser als Halten in 1
  von 272 Fällen.
- TQQQ/QQQ/UPRO/SOXL/TNA: im Median das **0,15-Fache** des Haltens; nie
  besser als Montag-Wiederkauf.
- Größter Rückgang immer kleiner als beim Halten — weil die Regel fast nur
  Kasse hält.
- Mit 10 bps Kosten dasselbe Bild. **Urteile 1 und 2: für keine Kombination
  belegt.**

## Warum

Nach einem Stop wartet die Regel darauf, dass der Kurs noch D % unter den
Ausstiegskurs fällt. Steigt der Markt danach, kommt dieser Kurs nie wieder,
und die Regel bleibt für immer draußen. Bei SMH (T 5 %, D 5 %) verkaufte der
letzte Stop am 2019-01-03 zu 42,06 (bereinigte Kurse); die Kauforder lag bei
39,96, der tiefste Kurs danach bei 41,95 am folgenden Tag — darunter fiel SMH
nie wieder, auch nicht im Corona-Crash 2020. Wiedereinstiege gibt es vor allem in Abwärtsphasen, wo der
nächste Stop oft schnell wieder verkauft (REMX, TNA: 6 bis 13 im Median).

## Was das nicht trägt

- Das Ergebnis hängt stark am Startdatum: Der erste Ausstiegskurs legt fest,
  ob es je einen Wiedereinstieg gibt. Andere Startdaten sind nicht gerechnet.
- Dieselben Vorbehalte wie in den Themen-ETF-Memos (Gleichlauf der ETFs,
  dünner Handel bei DMAT und NATO, pauschale Kosten).

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_reentry_prereg_2026-10-05.md`, `opaw_reentry.py`,
`results_opaw_reentry_{2,10}bps_2026-10-05.{txt,csv}`); nicht im Repo.

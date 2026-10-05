# Trailing Stop mit Wiedereinstieg erst 1–5 % über dem Ausstiegskurs

Stand 2026-10-05. Auftrag des Operators vom selben Tag. Eine Rückschau, kein
Track Record. Anschluss an `trailing_reentry_above_exit_2026-10-05.md`.

## Regel (vorregistriert in `opaw_reentry3_prereg_2026-10-05.md`)

- Kauf zur Eröffnung des ersten Montags im Datenzeitraum.
- Trailing Stop T = 5, 6, 7 oder 8 % unter dem Höchstkurs seit dem Kauf;
  Ausstiegskurs S = Ausführungskurs des Stops.
- Wiedereinstieg erst, wenn der Kurs **A = 1, 2, 3, 4 oder 5 % über S**
  handelt (Stop-Kauforder bei S × (1 + A), ohne Ablauf, keine Zeitgrenze).
  Danach derselbe Trailing Stop.
- 20 Kombinationen je ETF; 20 Themen-ETFs (17 auswertbar) und TQQQ, QQQ, UPRO,
  SOXL, TNA; Mai 2018 bzw. ab Fondsstart bis 2026-10-02. Drei
  Ausführungsfassungen: Basis (2 bps), 10 bps, pessimistisch.

## Ergebnis je ETF (Endkonto, Start 1,00; Spannen über die 20 Kombinationen)

| ETF | Halten (größter Rückgang) | Montag-Wiederkauf | Neue Regel, Basis | Neue Regel, pessimistisch | Größter Rückgang neue Regel (Median) | Zeit im Markt | Handelsrunden je Jahr |
|---|---|---|---|---|---|---|---|
| AIQ | 4,40 (−45 %) | 2,77 – 4,33 | 0,95 – 2,57 | 0,93 – 2,56 | −23 % | 53 % | 4 |
| CHAT | 3,73 (−31 %) | 2,52 – 3,06 | 1,27 – 2,44 | 1,22 – 2,46 | −28 % | 59 % | 7 |
| AGIX | 1,92 (−32 %) | 1,31 – 1,96 | 1,05 – 1,64 | 0,98 – 1,63 | −21 % | 61 % | 5 |
| QTUM | 6,27 (−39 %) | 4,43 – 6,01 | 1,22 – 3,51 | 1,16 – 3,07 | −23 % | 51 % | 5 |
| SMH | 13,02 (−45 %) | 8,62 – 11,39 | 1,16 – 5,58 | 1,02 – 5,28 | −37 % | 50 % | 6 |
| SOXX | 10,50 (−46 %) | 5,90 – 7,34 | 0,99 – 4,91 | 0,86 – 4,66 | −31 % | 44 % | 6 |
| ITA | 2,17 (−51 %) | 2,12 – 2,58 | 0,99 – 1,81 | 0,99 – 1,79 | −24 % | 51 % | 2 |
| XAR | 2,74 (−47 %) | 2,76 – 4,64 | 0,90 – 2,24 | 0,89 – 2,21 | −26 % | 44 % | 3 |
| PPA | 2,80 (−44 %) | 2,68 – 4,12 | 1,12 – 2,26 | 1,12 – 2,26 | −26 % | 69 % | 3 |
| SHLD | 2,43 (−25 %) | 1,92 – 2,86 | 1,53 – 2,49 | 1,52 – 2,49 | −17 % | 73 % | 3 |
| EUAD | 1,60 (−22 %) | 2,02 – 2,14 | 0,97 – 1,49 | 0,87 – 1,46 | −26 % | 57 % | 6 |
| NATO | 1,45 (−17 %) | 1,24 – 1,69 | 0,89 – 1,38 | 0,86 – 1,34 | −17 % | 68 % | 5 |
| REMX | 0,77 (−74 %) | 1,74 – 3,57 | 0,76 – 1,14 | 0,71 – 1,11 | −24 % | 7 % | 2 |
| URA | 3,01 (−52 %) | 3,30 – 5,15 | 0,78 – 1,77 | 0,69 – 1,25 | −34 % | 16 % | 5 |
| URNM | 3,77 (−52 %) | 4,60 – 13,55 | 1,11 – 2,12 | 0,92 – 1,97 | −31 % | 20 % | 6 |
| DMAT | 1,51 (−56 %) | 1,33 – 1,47 | 1,13 – 1,42 | 1,10 – 1,41 | −18 % | 9 % | 2 |
| SETM | 1,40 (−44 %) | 1,31 – 1,54 | 0,63 – 1,21 | 0,51 – 1,22 | −30 % | 19 % | 4 |
| TQQQ | 13,68 (−82 %) | 7,44 – 20,90 | 0,90 – 2,67 | 0,50 – 2,40 | −36 % | 25 % | 7 |
| QQQ | 4,67 (−36 %) | 3,80 – 4,62 | 1,50 – 2,82 | 1,51 – 2,78 | −24 % | 64 % | 3 |
| UPRO | 6,98 (−77 %) | 4,60 – 10,06 | 0,61 – 1,76 | 0,32 – 1,57 | −48 % | 41 % | 7 |
| SOXL | 20,27 (−91 %) | 4,66 – 51,79 | 0,30 – 1,68 | 0,12 – 1,40 | −59 % | 16 % | 12 |
| TNA | 0,88 (−88 %) | 1,85 – 2,88 | 0,17 – 1,12 | 0,13 – 1,11 | −40 % | 6 % | 2 |

Rückgang, Zeit im Markt und Handelsrunden: Median über die 20 Kombinationen
(Basis). WQTM, EUV und DRAM stehen in der Ergebnisdatei.

## Themen-ETFs: Abstand gegen Trailing-Weite (Median über 17 ETFs, Basis)

| Abstand | Konto/Halten T 5 % | 6 % | 7 % | 8 % | Rückgang Regel/Halten T 5 % | 6 % | 7 % | 8 % | Zeit im Markt T 5 % | 8 % |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 % (Vergleich) | 0,87 | 0,82 | 0,87 | 0,90 | 0,94 | 1,04 | 1,02 | 1,01 | 84 % | 98 % |
| 1 % | 0,58 | 0,66 | 0,73 | 0,61 | 0,72 | 0,82 | 0,76 | 0,94 | 61 % | 82 % |
| 2 % | 0,51 | 0,62 | 0,59 | 0,65 | 0,67 | 0,63 | 0,67 | 0,74 | 48 % | 72 % |
| 3 % | 0,42 | 0,56 | 0,63 | 0,62 | 0,48 | 0,50 | 0,64 | 0,67 | 39 % | 59 % |
| 4 % | 0,43 | 0,48 | 0,54 | 0,65 | 0,50 | 0,46 | 0,55 | 0,65 | 32 % | 52 % |
| 5 % | 0,40 | 0,50 | 0,49 | 0,56 | 0,50 | 0,44 | 0,52 | 0,61 | 27 % | 48 % |

Pessimistische Ausführung und 10 bps senken die Konto-Werte je Zelle um 0
bis 0,10 (z. B. T 5 %/A 2 %: 0,51 → 0,48 bzw. 0,47).

## Die vorab festgelegten Urteile (A = 1–5 %)

| Fassung | Gruppe | Fälle | Konto > Halten | Sharpe > Halten | davon sicher | Konto > Montag-Wiederkauf | davon sicher | Rückgang kleiner als Halten |
|---|---|---|---|---|---|---|---|---|
| Basis | Themen | 340 | 19 | 35 | 0 | 7 | 0 | 297 |
| Basis | gehebelt/Index | 100 | 8 | 0 | 0 | 0 | 0 | 94 |
| Pessimistisch | Themen | 340 | 18 | 28 | 0 | 10 | 0 | 285 |
| Pessimistisch | gehebelt/Index | 100 | 7 | 0 | 0 | 0 | 0 | 91 |

**Für keine Kombination belegt.** Die 19 bzw. 8 Fälle mit höherem Endkonto
(Basis) liegen bei REMX (18), einmal bei SHLD, und bei TNA (8); bei REMX und
TNA verlor das Halten Geld.

## Ablesung

- Der Abstand behebt das sofortige Zurückkaufen: am Tag des Verkaufs fallen
  bei A = 1 % noch rund 38 % der Rückkäufe, bei 2 % 13 bis 17 %, ab 4 % keine
  mehr (Median über die ETFs; bei A = 0 % waren es 86 bis 89 %). Die
  Handelsrunden sinken von 8 bis 16 auf 2,5 bis 12 je Jahr.
- Der Schutz ist echt: der größte Rückgang ist in 297 von 340 Fällen kleiner
  als beim Halten, im Median das 0,64-Fache (bei A ≥ 3 % je nach Trailing das
  0,44- bis 0,67-Fache).
- Der Preis ist hoch: Jede Runde, nach der der Kurs weiterläuft, kostet den
  Abstand A (Verkauf zu S, Rückkauf zu S × (1 + A)). Bei gut vier Runden je
  Jahr summiert sich das; das Endkonto liegt im Median beim 0,58-Fachen des
  Haltens, bei TQQQ, QQQ, UPRO, SOXL, TNA beim 0,15-Fachen.
- Die Regel ist je nach Kombination im Median nur 27 bis 82 % der Zeit
  investiert; die längste Wartezeit
  liegt im Median bei 450 bis 770 Tagen. Am Datenende ist sie in 297 von 440
  Fällen draußen, im Median seit 93 Tagen (REMX und TNA seit über vier
  Jahren).
- Gegenüber dem Montag-Wiederkauf ist das Endkonto nur in 7 von 340 Fällen
  höher.

## Was das nicht trägt

Start nur am ersten Montag des Datenzeitraums; Gleichlauf der Themen-ETFs;
dünner Handel bei DMAT und NATO; pauschale Kosten.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_reentry3_prereg_2026-10-05.md`, `opaw_reentry3.py`,
`results_opaw_reentry3_{base,cost10,pess}_2026-10-05.{txt,csv}`); nicht im
Repo.

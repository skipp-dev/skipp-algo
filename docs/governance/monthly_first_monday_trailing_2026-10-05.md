# Monatsregel: Kauf am ersten Montag, Trailing Stop, sonst Verkauf am letzten Freitag

Stand 2026-10-05. Auftrag des Operators vom selben Tag. Eine Rückschau, kein
Track Record. Anschluss an `trailing_reentry_with_buffer_2026-10-05.md`.

## Regel (vorregistriert in `opaw_monthly_prereg_2026-10-05.md`)

- Jeden Monat Kauf zur Eröffnung des ersten Montags. Ist er kein Handelstag
  (Labor Day ist jedes Jahr der erste Montag im September), am nächsten
  Handelstag derselben Woche.
- Trailing Stop T = 5, 6, 7 oder 8 % unter dem Höchstkurs seit dem Kauf. Nach
  einem Stop-Verkauf draußen bis zum Kauftag des nächsten Monats.
- Ohne Stop-Verkauf: Verkauf zum Schluss des letzten Freitags des Monats
  (ist er kein Handelstag, des letzten Handelstags davor).
- 20 Themen-ETFs (17 auswertbar) und TQQQ, QQQ, UPRO, SOXL, TNA; Mai 2018 bzw.
  ab Fondsstart bis 2026-10-02. Monate, deren Kursdaten erst nach dem ersten
  Montag beginnen (Fondsstart), werden ausgelassen. Drei Ausführungsfassungen:
  Basis (2 bps je Order), 10 bps, pessimistisch.
- Vergleiche: Halten; Montag-Wiederkauf (wöchentlich, gleicher Trailing Stop);
  **Monatsfenster ohne Stop** (gleicher Kalender, kein Trailing Stop).

## Ergebnis je ETF (Endkonto, Start 1,00; Basis)

| ETF | Halten (größter Rückgang) | Montag-Wiederkauf (T 5–8 %) | Monatsfenster ohne Stop | Monatsregel T 5 % | 6 % | 7 % | 8 % | Größter Rückgang Monatsregel | Zeit im Markt | Monate mit Stop |
|---|---|---|---|---|---|---|---|---|---|---|
| AIQ | 4,40 (−45 %) | 2,77 – 4,33 | 3,41 (−39 %) | 2,57 | 2,94 | 2,98 | 3,19 | −27 bis −42 % | 60–75 % | 30–58 % |
| CHAT | 3,73 (−31 %) | 2,52 – 3,06 | 3,13 (−26 %) | 2,13 | 2,00 | 2,05 | 1,94 | −15 bis −21 % | 51–68 % | 50–72 % |
| AGIX | 1,92 (−32 %) | 1,31 – 1,96 | 2,29 (−22 %) | 1,61 | 2,02 | 1,93 | 2,18 | −14 bis −19 % | 47–72 % | 31–69 % |
| QTUM | 6,27 (−39 %) | 4,43 – 6,01 | 4,49 (−37 %) | 2,51 | 3,14 | 4,00 | 3,79 | −23 bis −37 % | 56–73 % | 35–65 % |
| SMH | 13,02 (−45 %) | 8,62 – 11,39 | 10,15 (−35 %) | 6,29 | 5,54 | 5,60 | 5,36 | −26 bis −45 % | 46–65 % | 50–80 % |
| SOXX | 10,50 (−46 %) | 5,90 – 7,34 | 9,14 (−36 %) | 5,40 | 4,43 | 3,75 | 5,58 | −26 bis −45 % | 44–65 % | 50–83 % |
| ITA | 2,17 (−51 %) | 2,12 – 2,58 | 1,64 (−52 %) | 1,89 | 2,16 | 2,19 | 2,02 | −27 bis −39 % | 64–79 % | 26–53 % |
| XAR | 2,74 (−47 %) | 2,76 – 4,64 | 1,70 (−47 %) | 1,49 | 2,15 | 2,41 | 2,36 | −34 bis −45 % | 57–77 % | 30–67 % |
| PPA | 2,80 (−44 %) | 2,68 – 4,12 | 1,91 (−44 %) | 1,71 | 2,71 | 2,40 | 2,42 | −18 bis −39 % | 69–81 % | 18–46 % |
| SHLD | 2,43 (−25 %) | 1,92 – 2,86 | 1,81 (−36 %) | 1,71 | 1,82 | 1,72 | 1,73 | −25 bis −33 % | 62–80 % | 19–50 % |
| EUAD | 1,60 (−22 %) | 2,02 – 2,14 | 1,42 (−29 %) | 1,05 | 1,38 | 1,28 | 1,32 | −15 bis −22 % | 49–74 % | 30–74 % |
| NATO | 1,45 (−17 %) | 1,24 – 1,69 | 1,21 (−24 %) | 1,15 | 1,07 | 1,16 | 1,23 | −18 bis −21 % | 58–81 % | 21–58 % |
| REMX | 0,77 (−74 %) | 1,74 – 3,57 | 0,42 (−79 %) | 1,59 | 1,32 | 0,66 | 1,07 | −40 bis −63 % | 38–59 % | 67–95 % |
| URA | 3,01 (−52 %) | 3,30 – 5,15 | 1,15 (−53 %) | 2,00 | 3,36 | 2,10 | 1,98 | −24 bis −43 % | 36–57 % | 65–91 % |
| URNM | 3,77 (−52 %) | 4,60 – 13,55 | 1,32 (−53 %) | 2,54 | 4,74 | 3,09 | 2,79 | −19 bis −42 % | 28–48 % | 80–95 % |
| DMAT | 1,51 (−56 %) | 1,33 – 1,47 | 1,54 (−56 %) | 1,02 | 0,99 | 0,80 | 0,65 | −44 bis −70 % | 44–61 % | 67–82 % |
| SETM | 1,40 (−44 %) | 1,31 – 1,54 | 1,29 (−45 %) | 1,07 | 1,14 | 0,86 | 0,92 | −40 bis −55 % | 38–62 % | 61–95 % |
| TQQQ | 13,68 (−82 %) | 7,44 – 20,90 | 11,68 (−75 %) | 3,90 | 4,75 | 6,36 | 15,46 | −28 bis −44 % | 23–40 % | 82–96 % |
| QQQ | 4,67 (−36 %) | 3,80 – 4,62 | 3,86 (−33 %) | 3,42 | 3,91 | 4,18 | 3,48 | −19 bis −25 % | 64–78 % | 27–48 % |
| UPRO | 6,98 (−77 %) | 4,60 – 10,06 | 5,60 (−77 %) | 5,70 | 5,06 | 7,81 | 10,69 | −32 bis −41 % | 37–55 % | 63–89 % |
| SOXL | 20,27 (−91 %) | 4,66 – 51,79 | 29,09 (−81 %) | 1,58 | 2,80 | 7,87 | 18,46 | −42 bis −49 % | 11–22 % | 99–100 % |
| TNA | 0,88 (−88 %) | 1,85 – 2,88 | 0,63 (−91 %) | 3,04 | 3,64 | 6,26 | 3,72 | −49 bis −71 % | 18–33 % | 93–99 % |

Spannen über T = 5–8 %. WQTM, EUV und DRAM stehen in der Ergebnisdatei.

## Zusammenfassung (auswertbare ETFs)

| | Themen-ETFs (17) | TQQQ, QQQ, UPRO, SOXL, TNA (5) |
|---|---|---|
| Monatsfenster ohne Stop: Endkonto / Halten (Median) | 0,77 | 0,83 |
| Monatsfenster ohne Stop: Zeit im Markt | 87 % | 87 % |
| Monatsregel: Endkonto / Halten (Median, T 5–8 %) | 0,71 | 0,83 |
| Monatsregel: größter Rückgang / Halten (Median) | 0,79 | 0,53 |
| Monatsregel: Zeit im Markt (Median) | 62 % | 33 % |
| Endkonto über Halten | 9 von 68 | 7 von 20 |
| Sharpe über Halten (davon sicher) | 21 von 68 (0) | 16 von 20 (0) |
| Endkonto über Montag-Wiederkauf (davon sicher) | 4 von 68 (0) | 10 von 20 (0) |
| Endkonto über Monatsfenster ohne Stop (davon sicher) | 24 von 68 (0) | 10 von 20 (0) |
| Rückgang kleiner als Halten | 55 von 68 | 20 von 20 |

Pessimistische Ausführung: Themen-ETFs 0,70 statt 0,71, gehebelt/Index 0,76
statt 0,83. Mit 10 bps: je Trailing 0,59 bis 0,71 (Themen) und 0,62 bis 0,96
(gehebelt/Index).

**Urteile 1 bis 3: für kein T belegt** — weder besser als Halten, noch besser
als der Montag-Wiederkauf, noch ein gesicherter Beitrag des Trailing Stops
innerhalb des Monatsfensters.

## Ablesung

- **Der Kalender allein kostet.** Das Monatsfenster ohne Stop ist 87 % der
  Zeit investiert und erreicht im Median nur das 0,77-Fache des Haltens, bei
  gleichem Rückgang; über dem Halten liegt es bei 2 von 17 Themen-ETFs.
- **Ob die ausgelassenen Tage um den Monatswechsel überproportional zählen,
  hängt am Thema.** Gemessen am Anteil des (logarithmierten) Halte-Ertrags,
  den das Monatsfenster einfängt: bei 11 von 16 Themen-ETFs mit positivem
  Halte-Ertrag weniger als der Zeitanteil von 87 % (Median 76 %) — sehr
  deutlich bei Rüstung (ITA, XAR, PPA, SHLD, NATO: 51 bis 67 %) und Uran (URA
  13 %, URNM 21 %), nicht bei Halbleitern und KI (SMH 90 %, SOXX 94 %, CHAT
  87 %, AGIX über 100 %) und nicht bei TQQQ, QQQ, UPRO, SOXL (88 bis über
  100 %). Der vorab notierte Turn-of-the-Month-Effekt zeigt sich also nicht
  durchgehend.
- **Der Trailing Stop greift oft.** Bei Themen-ETFs wird in 35 % (T 8 %) bis
  72 % (T 5 %) der Monate per Stop verkauft, bei den gehebelten in 82 bis
  96 %; danach fehlt der Rest des Monats.
- **Themen-ETFs:** weniger Ertrag (0,71-fach) bei etwas kleinerem Rückgang
  (0,79-fach). Gegen den wöchentlichen Montag-Wiederkauf ist das Endkonto nur
  in 4 von 68 Fällen höher.
- **Gehebelte ETFs:** der Rückgang halbiert sich (0,53-fach), das Endkonto
  liegt im Median beim 0,83-Fachen, bei T 8 % über dem Halten in 3 von 5
  (TQQQ 15,46 gegen 13,68; UPRO 10,69 gegen 6,98; TNA 3,72 gegen 0,88). Fünf
  stark gleichlaufende Werte und vier Weiten: ein Hinweis, kein Beleg.

## Nachtrag (explorativ, nicht Teil der Urteile): Kalenderjahre

Nach Sicht der Ergebnisse gerechnet, um zu sehen, woher der Abstand zum
Halten kommt (`opaw_monthly_years.py`, Basisfassung; 2018 ab Mai bzw. ab
Fondsstart, 2026 bis 2. Oktober). Gezählt wird je ETF, Jahr und Stop-Weite.

| Jahr des Haltens | Gruppe | Regel vor dem Halten | Median Regel − Halten |
|---|---|---|---|
| im Minus | Themen-ETFs | 105 von 160 (66 %) | +4,5 Punkte |
| im Minus | TQQQ, QQQ, UPRO, SOXL, TNA | 45 von 48 (94 %) | +40,4 Punkte |
| im Plus | Themen-ETFs | 59 von 300 (20 %) | −14,8 Punkte |
| im Plus | TQQQ, QQQ, UPRO, SOXL, TNA | 33 von 132 (25 %) | −21,9 Punkte |

| Jahr | Halten (Median) | Regel (Median) | Regel vorn |
|---|---|---|---|
| 2018 | −12,8 % | −8,0 % | 37 von 56 |
| 2019 | +38,4 % | +33,1 % | 18 von 60 |
| 2020 | +47,5 % | +36,1 % | 32 von 60 |
| 2021 | +41,5 % | −0,5 % | 0 von 60 |
| 2022 | −32,5 % | −4,2 % | 49 von 64 |
| 2023 | +37,8 % | +1,3 % | 5 von 76 |
| 2024 | +13,5 % | +17,8 % | 50 von 88 |
| 2025 | +45,5 % | +33,4 % | 23 von 88 |
| 2026 | +26,1 % | +16,1 % | 28 von 88 |

- **Die Regel wirkt wie eine Absturzversicherung.** In Verlustjahren liegt
  sie meist vorn, in Gewinnjahren meist hinten. Beispiel TQQQ: 2022 Halten
  −79,2 %, Regel +2,6 bis −3,6 %; 2023 Halten +193,4 %, Regel −6,1 bis
  +42,4 %.
- **Bei den gehebelten ETFs hängt das Ergebnis an einem Jahr.** In 18 von 20
  Kombinationen ist 2022 das Jahr mit dem größten Vorsprung (sonst 2020, TNA
  bei T 7 und 8 %). Setzt man Regel und Halten für 2022 gleich, fällt der
  Median Konto/Halten von 0,83 auf 0,45, und über dem Halten bleiben 4 von 20
  statt 7 (alle vier TNA). TQQQ bei T 8 %: 1,13 → 0,24; UPRO bei T 8 %:
  1,53 → 0,78; SOXL bei T 8 %: 0,91 → 0,09.
- **Bei den Themen-ETFs nicht.** Mit 2022 im Zeitraum (44 Kombinationen)
  liegt der Median bei 0,67, ohne 2022 bei 0,69; das beste Jahr verteilt sich
  (2022 nur bei 17 von 68).

Der Hinweis bei T 8 % ist damit im Wesentlichen das Jahr 2022: eine einzige
Episode, kein Beleg.

## Was das nicht trägt

Gleichlauf der ETFs; dünner Handel bei DMAT und NATO; pauschale Kosten; ein
einziger Kalender (erster Montag / letzter Freitag) ohne Gegenprobe mit
anderen Wochentagen.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_monthly_prereg_2026-10-05.md`, `opaw_monthly.py`,
`results_opaw_monthly_{base,cost10,pess}_2026-10-05.{txt,csv}`,
`opaw_monthly_years.py`, `results_opaw_monthly_years_2026-10-05.{txt,csv}`,
`results_opaw_monthly_years_dependence_2026-10-05.csv`); nicht im Repo.

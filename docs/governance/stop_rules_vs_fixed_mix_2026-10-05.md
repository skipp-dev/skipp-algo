# Stop-Regeln gegen „einfach weniger investieren" (festes Gemisch mit gleichem Rückgang)

Stand 2026-10-05. Eine Rückschau, kein Track Record. Anschluss an
`monthly_first_monday_trailing_2026-10-05.md` und die Memos der Reihe davor.
Kein neuer Regel-Kandidat, sondern ein fairer Maßstab für die schon
gerechneten Regeln.

## Frage und Festlegung (vorregistriert in `opaw_fairmix_prereg_2026-10-05.md`)

Die Trailing-Stop-Regeln senken den größten Rückgang und kosten Ertrag.
Bekommt man denselben Schutz billiger, indem man dauerhaft nur einen Teil des
Geldes in den ETF legt?

- **Regeln (unverändert):** R0 Monatsfenster ohne Stop; R1 Montag-Wiederkauf
  (Trailing Stop T = 5 bis 8 %, nach einem Stop Kauf am nächsten Montag); R2
  Wiedereinstieg erst A = 1 bis 5 % über dem Ausstiegskurs (T = 5 bis 8 %);
  R3 Monatsregel (Kauf erster Montag, T = 5 bis 8 %, sonst Verkauf letzter
  Freitag).
- **Gegner:** festes Gemisch, Anteil w im ETF, Rest unverzinst; Kauf zur
  ersten Eröffnung, am Monatsende zurück auf w, Kosten wie bei der Regel,
  kein Hebel (w höchstens 1).
- **Hauptvergleich:** w so, dass der größte Rückgang des Gemischs dem der
  Regel gleicht. Fiel die Regel mindestens so tief wie der ETF, ist w = 1.
- **Nebenvergleich:** w = Anteil der Zeit, den die Regel investiert war.
- **Prüfgröße:** Unterschied der wöchentlichen Log-Erträge Regel minus
  Gemisch, 95 %-Intervall über Wochen. Belegt ist eine Seite nur, wenn das
  Intervall bei mindestens der Hälfte der ETFs einer Gruppe ganz auf ihrer
  Seite liegt, in der Basis- und in der pessimistischen Fassung.
- 17 Themen-ETFs und TQQQ, QQQ, UPRO, SOXL, TNA; Mai 2018 bzw. Fondsstart bis
  2026-10-02; Basis (2 bps je Order), 10 bps, pessimistisch.

## Ergebnis: gleicher größter Rückgang

Verhältnis = Endkonto der Regel geteilt durch Endkonto des Gemischs, ab dem
ersten Freitag gerechnet (siehe „Start-Artefakt"). Ein Fall ist ein ETF mit
einer Stellgröße.

| Gruppe | Regel | Fälle | Median w | Verhältnis Basis | pessimistisch | 10 bps | Regel vorn | Regel gesichert | Gemisch gesichert |
|---|---|---|---|---|---|---|---|---|---|
| Themen-ETFs | R0 Monatsfenster ohne Stop | 17 | 1,00 | 0,83 | 0,83 | 0,80 | 4 | 0 | 2 |
| Themen-ETFs | R1 Montag-Wiederkauf | 68 | 0,79 | 1,26 | 1,12 | 1,02 | 45 | 10 | 0 |
| Themen-ETFs | R2 Wiedereinstieg mit Abstand | 340 | 0,59 | 0,77 | 0,71 | 0,72 | 63 | 5 | 25 |
| Themen-ETFs | R3 Monatsregel | 68 | 0,75 | 0,90 | 0,84 | 0,76 | 27 | 0 | 0 |
| Gehebelt / Index | R0 Monatsfenster ohne Stop | 5 | 0,93 | 0,93 | 0,93 | 0,77 | 2 | 0 | 0 |
| Gehebelt / Index | R1 Montag-Wiederkauf | 20 | 0,59 | 1,47 | 1,11 | 1,00 | 17 | 0 | 0 |
| Gehebelt / Index | R2 Wiedereinstieg mit Abstand | 100 | 0,42 | 0,49 | 0,45 | 0,42 | 2 | 0 | 12 |
| Gehebelt / Index | R3 Monatsregel | 20 | 0,40 | 1,84 | 1,70 | 1,50 | 18 | 2 | 0 |

Nach Stop-Weite (Basis, Median des Verhältnisses bei T = 5 / 6 / 7 / 8 %):

| Gruppe | R1 Montag-Wiederkauf | R3 Monatsregel |
|---|---|---|
| Themen-ETFs | 1,25 / 1,29 / 1,08 / 1,28 | 1,01 / 0,93 / 0,95 / 0,79 |
| Gehebelt / Index | 1,24 / 1,06 / 1,90 / 2,22 | 1,60 / 1,38 / 1,88 / 3,06 |

**Vorregistriertes Urteil: für keine Regel und keine Stellgröße ist ein
Unterschied belegt**, weder zugunsten der Regel noch des Gemischs. Verlangt
war die Hälfte der ETFs in beiden Fassungen. Am nächsten kamen R1 bei
T = 6 % (Regel gesichert bei 5 von 17 Themen-ETFs in der Basisfassung) und R2
bei T = 7 %, A = 1 % (Gemisch gesichert bei 2 von 5 gehebelten ETFs in der
Basisfassung, 3 von 5 pessimistisch).

Gesichert vor dem Gemisch (Basis): R1 bei PPA (T 6, 7, 8 %), SHLD (6, 8 %),
URNM (5, 6 %), XAR (8 %), EUAD (6 %), REMX (6 %); R3 bei TQQQ (8 %) und QQQ
(7 %). Pessimistisch bleiben davon sieben, alle R1.

In 15 der 68 Themen-Fälle von R1 und in 13 der 68 von R3 fiel die Regel
mindestens so tief wie der ETF selbst (w = 1); dort liegt sie beim Endkonto
in 1 von 15 bzw. 0 von 13 Fällen vorn.

## Nebenvergleich: gleiche Marktzeit (Basis)

| Gruppe | Regel | Marktzeit (Median) | Endkonto Regel / Gemisch | Rückgang Regel / Gemisch | mehr Geld und kleinerer Rückgang | weniger Geld und größerer Rückgang |
|---|---|---|---|---|---|---|
| Themen-ETFs | R0 | 87 % | 0,88 | 1,14 | 3 von 17 | 12 von 17 |
| Themen-ETFs | R1 | 90 % | 1,08 | 0,92 | 38 von 68 | 15 von 68 |
| Themen-ETFs | R2 | 48 % | 0,84 | 1,43 | 23 von 340 | 201 von 340 |
| Themen-ETFs | R3 | 62 % | 1,00 | 1,21 | 13 von 68 | 31 von 68 |
| Gehebelt / Index | R0 | 87 % | 1,01 | 1,06 | 2 von 5 | 2 von 5 |
| Gehebelt / Index | R1 | 71 % | 1,25 | 0,89 | 11 von 20 | 0 von 20 |
| Gehebelt / Index | R2 | 27 % | 0,65 | 1,44 | 0 von 100 | 81 von 100 |
| Gehebelt / Index | R3 | 33 % | 2,02 | 1,08 | 10 von 20 | 1 von 20 |

## Explorativ (nicht Teil des Urteils): Kalenderjahre

Nach Sicht der Ergebnisse gerechnet (`opaw_fairmix_years.py`, Basis,
Hauptvergleich).

| Gruppe | Regel | Verhältnis (Median) | ohne das jeweils beste Jahr | Regel vorn | ohne das beste Jahr | häufigstes bestes Jahr |
|---|---|---|---|---|---|---|
| Themen-ETFs | R1 | 1,26 | 0,97 | 45 von 68 | 33 von 68 | 2024 (20), 2020 (19) |
| Gehebelt / Index | R1 | 1,47 | 0,82 | 17 von 20 | 4 von 20 | 2020 (18) |
| Themen-ETFs | R3 | 0,90 | 0,80 | 27 von 68 | 14 von 68 | 2025 (14), 2026 (13) |
| Gehebelt / Index | R3 | 1,83 | 1,17 | 18 von 20 | 15 von 20 | 2020 (16) |

- R1 gewinnt gegen das Gemisch vor allem im Jahr des Corona-Einbruchs: 2020
  liegt die Regel bei den Themen-ETFs in 39 von 40 Fällen vorn (Median 1,24),
  bei den gehebelten in 20 von 20 (Median 1,91). 2021 liegt sie bei den
  gehebelten in 0 von 20 Fällen vorn.
- Das Jahr 2022 trägt den Vorsprung von R1 nicht: mit 2022 im Zeitraum
  liegt der Median bei 1,35 (Themen) bzw. 1,47 (gehebelt), ohne 2022 bei 1,38
  bzw. 1,37.
- R3 bei den gehebelten ETFs bleibt auch ohne das beste Jahr vorn (1,17);
  ohne 2022 liegt der Median bei 1,38. Die Jahre 2020 (Median 1,74) und 2022
  (1,42) gehen in 20 von 20 Fällen an die Regel, 2021 und 2023 in 2 von 20.

## Start-Artefakt in den bisherigen Memos der Reihe

Beim Nachrechnen fiel auf: In allen Memos dieser Reihe zählt das Halten ab
dem ersten Datentag, die Regeln beginnen aber erst an ihrem ersten Montag.
Das Halten hat dadurch einige Tage Vorsprung, je nach Wert: TQQQ +9,7 %, SOXL
+15,6 %, TNA +6,1 %, UPRO +3,3 %, QQQ +3,2 %, SOXX +5,3 %, SMH +4,3 %, URA
+4,6 %; bei der Monatsregel außerdem CHAT +9,7 % und AGIX −12,9 %
(Fondsstart mitten im Monat). Die geprüften Wochen-Intervalle und damit alle
Urteile sind davon nicht berührt (die erste, unvollständige Woche zählt dort
nicht). Betroffen sind die beschreibenden Endkonto-Vergleiche:

| Aussage | wie berichtet | ab gleichem Starttag |
|---|---|---|
| Monatsregel, Themen-ETFs: Endkonto über Halten | 9 von 68 | 6 von 68 |
| Monatsregel, Themen-ETFs: Median Endkonto / Halten | 0,71 | 0,71 |
| Monatsregel, gehebelt: Endkonto über Halten | 7 von 20 | 8 von 20 |
| Monatsregel, gehebelt: Median Endkonto / Halten | 0,83 | 0,85 |
| Monatsregel, gehebelt, T = 8 %: über Halten | 3 von 5 | 4 von 5 (SOXL 18,46 gegen 17,54) |
| Montag-Wiederkauf, Themen-ETFs: Endkonto über Halten | 34 von 68 | 35 von 68 |
| Montag-Wiederkauf, gehebelt: Endkonto über Halten | 9 von 20 | 11 von 20 |

Dieses Memo rechnet die Verhältnisse deshalb ab dem ersten Freitag. Wie
festgelegt ab dem ersten Datentag lauten die Mediane 1,26 / 0,77 / 0,90
(Themen, R1 / R2 / R3) und 1,41 / 0,48 / 1,82 (gehebelt).

## Ablesung

- **Belegt ist nichts**, in keiner Richtung.
- **In der Richtung** war der Montag-Wiederkauf die billigere Absicherung als
  das feste Gemisch (Themen 1,26-fach, gehebelt 1,47-fach), der Wiedereinstieg
  mit Abstand die teurere (0,77 und 0,49). Die Monatsregel lag bei
  Themen-ETFs knapp hinter dem Gemisch (0,90), bei den gehebelten davor
  (1,84).
- **Der Vorsprung des Montag-Wiederkaufs stammt aus einzelnen Jahren**, vor
  allem aus 2020. Ohne das jeweils beste Jahr liegt der Median bei 0,97
  (Themen) und 0,82 (gehebelt).
- **Kosten zehren ihn auf:** mit 10 bps je Order liegt der Median bei 1,02
  und 1,00, pessimistisch bei 1,12 und 1,11.
- **Die vorab notierte Erwartung** („Themen-ETFs: das Gemisch liegt vorn")
  traf für R2 und knapp für R3 zu, für R1 nicht.

## Was das nicht trägt

Zwei Einbrüche (2020, 2022) im ganzen Zeitraum; gleichlaufende ETFs; w ist im
Nachhinein aus dem eingetretenen Rückgang bestimmt; der größte Rückgang ist
ein einzelnes Ereignis je Verlauf; Bargeld unverzinst.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_fairmix_prereg_2026-10-05.md`, `opaw_fairmix.py`,
`results_opaw_fairmix_2026-10-05.{txt,csv}`, `opaw_fairmix_years.py`,
`results_opaw_fairmix_years_2026-10-05.{txt,csv}`, `opaw_headstart.py`,
`results_opaw_headstart_2026-10-05.{txt,csv}`); nicht im Repo.

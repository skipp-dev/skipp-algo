# „One Percent A Week" (TASC 2026.03) nachgerechnet: TQQQ und QQQ 2018–2026

Stand 2026-10-05. Auftrag des Operators vom selben Tag, dazu Varianten mit
Stop-Loss 1–4 % und (Nachtrag unten) mit Trailing Stops 1–5 %. Eine
Rückschau, kein Track Record.

> **Korrektur, gleicher Tag.** Das vorregistrierte Placebo V2 war fehlerhaft:
> Es kauft zur Montagseröffnung nur in den Wochen, in denen der Kurs danach
> nachweislich 1 % darunter fiel, und ist damit gegenüber dem Rücksetzer-Kauf
> um mindestens 1 % benachteiligt. Punkt 2 des Urteils war deshalb leicht zu
> bestehen. Gegen einen fairen Vergleich (Kauf zur Montagseröffnung in **jeder**
> Woche, gleiche Ausstiege) trägt der Rücksetzer-Einstieg **nichts Belegtes**
> bei: TQQQ +0,28 % je Woche [−0,06; +0,64], QQQ −0,06 % [−0,20; +0,08].
> Das Urteil „belegt vorteilhaft" unten ist damit **zurückgezogen**. Was bleibt:
> Long Nasdaq in einer Hausse verdient Geld, auch mit dieser Regel; einen
> eigenen Beitrag der Regel zeigen die Daten nicht. Einzelheiten im Abschnitt
> „Fairer Vergleich".

## Die Regel (veröffentlichter Pine-Code, PineCoders)

Montag Eröffnung merken; Limit-Kauf 1 % darunter; ab dem nächsten Handelstag
Gewinnziel +1 % über dem Einstieg; fällt der Kurs 0,5 % unter den Einstieg,
wird das Ziel durch „Verkauf zum Einstiegspreis" ersetzt; Freitag zum Schluss
alles verkaufen. Kein Stop-Loss. Gedacht für TQQQ (Nasdaq-100, dreifach).

## Vorab festgelegt

`opaw_prereg_2026-10-05.md` (vor dem ersten Kurs): Databento `XNAS.ITCH`
1m-Kerzen, reguläre Sitzung, 2018-05 bis 2026-10 (397 Wochen; Kosten 0,00
USD). Limit-Orders nur bei Durchhandeln um einen Cent; Market-Ausstiege
(Freitag, Stop) 2 bps. Urteil „belegt vorteilhaft" nur, wenn (1) Mittel je
Trade mit Intervall über null, (2) besser als ein Placebo-Einstieg zur
Montagseröffnung mit denselben Ausstiegen, (3) positiv in beiden Hälften.

## Ergebnis TQQQ (je Trade nach Kosten, 95 %-Intervall über Wochen)

| Variante | Trades | Mittel je Trade | minus Placebo | schlechtester Trade | 1. / 2. Hälfte |
|---|---|---|---|---|---|
| **Original** | 337 | **+0,40 % [+0,09; +0,70]** | +0,75 % [+0,36; +1,14] | −17,0 % | +0,39 / +0,40 |
| Stop 1 % | 337 | +0,23 % [−0,00; +0,50] | +0,56 % | −4,3 % | +0,15 / +0,31 |
| Stop 2 % | 337 | +0,16 % [−0,09; +0,44] | +0,49 % | −5,1 % | +0,07 / +0,25 |
| Stop 3 % | 337 | +0,17 % [−0,09; +0,46] | +0,53 % | −5,1 % | +0,06 / +0,26 |
| Stop 4 % | 337 | +0,19 % [−0,08; +0,49] | +0,52 % | −7,1 % | +0,02 / +0,35 |

**Vorregistriertes Urteil Original: belegt vorteilhaft** (alle drei Punkte
erfüllt). Keine Stop-Variante erfüllt Punkt 1.

Woher der Ertrag kommt: 54 Trades erreichen das Gewinnziel und bringen im
Schnitt +4,25 % (das Ziel wird erst am Folgetag gesetzt; eröffnet TQQQ dann
darüber, wird zum Eröffnungskurs verkauft); 266 enden über die
Break-even-Regel bei ≈ 0; 17 werden am Freitag mit im Schnitt −6,2 %
geschlossen. Ein Stop schneidet diese Ausreißer ab, macht aber aus vielen
späteren Break-even- oder Ziel-Trades Verluste.

## Gegenprobe QQQ (vorab festgelegt, ungehebelt)

Original: 239 Trades, +0,22 % [+0,04; +0,40], minus Placebo +0,45 %
[+0,25; +0,64], Hälften +0,33 / +0,11 — ebenfalls „belegt vorteilhaft".
Stop-Varianten: keine mit Intervall über null.

## Nachträgliche Prüfungen (nicht vorregistriert)

- Gewinnziel erst ab der zweiten Minute aktiv (wie der Pine-Code auf
  Minutenkerzen): unverändert +0,40 %.
- Zufälliger Einstiegszeitpunkt in derselben Woche (50 Ziehungen, dieselben
  Ausstiege): +0,06 % je Trade; Original minus dieses Placebo +0,43 %
  [+0,13; +0,74].
- Kosten 5 bps je Market-Ausstieg und 2 bps je Limit-Ausführung: +0,29 %
  [−0,01; +0,60] — die untere Grenze berührt null.
- Risiko je Woche (Wochen ohne Trade = 0): Original +0,34 % bei 2,6 %
  Schwankung, Sharpe 0,94, 11 % der Handelszeit investiert; dauerhaftes
  Halten von TQQQ +1,07 % bei 8,5 % Schwankung, Sharpe 0,90, größter
  Rückgang −78 % (Original bei vollem Einsatz −19 %).
- Seit Veröffentlichung (ab 16.2.2026, vom Autor nicht gesehen): 28 Trades,
  +0,62 % je Trade — zu wenige für ein Urteil, aber kein Widerspruch.

## Ablesung

- Erstmals in dieser Reihe besteht eine Regel die vorab festgelegte Hürde,
  auf TQQQ und auf QQQ. Der Rücksetzer-Einstieg trägt gegenüber beiden
  Placebos rund +0,4 bis +0,75 % je Trade.
- Der Vorsprung ist schmal: bei höheren Kosten berührt das Intervall null.
- Die Regel ist risikoarm im Sinne der Zeit im Markt (11 %), aber nicht im
  Sinne einzelner Trades: ohne Stop bis −17 %.
- Mit dem Einsatz aus dem Code (10 % je Trade) wurden aus 1,00 in 8,4 Jahren
  1,14; bei vollem Einsatz 3,32.
- Ein Stop-Loss verbessert nichts.

## Was das nicht trägt

- Der Autor hat die Regel sehr wahrscheinlich auf dieser Geschichte
  entwickelt; die Rückschau ist deshalb nicht unabhängig. Unabhängig sind nur
  die Wochen seit Februar 2026 (28 Trades).
- Ein Markt (Nasdaq-100) in einer langen Hausse; ein Wert, keine Streuung.
  Ob Rücksetzer-Käufe in einem Bärenmarkt tragen, zeigt nur 2022 (+0,29 %
  je Trade, schlechtester −11 %).
- Ausführung auf Nasdaq-Kerzen, nicht konsolidiert; Teilausführungen und
  Warteschlangen an Limit-Preisen sind über das Durchhandeln um einen Cent nur
  grob berücksichtigt.

Skripte und Einzeltrades: `~/.claude/scripts/family-fill-analysis/`
(`opaw_prereg_2026-10-05.md`, `opaw.py`, `opaw_posthoc.py`,
`results_opaw_*_2026-10-05.txt`); nicht im Repo.

## Fairer Vergleich (nachträglich, nicht vorregistriert)

Je Woche über **alle** 397 Wochen (Wochen ohne Kauf = 0): die Regel (DIP)
gegen „Kauf zur Montagseröffnung jede Woche, identische Ausstiege" (OPEN).
Dieses Vergleichsmaß weiß nichts über den späteren Verlauf der Woche.

| Wert | Variante | DIP je Woche | OPEN je Woche | DIP minus OPEN [95 %] |
|---|---|---|---|---|
| TQQQ | Original | +0,34 % | +0,05 % | +0,28 % [−0,06; +0,64] |
| QQQ | Original | +0,13 % | +0,19 % | −0,06 % [−0,20; +0,08] |

Zum Vergleich dauerhaftes Halten je Woche: TQQQ +1,07 %, QQQ +0,42 %.

## Nachtrag: Trailing Stops statt festem Stop

Vorregistriert in `opaw_trailing_prereg_2026-10-05.md`: Trailing Stop 1–5 %
unter dem Höchstkurs seit dem Kauf; **T** = alle Originalregeln plus Trailing
Stop, **T-frei** = nur Trailing Stop und Freitagsschluss (kein +1-%-Ziel, kein
Break-even).

Je Trade (TQQQ):

| Variante | 1 % | 2 % | 3 % | 4 % | 5 % |
|---|---|---|---|---|---|
| T | +0,02 % | +0,11 % | +0,22 % | +0,17 % | +0,19 % |
| T-frei | −0,01 % | +0,42 % | +0,63 % | +0,91 % | +1,17 % |

Schlechtester Trade mit Trailing Stop −4 bis −10 % (Original −17 %).

Fairer Vergleich je Woche (DIP minus OPEN, 95 %):

| Variante | TQQQ | QQQ |
|---|---|---|
| T 1 % … 5 % | −0,13 bis +0,13 %, alle Intervalle über null hinweg | −0,06 bis +0,04 %, alle über null hinweg |
| T-frei 1 % | −0,19 % [−0,37; −0,00] | −0,04 % |
| T-frei 5 % | +0,27 % [−0,17; +0,70] | −0,19 % [−0,39; −0,00] |

Ablesung:
- Mit den Originalregeln macht ein Trailing Stop die Regel schlechter: er
  verkauft am Kauftag Gewinne zu früh, bevor das Ziel am Folgetag greift.
- Ohne Ziel steigt der Ertrag mit der Weite des Trailing Stops — weil die
  Position länger im steigenden Markt bleibt. Dieselben Ausstiege mit Kauf zur
  Montagseröffnung verdienen ähnlich viel; auf QQQ sogar mehr.
- Was ein weiter Trailing Stop auf TQQQ verändert, ist das Risiko, nicht der
  Ertrag des Einstiegs: T-frei 5 % hatte bei vollem Einsatz einen größten
  Rückgang von −31 % gegenüber −78 % beim dauerhaften Halten (Sharpe 1,32
  gegen 0,90; mit Kauf zur Eröffnung 0,98). Das ist eine Suche über fünf
  Weiten auf einer Hausse-Geschichte, kein Beleg.

Ergebnisdateien: `results_opaw_trailing_{TQQQ,QQQ}_2026-10-05.txt`,
`results_opaw_fair_{TQQQ,QQQ}_2026-10-05.txt`.

## Nachtrag 2: Trailing Stops größer 5 %

Vorregistriert in `opaw_trailing_wide_prereg_2026-10-05.md`: 6, 7, 8, 10, 12,
15, 20 % und „kein Trailing", gemessen am fairen Vergleich (DIP − OPEN je
Woche). Für keine der 26 Weiten-Varianten je Wert liegt die untere
Intervallgrenze über null.

Nur Trailing (TQQQ), je Woche über alle Wochen:

| Trailing | je Trade | DIP je Woche | OPEN je Woche | DIP − OPEN [95 %] | Sharpe | größter Rückgang |
|---|---|---|---|---|---|---|
| 5 % | +1,17 % | +0,99 % | +0,72 % | +0,27 % [−0,17; +0,70] | 1,32 | −31 % |
| 8 % | +1,27 % | +1,08 % | +1,04 % | +0,04 % [−0,37; +0,43] | 1,20 | −45 % |
| 10 % | +1,11 % | +0,94 % | +1,14 % | −0,20 % [−0,57; +0,13] | 0,95 | −56 % |
| 20 % | +1,01 % | +0,86 % | +0,90 % | −0,04 % [−0,38; +0,28] | 0,78 | −71 % |
| kein | +1,18 % | +1,00 % | +1,07 % | −0,07 % [−0,40; +0,24] | 0,89 | −69 % |

Halten TQQQ: +1,07 % je Woche, Sharpe 0,90, Rückgang −78 %.

Auf QQQ ist DIP − OPEN für jede Weite negativ (−0,04 bis −0,27 %). Mit den
Originalregeln liegen alle Weiten ab 7 % nahe dem Original ohne Trailing
(TQQQ +0,31 bis +0,38 % je Trade), weil der Trailing Stop kaum noch auslöst.

Ablesung: Ab etwa 8 % wird der Trailing Stop zur Nebensache — die Regel
nähert sich „Rücksetzer kaufen, bis Freitag halten", und das entspricht im
Ertrag einfachem Wochen-Halten. Der Schutz durch den Trailing Stop wirkt nur
zwischen etwa 3 und 8 %; über Nacht springt der Kurs aber über jeden Stop
(schlechtester Trade ab 6 % Weite −18,8 %).

Ergebnisdateien: `results_opaw_trailing_wide_{TQQQ,QQQ}_2026-10-05.txt`.

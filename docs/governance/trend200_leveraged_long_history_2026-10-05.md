# 200-Tage-Regel für gehebelte ETFs über knapp 100 Jahre

Stand 2026-10-05. Auftrag des Operators vom selben Tag („Bitte Vorschläge 2
bis 4 rechnen"). Eine Rückschau, kein Track Record. Anschluss an
`stop_rules_vs_fixed_mix_2026-10-05.md`. Kandidat `trend200_hebel` der
Kandidaten-Werkstatt; die Festlegung
`festlegungen/trend200_hebel__us_markt_1926.md` wurde vor dem Lauf geschrieben.

## Regel und Daten

- Index: Gesamtertrag des US-Marktes, täglich, 1926-07 bis 2026-08 (Kenneth R.
  French Data Library, CRSP 202608). Erstes Signal 1927-03-03, alle Reihen ab
  1927-03-05 (99,5 Jahre).
- Signal am Tagesschluss: Index über seinem Durchschnitt der letzten 200
  Handelstage heißt „an" (73 % der Zeit, 5,7 Umschichtungen je Jahr), sonst
  „aus". Umschichtung einen Tag später zum Schluss, 5 bps je Order.
- „An": Produkt mit Hebel L (nachgebildet: L × Markt − (L − 1) × (RF +
  0,50 % p.a.) − 0,95 % p.a.). „Aus": Schatzwechsel.
- Vergleiche: Markt halten; das 3×-Produkt halten; festes Gemisch aus
  Hebelprodukt und Schatzwechseln mit demselben größten Rückgang; die
  Trailing-Stop-Regeln der Reihe in einer Tagesschluss-Fassung.

## Wachstum und größter Rückgang

Je Abschnitt neu bei 1,0 gestartet; Rückgang auf Tagesschlüssen.

| Reihe | gesamt | bis 1976 | ab 1977 | ab 2016 |
|---|---|---|---|---|
| Markt halten | 10,2 % p.a., −84,1 % | 8,4 %, −84,1 % | 12,0 %, −54,6 % | 15,1 %, −34,2 % |
| 3×-Produkt halten | 12,2 %, −99,9 % | 8,6 %, −99,9 % | 16,0 %, −98,0 % | 28,9 %, −77,2 % |
| 200-Tage-Regel ohne Hebel | 10,4 %, −40,3 % | 10,9 %, −40,3 % | 9,8 %, −29,4 % | 11,8 %, −22,3 % |
| 200-Tage-Regel mit 3× | 20,0 %, −84,4 % | 24,3 %, −84,4 % | 15,8 %, −72,9 % | 26,1 %, −56,5 % |

## Vorregistrierte Urteile zur 200-Tage-Regel

A = Sharpe(Regel) − Sharpe(Markt halten). B = Log-Ertrag je Monat, Regel
minus Gemisch gleichen Rückgangs (w = Anteil im Hebelprodukt). Intervalle
95 %, Block-Bootstrap über Monate.

| Hebel | A gesamt | bis 1976 | ab 1977 | ab 2016 | Urteil A | B gesamt | bis 1976 | ab 1977 | ab 2016 | Urteil B |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | +0,15 [−0,03; +0,32] | +0,32 | −0,06 | −0,06 | nicht belegt | +0,70 % [+0,24; +1,16], w 0,36 | +1,07 | +0,33 | +0,82 | **belegt** |
| 2 | +0,13 [−0,04; +0,31] | +0,31 | −0,08 | −0,06 | nicht belegt | +0,57 % [+0,26; +0,87], w 0,33 | +0,82 | +0,31 | +0,65 | **belegt** |
| 1 | +0,16 [−0,02; +0,34] | +0,34 | −0,06 | −0,01 | nicht belegt | +0,35 % [+0,20; +0,50], w 0,33 | +0,48 | +0,22 | +0,39 | **belegt** |

Kontrollen bestanden: Positivkontrolle A = +3,36 [+2,77; +4,48];
Nullkontrolle A = −0,06 [−0,17; +0,05]; Nachbildung 3× aus QQQ gegen echten
TQQQ über 8,3 Jahre −1,12 % p.a. (erlaubt −3,5 bis +1,5).

Nebenfassung ohne Verzögerung (3×): 23,0 % p.a., A = +0,21 [+0,04; +0,38],
ab 1977 −0,01, ab 2016 −0,08.

Nachprüfung (nicht vorregistriert): Wird das Gemisch in jedem Abschnitt neu
auf denselben Rückgang eingestellt, bleibt die Regel vorn. Mit 3×: ab 1977
15,8 % p.a. gegen 12,7 % (w 0,45), ab 2016 26,1 % gegen 22,6 % (w 0,66).
Ohne Hebel: ab 1977 9,8 % gegen 8,2 % (w 0,47), ab 2016 11,8 % gegen 10,5 %
(w 0,63).

## Trailing-Stop-Regeln in Tagesschluss-Fassung

Vor 2018 gibt es keine Minutenkurse; die Regeln wurden deshalb auf
Tagesschlüssen nachgebildet (Verkauf zum Schluss, sobald er T % unter dem
höchsten Schluss seit dem Kauf liegt).

| Regel auf dem 3×-Produkt | p.a. | größter Rückgang | A gesamt | bis 1976 | ab 1977 | ab 2016 | Urteil A | Urteil B |
|---|---|---|---|---|---|---|---|---|
| Montag-Wiederkauf T 5 % | 29,6 % | −95,3 % | +0,29 [+0,15; +0,43] | +0,49 | +0,05 | −0,02 | Hinweis | belegt |
| Montag-Wiederkauf T 6 % | 29,4 % | −94,1 % | +0,30 [+0,15; +0,44] | +0,49 | +0,06 | +0,11 | belegt | belegt |
| Montag-Wiederkauf T 7 % | 25,6 % | −95,7 % | +0,22 [+0,09; +0,34] | +0,39 | +0,00 | +0,12 | belegt | belegt |
| Montag-Wiederkauf T 8 % | 24,8 % | −95,7 % | +0,19 [+0,07; +0,31] | +0,35 | −0,01 | +0,06 | Hinweis | belegt |
| Monatsregel T 5 % | 12,6 % | −94,9 % | −0,02 [−0,25; +0,19] | +0,15 | −0,23 | −0,04 | nicht belegt | nicht belegt |
| Monatsregel T 6 % | 11,9 % | −96,0 % | −0,04 [−0,27; +0,17] | +0,11 | −0,24 | −0,15 | nicht belegt | nicht belegt |
| Monatsregel T 7 % | 12,0 % | −97,9 % | −0,05 [−0,26; +0,14] | +0,13 | −0,28 | −0,14 | nicht belegt | nicht belegt |
| Monatsregel T 8 % | 10,8 % | −98,4 % | −0,08 [−0,29; +0,11] | +0,12 | −0,33 | −0,09 | nicht belegt | nicht belegt |

**Die formalen „belegt" für den Montag-Wiederkauf tragen nicht.**
Nachprüfung (nicht vorregistriert):

- Die alten Indexdaten setzen sich von Tag zu Tag fort, die neuen nicht:
  Autokorrelation der Tageserträge bis 1976 +0,108, ab 1977 −0,022, ab 2016
  −0,132; Ertrag am Tag nach einem Minustag bis 1976 −0,095 %, ab 2016
  +0,113 %. Eine Regel, die am auslösenden Schluss selbst verkauft, nutzt das
  aus, obwohl sich der Index zu diesem Schluss nicht handeln ließ.
- Wird jede Order einen Schluss später ausgeführt (wie bei der
  200-Tage-Regel), bleibt nichts: Montag-Wiederkauf T 5 % mit 3× fällt von
  29,6 % auf 16,7 % p.a., A von +0,29 auf +0,04 [−0,10; +0,17] (ab 1977
  −0,20, ab 2016 −0,25), B von +1,19 % auf +0,25 % [−0,15; +0,66].
- Auf den echten Tagesschlüssen von TQQQ, UPRO, SOXL und TNA (2019 bis 2026)
  liegt die Tagesschluss-Fassung weit neben der Rechnung aus Minutenkursen
  (TQQQ, T 5 %: Endwert 1,45 gegen 5,13).

Monatsregel: nirgends ein Vorteil. Ohne Hebel liegt sie bei A gesichert unter
dem Halten (T 5 %: −0,18 [−0,35; −0,01]; T 7 %: −0,19 [−0,34; −0,05]; T 8 %:
−0,23 [−0,37; −0,09]).

C (200-Tage-Regel gegen Trailing-Stop-Regel, 3×): gegen die Monatsregel
+0,17 bis +0,23 (belegt bei T 7 und 8 %, Hinweis bei T 6 %); gegen den
Montag-Wiederkauf −0,15 bis −0,05, nicht belegt.

## Gegenprobe mit echten Kursen (nur beschreibend)

Signal aus den Tagesschlüssen des Index-ETF, Umschichtung zur nächsten
Eröffnung, 5 bps, Bargeld mit RF; alle Reihen ab 2019-02-25 bis 2026-10-02.

| ETF (Linie von) | Index-ETF halten | 3×-ETF halten | 200-Tage-Regel | Montag-Wiederkauf T 5–8 % | Monatsregel T 5–8 % |
|---|---|---|---|---|---|
| TQQQ (QQQ) | 4,30 (−36 %) | 12,46 (−82 %) | 18,68 (−58 %) | 5,13 bis 16,03 | 4,34 bis 14,28 |
| UPRO (SPY) | 2,74 (−34 %) | 6,26 (−77 %) | 4,59 (−55 %) | 3,92 bis 8,19 | 4,68 bis 8,06 |
| SOXL (SOXX) | 9,38 (−46 %) | 17,95 (−91 %) | 14,84 (−83 %) | 4,92 bis 54,43 | 1,71 bis 21,88 |
| TNA (IWM) | 1,77 (−41 %) | 0,87 (−85 %) | 1,31 (−60 %) | 1,41 bis 2,20 | 2,66 bis 4,62 |

Endwert bei Start 1,00, in Klammern der größte Rückgang. Die Trailing-Stop-
Spalten stammen aus den Minutenkursen (5 bps, Bargeld mit RF).

## Ablesung

- **Als Ertragsbringer nicht belegt.** Risikobereinigt war die 200-Tage-Regel
  nur vor 1977 besser als das Halten des Marktes; seither nicht.
- **Als Absicherung belegt.** Bei gleichem größten Rückgang brachte sie mehr
  als „einfach weniger Hebel", über die ganze Zeit, in beiden Hälften und
  nach 2016. Das ist das erste bestandene Urteil der Reihe.
- **Seit 1977** liefert „3× mit Regel" etwa den Ertrag von „3× halten"
  (15,8 % gegen 16,0 % p.a.), bei −73 % statt −98 % größtem Rückgang. Gegen
  den ungehebelten Markt (12,0 %, −55 %) ist das mehr Ertrag bei mehr
  Rückgang.
- **Ohne Hebel** kostet die Regel seit 1977 Ertrag (9,8 % gegen 12,0 % p.a.)
  und halbiert den größten Rückgang (−29 % gegen −55 %).
- **Echte ETFs 2019 bis 2026:** der Rückgang war bei allen vier kleiner, der
  Endwert bei zwei höher (TQQQ, TNA) und bei zwei niedriger (UPRO, SOXL). Bei
  SOXL half die Regel kaum (−83 % gegen −91 %).
- **Die Trailing-Stop-Regeln bestehen den langen Test nicht.** Der scheinbare
  Vorteil des Montag-Wiederkaufs ist eine Eigenheit alter Indexdaten.

## Was das nicht trägt

Vor 2008 gab es kein dreifach gehebeltes Produkt; Zinsen und Gebühren sind
angenommen. Der größte Rückgang der ganzen Zeit ist ein einzelnes Ereignis
(1929 bis 1932), an dem der Hauptvergleich B hängt. Steuern sind nicht
gerechnet. Ab 2016 sind es gut zehn Jahre.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`french.py`, `longhist_common.py`, `longhist_trend.py`,
`longhist_trend_posthoc.py`, `results_longhist_trend*_2026-10-05.*`), Daten
unter `data/french/`; nicht im Repo.

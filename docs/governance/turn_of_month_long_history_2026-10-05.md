# Nur um den Monatswechsel investiert: knapp 100 Jahre US-Markt

Stand 2026-10-05. Auftrag des Operators vom selben Tag („Bitte Vorschläge 2
bis 4 rechnen"). Eine Rückschau, kein Track Record. Kandidat `monatswechsel`
der Kandidaten-Werkstatt; die Festlegung
`festlegungen/monatswechsel__us_markt_1926.md` wurde vor dem Lauf geschrieben.

## Regel und Daten

- Fenster: der letzte Handelstag eines Monats und die ersten drei des
  Folgemonats (18,3 % aller Handelstage), wie bei Lakonishok/Smidt 1988 und
  McConnell/Xu 2008.
- Daten: US-Markt täglich 1926-07 bis 2026-08 (Kenneth R. French Data
  Library, CRSP 202608). Ab 2006 liegen die Daten nach der letzten
  Veröffentlichung.
- Handelbare Fassung: Kauf zum Schluss des vorletzten Handelstags, Verkauf zum
  Schluss des dritten Handelstags, dazwischen das 3×-Produkt (nachgebildet wie
  in `trend200_leveraged_long_history_2026-10-05.md`), sonst Schatzwechsel;
  5 bps je Order.

## Der Effekt vor Kosten

Mittlerer täglicher Überschussertrag des Marktes über RF.

| Abschnitt | Fenstertag | übriger Tag | Unterschied | Anteil am gesamten Überschussertrag |
|---|---|---|---|---|
| gesamt | +0,127 % | +0,010 % | +0,118 % [+0,087; +0,146] | 75 % bei 18 % der Tage |
| bis 1976 | +0,158 % | −0,000 % | +0,158 % | 100 % |
| ab 1977 | +0,096 % | +0,021 % | +0,075 % | 52 % |
| ab 2006 | +0,047 % | +0,042 % | +0,005 % [−0,050; +0,065] | 21 % bei 19 % der Tage |

Je Jahrzehnt (Unterschied in % je Tag): 1930er +0,201, 1950er +0,174, 1980er
+0,155, 1990er +0,084, 2000er +0,070, 2010er +0,008, 2020er +0,031.

**Vorregistriertes Urteil zum Effekt: belegt.** Das Urteil ist formal: Die
Festlegung verlangte für die Zeit nach der Veröffentlichung nur einen
Punktwert über null, und der liegt bei +0,005 % je Tag. Seit 2006 ist vom
Effekt praktisch nichts übrig.

Vergleichsfenster in der Monatsmitte (Handelstage 9 bis 12, ohne Urteil):
−0,003 % [−0,033; +0,027]; ab 2006 +0,067 % [+0,017; +0,114].

## Die handelbaren Fassungen nach Kosten

| Reihe | gesamt p.a. | größter Rückgang | bis 1976 | ab 1977 | ab 2006 | Sharpe gegen Markt halten |
|---|---|---|---|---|---|---|
| Markt halten | 10,3 % | −84,1 % | 8,6 % | 12,0 % | 11,4 % | |
| nur Fenster, 3× | 19,2 % | −59,8 % | 23,7 % | 14,7 % | 4,2 % | +0,31 [+0,10; +0,51]; ab 2006 −0,44 [−0,91; −0,04] |
| nur Fenster, ohne Hebel | 8,1 % | −23,8 % | 8,7 % | 7,5 % | 2,6 % | +0,22 [+0,01; +0,42]; ab 2006 −0,51 [−1,00; −0,09] |
| nur die übrigen Tage, ohne Hebel | 2,8 % | −85,2 % | −0,4 % | 6,1 % | 7,9 % | −0,40 [−0,49; −0,31] |

**Vorregistriertes Urteil „nutzbar" (nur Fenster, 3×): Hinweis.** Über die
ganze Zeit gesichert besser als das Halten, in der zweiten Hälfte gleichauf
(+0,00), seit 2006 gesichert schlechter.

## Anwendung auf ETFs (nur beschreibend)

Tagesschlüsse ab Mai 2018, Fenster nach dem Handelskalender von SPY (19 % der
Tage).

- TQQQ, QQQ, UPRO, SOXL, TNA: Fenstertage vorn bei 4 von 5; im Median
  entfallen 39 % des Log-Ertrags auf das Fenster.
- 15 Themen-ETFs mit genug Historie: Fenstertage vorn bei 13 von 15; im
  Median 37 %. Am stärksten bei Uran (URA 98 %, URNM 74 %) und Rüstung (ITA
  54 %, XAR 50 %, PPA 49 %, SHLD 58 %); umgekehrt bei DMAT und SETM.

Nachprüfung (nicht vorregistriert): Im breiten Markt beträgt der Unterschied
ab 2018-05 +0,033 % je Tag [−0,066; +0,130]. Die Neigung der letzten acht
Jahre ist also da, aber nicht von Zufall zu unterscheiden.

## Ablesung

- **Der Effekt war jahrzehntelang groß und ist verschwunden.** Bis 1976
  entstand der gesamte Überschussertrag des Marktes an den vier Fenstertagen;
  seit der Veröffentlichung sind es gewöhnliche Tage.
- **Nicht nutzbar.** Seit 2006 brachte die handelbare Fassung 4,2 % p.a.
  gegen 11,4 % beim Halten.
- **Zur Monatsregel der Reihe:** Dass sie in den ETF-Daten ab 2018 Ertrag
  liegen ließ, passt zur Neigung dieser acht Jahre; ein verlässlicher Effekt
  ist es nicht.

## Was das nicht trägt

Die Regel des Urteils war zu weich für einen Effekt, der nach der
Veröffentlichung auf null fällt; das Urteil „belegt" beschreibt die
Vergangenheit. Das 3×-Produkt ist vor 2008 nachgebildet. Steuern sind nicht
gerechnet.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`french.py`, `longhist_common.py`, `longhist_tom.py`,
`results_longhist_tom*_2026-10-05.*`), Daten unter `data/french/`; nicht im
Repo.
